"""Cursor: `cursor-agent about --format json` exposes the plan only. Usage stays UNSUPPORTED."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime

from .. import normalize as N
from ._allow import check_argv

ALIAS = "cursor-premium"
METHOD = "cursor-agent about reports plan only"
REASON = "Usage is visible in Cursor's UI only; enter it manually to track it"


def _reading(now, outcome, reason, plan=None):
    return N.make_reading(ALIAS, "cursor-cli", METHOD, now, outcome, plan=plan, reason=reason)


def parse_about(text: str, now: datetime) -> dict:
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):
        return _reading(now, "error", "cursor-agent about returned malformed JSON")
    if not isinstance(data, dict):
        return _reading(now, "error", "cursor-agent about returned an unexpected shape")
    return _reading(now, "unsupported", REASON, plan=data.get("subscriptionTier"))  # email etc. dropped


def collect(binary: str = "cursor-agent", *, timeout: float = 15.0, now: datetime | None = None,
            run=subprocess.run) -> dict:
    stamp = now or N.now_utc()
    try:
        argv = check_argv([binary, "about", "--format", "json"])
        proc = run(argv, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        return _reading(stamp, "error", "cursor-agent binary not found on PATH")
    except subprocess.TimeoutExpired:
        return _reading(stamp, "error", f"cursor-agent about did not answer within {timeout:g}s")
    except OSError as exc:
        return _reading(stamp, "error", f"could not run cursor-agent: {type(exc).__name__}")
    if proc.returncode != 0:
        return _reading(stamp, "error", f"cursor-agent about exited with status {proc.returncode}")
    return parse_about(proc.stdout, stamp)
