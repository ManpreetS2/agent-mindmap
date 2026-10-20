#!/usr/bin/env python3
"""QA harness for MM-011 live daemon (Linux). Evidence only — does not modify product code."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path("/tmp/mm011-qa")
RUN = Path("/tmp/mm011-qa-run")
EV = Path("/tmp/mm011-qa-evidence-0fa142f")
EV.mkdir(parents=True, exist_ok=True)

PORT = 18787
PORT2 = 18788

results: list[dict] = []


def record(check: str, ok: bool, expected: str, actual: str, **extra) -> None:
    entry = {"check": check, "ok": ok, "expected": expected, "actual": actual, **extra}
    results.append(entry)
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {check}: {actual}")


def http_raw(
    host: str,
    port: int,
    method: str,
    path: str,
    headers: dict[str, str] | None = None,
    body: bytes = b"",
) -> tuple[int, dict[str, str], bytes]:
    """Raw TCP HTTP to observe Host header behavior without urllib Host rewriting."""
    hdrs = {"Host": f"{host}:{port}", "Connection": "close"}
    if headers:
        hdrs.update(headers)
    req = f"{method} {path} HTTP/1.1\r\n"
    for k, v in hdrs.items():
        req += f"{k}: {v}\r\n"
    if body:
        req += f"Content-Length: {len(body)}\r\n"
    req += "\r\n"
    data = req.encode() + body
    with socket.create_connection((host, port), timeout=5) as sock:
        sock.sendall(data)
        chunks = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    raw = b"".join(chunks)
    head, _, rest = raw.partition(b"\r\n\r\n")
    lines = head.decode("latin-1", errors="replace").split("\r\n")
    status_line = lines[0] if lines else ""
    try:
        code = int(status_line.split()[1])
    except (IndexError, ValueError):
        code = 0
    resp_headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            resp_headers[k.strip().lower()] = v.strip()
    return code, resp_headers, rest


def wait_port(host: str, port: int, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.2):
                return True
        except OSError:
            time.sleep(0.05)
    return False


def start_daemon(
    *,
    port: int,
    log_name: str,
    env_extra: dict[str, str] | None = None,
    ledger: Path | None = None,
) -> subprocess.Popen:
    env = os.environ.copy()
    env["PATH"] = f"{RUN / 'bin'}:{env.get('PATH', '')}"
    env["PYTHONPATH"] = str(ROOT)
    env["MOCK_GH_LOG"] = str(RUN / "logs" / "gh-calls.log")
    env["MINDMAP_LEDGER"] = str(ledger or RUN / "ledger" / "task-ledger.md")
    if env_extra:
        env.update(env_extra)
    log_path = RUN / "logs" / log_name
    log_f = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "ingest.live",
            "--ledger",
            env["MINDMAP_LEDGER"],
            "--static-dir",
            str(RUN / "dist"),
            "--activity-out",
            str(RUN / "dist" / "activity.json"),
            "--cache-dir",
            str(RUN / "cache"),
            "--port",
            str(port),
            "--ledger-poll-sec",
            "2",
            "--gh-poll-sec",
            "3",
        ],
        cwd=str(ROOT),
        env=env,
        stdout=log_f,
        stderr=subprocess.STDOUT,
        text=True,
    )
    proc._qa_log = log_f  # type: ignore[attr-defined]
    proc._qa_log_path = log_path  # type: ignore[attr-defined]
    return proc


def stop_proc(proc: subprocess.Popen, sig: int = signal.SIGTERM, wait: float = 8.0) -> dict:
    before_children = list_children(proc.pid)
    proc.send_signal(sig)
    try:
        proc.wait(timeout=wait)
        exit_code = proc.returncode
        timed_out = False
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=3)
        exit_code = proc.returncode
        timed_out = True
    time.sleep(0.3)
    after_alive = False
    try:
        os.kill(proc.pid, 0)
        after_alive = True
    except OSError:
        after_alive = False
    orphans = []
    for cpid in before_children:
        try:
            os.kill(cpid, 0)
            orphans.append(cpid)
        except OSError:
            pass
    if hasattr(proc, "_qa_log"):
        proc._qa_log.close()  # type: ignore[attr-defined]
    return {
        "exit_code": exit_code,
        "timed_out": timed_out,
        "still_alive": after_alive,
        "orphans": orphans,
        "log": Path(proc._qa_log_path).read_text(encoding="utf-8", errors="replace"),  # type: ignore[attr-defined]
    }


def list_children(pid: int) -> list[int]:
    try:
        out = subprocess.check_output(["ps", "-o", "pid=", "--ppid", str(pid)], text=True)
    except subprocess.CalledProcessError:
        return []
    return [int(x) for x in out.split() if x.strip().isdigit()]


def ss_listen(port: int) -> str:
    try:
        return subprocess.check_output(
            ["ss", "-ltnp"], text=True, stderr=subprocess.DEVNULL
        )
    except Exception as exc:  # noqa: BLE001
        return f"ss failed: {exc}"


def main() -> int:
    # Clean previous activity
    act = RUN / "dist" / "activity.json"
    if act.exists():
        act.unlink()
    cache = RUN / "cache"
    if cache.exists():
        for p in cache.rglob("*"):
            if p.is_file():
                p.unlink()

    # --- Start primary daemon ---
    proc = start_daemon(port=PORT, log_name="daemon1.log")
    up = wait_port("127.0.0.1", PORT, 15)
    record(
        "daemon_starts_and_binds",
        up and proc.poll() is None,
        "listening on 127.0.0.1 and process alive",
        f"up={up} poll={proc.poll()}",
    )
    if not up:
        log = Path(proc._qa_log_path).read_text(errors="replace")  # type: ignore[attr-defined]
        (EV / "daemon_start_fail.log").write_text(log)
        print(log)
        json.dump(results, open(EV / "harness_results.json", "w"), indent=2)
        return 1

    ss_out = ss_listen(PORT)
    (EV / "ss_listen.txt").write_text(ss_out)
    bind_ok = f":{PORT}" in ss_out and ("127.0.0.1" in ss_out or "127.0.0.1:" + str(PORT) in ss_out)
    # also reject 0.0.0.0
    public = f"*:{PORT}" in ss_out or f"0.0.0.0:{PORT}" in ss_out
    record(
        "bind_127_only",
        bind_ok and not public,
        "ss shows 127.0.0.1 only, not 0.0.0.0",
        f"bind_ok={bind_ok} public={public}; snippet="
        + "\n".join(l for l in ss_out.splitlines() if str(PORT) in l),
    )

    # healthz
    code, _, body = http_raw("127.0.0.1", PORT, "GET", "/healthz")
    health = json.loads(body.decode()) if body else {}
    record(
        "healthz_ok",
        code == 200 and "errors" in health,
        "200 JSON with errors field",
        f"code={code} health={health}",
    )

    # activity exists after first poll
    code, hdrs, body = http_raw("127.0.0.1", PORT, "GET", "/activity.json")
    record(
        "activity_served",
        code == 200 and b"schema_version" in body,
        "200 with activity JSON",
        f"code={code} len={len(body)} etag={hdrs.get('etag')}",
    )
    mtime1 = act.stat().st_mtime_ns if act.exists() else 0
    size1 = act.stat().st_size if act.exists() else 0

    # --- Idempotent: wait a poll cycle without ledger change ---
    time.sleep(5)
    mtime2 = act.stat().st_mtime_ns if act.exists() else 0
    size2 = act.stat().st_size if act.exists() else 0
    record(
        "idempotent_no_rewrite",
        mtime1 == mtime2 and size1 == size2,
        "activity.json mtime/size unchanged across poll with no input change",
        f"mtime1={mtime1} mtime2={mtime2} size1={size1} size2={size2}",
    )

    # --- Schedule refresh on ledger change ---
    ledger = RUN / "ledger" / "task-ledger.md"
    ledger.write_text(ledger.read_text(encoding="utf-8") + "\n# QA trigger note\n", encoding="utf-8")
    deadline = time.monotonic() + 10
    refreshed = False
    while time.monotonic() < deadline:
        if act.exists() and act.stat().st_mtime_ns != mtime2:
            refreshed = True
            break
        time.sleep(0.2)
    record(
        "refresh_on_ledger_change",
        refreshed,
        "activity.json rewritten within ~10s after ledger edit (poll=2s)",
        f"refreshed={refreshed} new_mtime={act.stat().st_mtime_ns if act.exists() else None}",
    )

    # --- SEC-MM011-1: Host: evil.example ---
    code_h, hdrs_h, body_h = http_raw(
        "127.0.0.1",
        PORT,
        "GET",
        "/activity.json",
        headers={"Host": "evil.example"},
    )
    (EV / "host_evil_response.txt").write_text(
        f"status={code_h}\nheaders={json.dumps(hdrs_h)}\nbody_prefix={body_h[:200]!r}\n"
    )
    # Expected secure behavior: reject (400/403/421) — actual likely serves 200 (no Host allowlist)
    record(
        "SEC-MM011-1_host_header_allowlist",
        code_h in (400, 403, 421),
        "reject or ignore foreign Host (400/403/421); not serve app content",
        f"status={code_h} body_has_schema={b'schema_version' in body_h} "
        f"(DNS rebinding possible if 200 with content)",
        severity="LOW",
        finding_id="SEC-MM011-1",
    )

    # --- Methods: only GET/HEAD ---
    method_results = {}
    for method in ("POST", "PUT", "DELETE", "PATCH", "OPTIONS"):
        code_m, _, _ = http_raw("127.0.0.1", PORT, method, "/activity.json", body=b"{}")
        method_results[method] = code_m
    # HEAD should work
    code_head, _, body_head = http_raw("127.0.0.1", PORT, "HEAD", "/activity.json")
    method_results["HEAD"] = code_head
    method_results["HEAD_body_empty"] = len(body_head) == 0
    # BaseHTTPRequestHandler returns 501 for unimplemented methods (PATCH/OPTIONS)
    # Product implements POST/PUT/DELETE → 405. PATCH/OPTIONS may be 501.
    bad_ok = all(method_results[m] in (405, 501) for m in ("POST", "PUT", "DELETE", "PATCH", "OPTIONS"))
    head_ok = code_head == 200 and len(body_head) == 0
    record(
        "methods_get_head_only",
        bad_ok and head_ok,
        "non-GET/HEAD → 405 (or 501 if unimplemented); HEAD 200 empty body",
        f"{method_results}",
    )

    # --- Path traversal ---
    trav = {}
    for path in (
        "/../etc/passwd",
        "/%2e%2e/etc/passwd",
        "/..%2fetc/passwd",
        "/%2e%2e%2fetc%2fpasswd",
        "/assets/../../etc/passwd",
        "/./../../etc/passwd",
    ):
        code_t, _, body_t = http_raw("127.0.0.1", PORT, "GET", path)
        trav[path] = {"status": code_t, "leaked": b"root:" in body_t or b"/bin/" in body_t}
    trav_ok = all(v["status"] in (400, 404) and not v["leaked"] for v in trav.values())
    (EV / "path_traversal.json").write_text(json.dumps(trav, indent=2))
    record(
        "path_traversal_blocked",
        trav_ok,
        "traversal paths → 400/404 and no /etc/passwd content",
        json.dumps(trav),
    )

    # --- File permissions / write paths ---
    written = []
    for p in [act, *cache.rglob("*")]:
        if p.is_file():
            mode = oct(p.stat().st_mode & 0o777)
            written.append({"path": str(p), "mode": mode})
    (EV / "written_files.json").write_text(json.dumps(written, indent=2))
    outside = [
        w
        for w in written
        if not (
            w["path"].startswith(str(RUN / "dist"))
            or w["path"].startswith(str(RUN / "cache"))
            or w["path"].startswith(str(RUN / "logs"))
            or w["path"].startswith(str(RUN / "ledger"))
        )
    ]
    # modes: not world-writable
    bad_modes = [w for w in written if int(w["mode"], 8) & 0o002]
    record(
        "writes_only_intended_paths",
        len(outside) == 0,
        "only activity under dist + cache under --cache-dir",
        f"files={len(written)} outside={outside}",
    )
    record(
        "file_permissions_sane",
        len(bad_modes) == 0,
        "no world-writable files among daemon outputs",
        f"bad_modes={bad_modes} sample={written[:5]}",
    )

    # --- Logs: no tokens ---
    log1 = Path(proc._qa_log_path).read_text(errors="replace")  # type: ignore[attr-defined]
    gh_log = (RUN / "logs" / "gh-calls.log").read_text(errors="replace") if (RUN / "logs" / "gh-calls.log").exists() else ""
    token_pat = ("ghp_", "gho_", "github_pat_", "Bearer ", "Authorization:")
    combined_logs = log1 + "\n" + gh_log
    leaks = [t for t in token_pat if t.lower() in combined_logs.lower()]
    # Also inject a fake failure with token in stderr path via FAIL — separate phase
    record(
        "logs_no_tokens",
        len(leaks) == 0,
        "daemon + mock gh logs contain no token patterns",
        f"leaks={leaks} log_bytes={len(combined_logs)}",
    )
    (EV / "daemon1.log").write_text(log1)

    # --- Second instance / locking ---
    # Same port should fail to bind
    proc2 = start_daemon(port=PORT, log_name="daemon2-sameport.log")
    time.sleep(2)
    same_port_alive = proc2.poll() is None
    # If still alive, it might have failed later — check if two listeners
    ss2 = ss_listen(PORT)
    listeners = [l for l in ss2.splitlines() if str(PORT) in l]
    stop_info2 = stop_proc(proc2, signal.SIGTERM, wait=3)
    record(
        "locking_same_port",
        not same_port_alive or len(listeners) <= 1,
        "second instance cannot serve on same port (OS bind or explicit lock)",
        f"proc2_alive_after_2s={same_port_alive} listeners={listeners} "
        f"exit={stop_info2['exit_code']} log_tail={stop_info2['log'][-400:]}",
    )

    # Different port — both can run (no flock/pidfile in product)
    proc3 = start_daemon(port=PORT2, log_name="daemon3-diffport.log", env_extra={"MOCK_GH_LOG": str(RUN / "logs" / "gh-calls-3.log")})
    up3 = wait_port("127.0.0.1", PORT2, 10)
    both = up3 and proc.poll() is None and proc3.poll() is None
    record(
        "locking_prevents_two_instances",
        not both,  # FAIL if product lacks singleton lock
        "explicit lock/pidfile prevents two daemon instances even on different ports",
        f"both_running={both} up3={up3} (product appears to have no singleton lock)",
        severity="MEDIUM",
        note="Port collision alone is not a full singleton lock",
    )
    if proc3.poll() is None:
        stop_proc(proc3, signal.SIGTERM)

    # --- gh failure / backoff (no tight loop) ---
    # Restart with FAIL_GH and measure poll call rate
    stop_info = stop_proc(proc, signal.SIGTERM)
    record(
        "sigterm_clean",
        not stop_info["timed_out"] and not stop_info["still_alive"] and not stop_info["orphans"],
        "SIGTERM exits promptly, no orphans",
        f"exit={stop_info['exit_code']} timed_out={stop_info['timed_out']} "
        f"orphans={stop_info['orphans']} still_alive={stop_info['still_alive']}",
    )

    # Clear gh log and start with FAIL_GH
    fail_log = RUN / "logs" / "gh-calls-fail.log"
    if fail_log.exists():
        fail_log.unlink()
    proc_f = start_daemon(
        port=PORT,
        log_name="daemon-fail.log",
        env_extra={"FAIL_GH": "1", "MOCK_GH_LOG": str(fail_log)},
    )
    wait_port("127.0.0.1", PORT, 10)
    time.sleep(8)
    calls = fail_log.read_text().splitlines() if fail_log.exists() else []
    # With gh-poll-sec=3 and ledger-poll-sec=2 over ~8s, expect roughly handful of calls, not hundreds
    tight = len(calls) > 40
    code_f, _, body_f = http_raw("127.0.0.1", PORT, "GET", "/healthz")
    health_f = json.loads(body_f.decode()) if body_f else {}
    still_serving = code_f == 200
    # activity should still be last-good if present
    act_exists = act.exists()
    record(
        "gh_down_recovers_no_tight_loop",
        still_serving and not tight and bool(health_f.get("errors")),
        "keeps serving, records errors, poll rate bounded by interval (not spin)",
        f"health_status={code_f} errors={health_f.get('errors')} "
        f"gh_calls_in_8s={len(calls)} tight={tight} activity_kept={act_exists}",
    )
    (EV / "gh_fail_calls.txt").write_text("\n".join(calls))
    (EV / "daemon-fail.log").write_text(Path(proc_f._qa_log_path).read_text(errors="replace"))  # type: ignore[attr-defined]

    # Rate-limit backoff path
    stop_proc(proc_f, signal.SIGTERM)
    rl_log = RUN / "logs" / "gh-calls-rl.log"
    if rl_log.exists():
        rl_log.unlink()
    proc_rl = start_daemon(
        port=PORT,
        log_name="daemon-rl.log",
        env_extra={"RATE_LIMIT": "1", "MOCK_GH_LOG": str(rl_log)},
    )
    wait_port("127.0.0.1", PORT, 10)
    time.sleep(7)
    rl_calls = rl_log.read_text().splitlines() if rl_log.exists() else []
    code_rl, _, body_rl = http_raw("127.0.0.1", PORT, "GET", "/healthz")
    health_rl = json.loads(body_rl.decode()) if body_rl else {}
    # After first rate-limit, subsequent polls should skip (backoff) — fewer gh invocations
    record(
        "rate_limit_backoff",
        code_rl == 200 and len(rl_calls) < 40,
        "rate-limit sets backoff; process keeps serving; no tight loop",
        f"calls={len(rl_calls)} health_errors={health_rl.get('errors')}",
    )
    (EV / "daemon-rl.log").write_text(Path(proc_rl._qa_log_path).read_text(errors="replace"))  # type: ignore[attr-defined]

    # SIGINT
    stop_rl = stop_proc(proc_rl, signal.SIGINT)
    record(
        "sigint_clean",
        not stop_rl["timed_out"] and not stop_rl["still_alive"] and not stop_rl["orphans"],
        "SIGINT exits promptly, no orphans",
        f"exit={stop_rl['exit_code']} timed_out={stop_rl['timed_out']} orphans={stop_rl['orphans']}",
    )

    # Port free after shutdown
    time.sleep(0.5)
    port_free = not wait_port("127.0.0.1", PORT, 1.0)
    record(
        "port_released_after_shutdown",
        port_free,
        "port not listening after SIGINT shutdown",
        f"port_free={port_free}",
    )

    # Persist
    out = EV / "harness_results.json"
    out.write_text(json.dumps(results, indent=2))
    failed = [r for r in results if not r["ok"]]
    print(f"\n=== {len(results) - len(failed)}/{len(results)} checks passed ===")
    for f in failed:
        print(f"  FAIL: {f['check']}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
