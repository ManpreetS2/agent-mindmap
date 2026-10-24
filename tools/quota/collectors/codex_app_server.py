"""Codex: `codex app-server` over stdio, methods initialize / initialized / account/rateLimits/read only."""
from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from datetime import datetime

from .. import normalize as N
from ..models import QuotaError
from ._allow import check_argv, check_method

METHOD = "codex app-server account/rateLimits/read"
ALIAS = "codex"
_AUTH_HINTS = ("auth", "login", "log in", "sign in", "unauthor", "token", "credential")


def _error(now: datetime, reason: str) -> dict:
    return N.make_reading(ALIAS, "codex-app-server", METHOD, now, "error", reason=reason)


def map_rate_limits(result: dict, now: datetime) -> dict:
    """account/rateLimits/read result -> reading. accountId and credits are never copied."""
    limits = result.get("rateLimits") if isinstance(result, dict) else None
    if not isinstance(limits, dict):
        return _error(now, "Codex returned no rateLimits object")
    windows, seen = [], set()
    for slot in ("primary", "secondary"):
        raw = limits.get(slot)
        if not isinstance(raw, dict):
            continue
        used = N.pct(raw.get("usedPercent"))
        if used is None:
            continue
        mins = N.minutes(raw.get("windowDurationMins"))
        wtype, label = N.classify_window(mins, slot)
        key = (wtype, mins if wtype == "other" else None)
        if key in seen:
            return _error(now, f"Codex returned two {wtype} windows; refusing to guess which is current")
        seen.add(key)
        reset_raw = raw.get("resetsAt")
        resets = N.epoch_to_dt(reset_raw)
        windows.append(N.make_window(wtype, label, mins, used, resets))
    allowed = result.get("ordinaryUsageAllowed")
    allowed = allowed if isinstance(allowed, bool) else None  # null = unknown, never inferred
    reason = None
    if not windows:
        reason = "Codex returned no usable rate-limit windows"
    elif allowed is False:
        reason = "Codex reports ordinary usage is not currently allowed"
    return N.make_reading(ALIAS, "codex-app-server", METHOD, now, "ok", plan=limits.get("planType"),
                          reason=reason, windows=windows, ordinary_usage_allowed=allowed)


class _Rpc:
    def __init__(self, proc):
        self.proc, self.lines = proc, queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        try:
            for line in iter(lambda: self.proc.stdout.readline(1 << 20), ""):
                self.lines.put(line)
        except (OSError, ValueError):
            pass
        self.lines.put(None)

    def send(self, method: str, params=None, msg_id: int | None = None):
        check_method(method)
        msg = {"method": method}
        if msg_id is not None:
            msg["id"] = msg_id
        if params is not None:
            msg["params"] = params
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def wait_for(self, msg_id: int, deadline: float) -> dict:
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError
            try:
                line = self.lines.get(timeout=left)
            except queue.Empty:
                raise TimeoutError from None
            if line is None:
                raise EOFError
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if isinstance(msg, dict) and msg.get("id") == msg_id and ("result" in msg or "error" in msg):
                return msg


def _terminate(proc):
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)
    except OSError:
        pass
    for stream in (proc.stdin, proc.stdout):
        try:
            stream.close()
        except (OSError, ValueError):
            pass


def _rpc_failure(msg: dict) -> str:
    err = msg.get("error")
    text = json.dumps(err).lower() if err is not None else ""
    if any(h in text for h in _AUTH_HINTS):
        return "Codex is not logged in or authentication failed (run `codex login`)"
    code = err.get("code") if isinstance(err, dict) else None
    return f"Codex app-server returned an error{f' (code {code})' if isinstance(code, int) else ''}"


def collect(binary: str = "codex", *, timeout: float = 20.0, now: datetime | None = None,
            popen=subprocess.Popen) -> dict:
    """Return a reading (never raises, never a traceback). Zero model calls."""
    stamp = now or N.now_utc()
    try:
        argv = check_argv([binary, "app-server"])
        proc = popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    except FileNotFoundError:
        return _error(stamp, "codex binary not found on PATH")
    except (OSError, QuotaError) as exc:
        return _error(stamp, f"could not start codex app-server: {type(exc).__name__}")
    try:
        deadline = time.monotonic() + timeout
        rpc = _Rpc(proc)
        rpc.send("initialize", {"clientInfo": {"name": "agent-mindmap-quota", "title": "Agent Mindmap quota",
                                               "version": "1.0.0"}}, msg_id=1)
        init = rpc.wait_for(1, deadline)
        if "error" in init:
            return _error(stamp, _rpc_failure(init))
        rpc.send("initialized")
        rpc.send("account/rateLimits/read", msg_id=2)
        out = rpc.wait_for(2, deadline)
        if "error" in out:
            return _error(stamp, _rpc_failure(out))
        return map_rate_limits(out.get("result"), stamp)
    except TimeoutError:
        return _error(stamp, f"codex app-server did not answer within {timeout:g}s")
    except EOFError:
        return _error(stamp, "codex app-server exited before answering")
    except (OSError, ValueError, QuotaError) as exc:
        return _error(stamp, f"codex collection failed: {type(exc).__name__}")
    finally:
        _terminate(proc)
