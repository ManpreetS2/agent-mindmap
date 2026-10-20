#!/usr/bin/env python3
"""
Independent QA behavioral harness — MM-020d PR #21 @ dd4a343.
Verify-only; does not modify product code.
"""
from __future__ import annotations

import errno
import http.client
import json
import os
import select
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
from http import HTTPStatus
from pathlib import Path

ROOT = Path("/tmp/qa-mm020d-full/checkout")
SHA = "dd4a3431214580a1fae1e4e72d78d84c7c7ae809"
OUT = Path(f"/tmp/qa-mm020d-full/evidence/logs/{SHA}")
OUT.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from ingest.live import (  # noqa: E402
    BIND_HOST,
    MAX_SSE_CONNECTIONS,
    PROCESS_LOCK_MODE,
    SSE_RETRY_AFTER_SEC,
    LiveDaemon,
    ProcessSingletonLock,
    SingletonLockError,
    create_http_server,
    process_lock_path,
)

checks: list[dict] = []
findings: list[dict] = []


def record(check: str, result: str, detail: str = "") -> None:
    checks.append({"check": check, "result": result, "detail": detail})
    print(f"[{result}] {check}" + (f" — {detail}" if detail else ""))


def finding(**kwargs) -> None:
    findings.append(kwargs)
    print(f"[FINDING:{kwargs.get('severity')}] {kwargs.get('component')}: {kwargs.get('actual')}")


def _sample_evt(eid: str, summary: str = "hello") -> dict:
    return {
        "id": eid,
        "ts": "2026-10-20T12:00:00-07:00",
        "sender": "director",
        "group": "build",
        "type": "message",
        "summary": summary,
        "provenance": "agent-reported",
    }


def make_env(tmp: Path) -> dict:
    ledger = ROOT / "tests" / "fixtures" / "ledger-sample.md"
    activity = tmp / "activity.json"
    static = tmp / "static"
    static.mkdir()
    # Minimal static + copy dist assets if present
    dist = ROOT / "web" / "dist"
    if dist.is_dir():
        for p in dist.iterdir():
            dest = static / p.name
            if p.is_file():
                shutil.copy2(p, dest)
            elif p.is_dir():
                shutil.copytree(p, dest, dirs_exist_ok=True)
    else:
        (static / "index.html").write_text("<html><body>ok</body></html>", encoding="utf-8")
    # Ensure activity exists
    demo = ROOT / "web" / "public" / "activity.json"
    if demo.is_file():
        shutil.copy2(demo, activity)
        shutil.copy2(demo, static / "activity.json")
    else:
        activity.write_text("{}", encoding="utf-8")
    cache = tmp / "cache"
    cache.mkdir()
    return {
        "ledger": ledger,
        "activity": activity,
        "static": static,
        "cache": cache,
        "bots": ROOT / "config" / "bots.json",
    }


def daemon_from_env(env: dict, **kw) -> LiveDaemon:
    with env["bots"].open(encoding="utf-8") as f:
        bots = json.load(f)["bots"]
    d = LiveDaemon(
        ledger_source="path",
        ledger_path=env["ledger"],
        ledger_source_url="build/task-ledger.md",
        activity_path=env["activity"],
        static_dir=env["static"],
        cache_dir=env["cache"],
        bots=bots,
        ledger_poll_sec=kw.get("ledger_poll_sec", 3600),
        gh_poll_sec=kw.get("gh_poll_sec", 3600),
        events_source="off",
        events_poll_sec=3600,
    )
    d._load_activity_from_disk()
    d.run_poll_cycle()
    return d


def http_req(
    host: str,
    port: int,
    path: str,
    *,
    method: str = "GET",
    headers: dict | None = None,
    timeout: float = 3.0,
) -> tuple[int, dict, bytes]:
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        conn.request(method, path, headers=headers or {})
        resp = conn.getresponse()
        body = resp.read()
        hdrs = {k: v for k, v in resp.getheaders()}
        return resp.status, hdrs, body
    finally:
        conn.close()


def start_server(daemon: LiveDaemon, *, heartbeat: float = 0.2) -> tuple[object, str, int]:
    httpd = create_http_server(daemon, host=BIND_HOST, port=0, sse_heartbeat_sec=heartbeat)
    host, port = httpd.server_address
    t = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    t.start()
    return httpd, host, int(port)


# --------------- (1) Host/Origin matrix ---------------
def check_host_origin(httpd_pack) -> None:
    httpd, host, port = httpd_pack
    endpoints = ["/healthz", "/activity.json", "/index.html", "/events"]
    allowed_host = f"{host}:{port}"
    results = {}

    # Allowed
    for path in endpoints:
        # For /events we only check status line then close quickly
        if path == "/events":
            conn = http.client.HTTPConnection(host, port, timeout=2)
            conn.request(
                "GET",
                path,
                headers={"Host": allowed_host, "Origin": f"http://{host}:{port}"},
            )
            resp = conn.getresponse()
            status = resp.status
            conn.close()
        else:
            status, _, _ = http_req(
                host,
                port,
                path,
                headers={"Host": allowed_host, "Origin": f"http://{host}:{port}"},
            )
        results[f"allowed:{path}"] = status
        ok = status == 200
        record(
            f"Host/Origin allowed → 200 ({path})",
            "PASS" if ok else "FAIL",
            f"status={status}",
        )
        if not ok:
            finding(
                id="SEC-MM011-1-allowed",
                component=f"MindmapHandler {path}",
                expected="200 for localhost Host+Origin",
                actual=f"status={status}",
                repro=f"GET {path} Host={allowed_host}",
                evidence="host_origin_matrix.json",
                environment=f"@{SHA[:7]}",
                severity="high",
                confidence="high",
            )

    cases = [
        ("evil_host", {"Host": "evil.com", "Origin": f"http://{host}:{port}"}, 403),
        ("dns_rebind_host", {"Host": "attacker.example:8787", "Origin": f"http://{host}:{port}"}, 403),
        ("ip_variant_host_127_1", {"Host": "127.1", "Origin": f"http://{host}:{port}"}, 403),
        ("ip_variant_host_0", {"Host": "0.0.0.0", "Origin": f"http://{host}:{port}"}, 403),
        ("ip_variant_host_ipv6", {"Host": "[::1]:8787", "Origin": f"http://{host}:{port}"}, 403),
        ("missing_host", {"Origin": f"http://{host}:{port}"}, 403),  # no Host header
        ("mismatched_origin", {"Host": allowed_host, "Origin": "https://evil.com"}, 403),
        ("null_origin", {"Host": allowed_host, "Origin": "null"}, 403),  # verify checklist expects 403
    ]

    null_actual = None
    for path in endpoints:
        for name, hdrs, expect in cases:
            # http.client always sends Host; for missing Host use raw socket
            if name == "missing_host":
                status = raw_http_status(host, port, path, extra_headers=["Origin: http://127.0.0.1"])
            else:
                if path == "/events" and expect == 200:
                    continue
                try:
                    if path == "/events":
                        conn = http.client.HTTPConnection(host, port, timeout=2)
                        conn.request("GET", path, headers=hdrs)
                        resp = conn.getresponse()
                        status = resp.status
                        # drain a bit then close
                        conn.close()
                    else:
                        status, _, _ = http_req(host, port, path, headers=hdrs)
                except Exception as exc:  # noqa: BLE001
                    status = f"ERR:{exc}"
            key = f"{name}:{path}"
            results[key] = status
            if name == "null_origin":
                null_actual = status
            # For null_origin: product AC allows 200; checklist wants 403 — record both
            if name == "null_origin":
                continue
            ok = status == expect
            record(
                f"Host/Origin {name} on {path} → {expect}",
                "PASS" if ok else "FAIL",
                f"status={status}",
            )
            if not ok:
                finding(
                    id=f"SEC-MM011-1-{name}",
                    component=f"MindmapHandler {path}",
                    expected=f"HTTP {expect}",
                    actual=f"status={status}",
                    repro=f"GET {path} headers={hdrs}",
                    evidence="host_origin_matrix.json",
                    environment=f"@{SHA[:7]}",
                    severity="high",
                    confidence="high",
                )

    # Null Origin special handling
    # Product/PR/audit: allow Origin:null → 200. Verify checklist: expect 403.
    null_statuses = {k: v for k, v in results.items() if k.startswith("null_origin:")}
    all_200 = all(v == 200 for v in null_statuses.values())
    all_403 = all(v == 403 for v in null_statuses.values())
    record(
        "Origin:null policy (checklist wants 403; PR/audit allow)",
        "FAIL" if all_200 else ("PASS" if all_403 else "FAIL"),
        f"statuses={null_statuses}; PR AC allows null → 200",
    )
    if all_200:
        finding(
            id="SEC-MM011-1-null-origin",
            component="origin_header_allowed",
            expected="Verify checklist: Origin: null → 403 on all endpoints incl. SSE",
            actual="Origin: null accepted (200) — matches PR body/audit “null-or-localhost” policy, not the verify checklist 403",
            repro=f'GET /healthz Host={allowed_host} Origin: null',
            evidence="host_origin_matrix.json",
            environment=f"@{SHA[:7]}",
            severity="medium",
            confidence="high",
            note="PR #21 and docs/MM-020-audit.md §7.1 document allowing null Origin; checklist asks for 403.",
        )

    (OUT / "host_origin_matrix.json").write_text(json.dumps(results, indent=2), encoding="utf-8")


def raw_http_status(host: str, port: int, path: str, extra_headers: list[str] | None = None) -> int:
    """Send request WITHOUT Host header (http.client always adds one)."""
    lines = [f"GET {path} HTTP/1.1"]
    for h in extra_headers or []:
        lines.append(h)
    lines.append("Connection: close")
    lines.append("")
    lines.append("")
    payload = "\r\n".join(lines).encode()
    with socket.create_connection((host, port), timeout=3) as s:
        s.sendall(payload)
        data = b""
        s.settimeout(3)
        try:
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
                if b"\r\n" in data:
                    break
        except socket.timeout:
            pass
    first = data.split(b"\r\n", 1)[0].decode("latin1", errors="replace")
    parts = first.split()
    if len(parts) >= 2 and parts[1].isdigit():
        return int(parts[1])
    return -1


# --------------- (2) SSE ---------------
def read_sse(
    host: str,
    port: int,
    *,
    last_event_id: str | None = None,
    max_events: int = 5,
    timeout: float = 4.0,
    collect_heartbeats: bool = False,
) -> tuple[list[dict], list[str]]:
    headers = {"Host": f"{host}:{port}", "Accept": "text/event-stream"}
    if last_event_id:
        headers["Last-Event-ID"] = last_event_id
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    conn.request("GET", "/events", headers=headers)
    resp = conn.getresponse()
    assert resp.status == 200, resp.status
    deadline = time.monotonic() + timeout
    events: list[dict] = []
    heartbeats: list[str] = []
    buf = b""
    while (len(events) < max_events or collect_heartbeats) and time.monotonic() < deadline:
        # Use select for non-blocking-ish read
        ready, _, _ = select.select([resp.fp], [], [], 0.2)
        if not ready:
            if collect_heartbeats and heartbeats and len(events) >= max_events:
                break
            continue
        chunk = resp.read(1)
        if not chunk:
            break
        buf += chunk
        while b"\n\n" in buf:
            block, buf = buf.split(b"\n\n", 1)
            text = block.decode("utf-8", errors="replace")
            if text.startswith(":") or "\n:" in text or text.strip().startswith(":"):
                heartbeats.append(text)
                if collect_heartbeats and len(heartbeats) >= 1 and len(events) >= max_events:
                    conn.close()
                    return events, heartbeats
                continue
            data_lines = [ln[5:].lstrip() for ln in text.splitlines() if ln.startswith("data:")]
            id_lines = [ln[3:].lstrip() for ln in text.splitlines() if ln.startswith("id:")]
            if not data_lines:
                continue
            payload = "\n".join(data_lines)
            evt = json.loads(payload)
            if id_lines:
                evt["_sse_id"] = id_lines[0]
            events.append(evt)
            if len(events) >= max_events and not collect_heartbeats:
                conn.close()
                return events, heartbeats
    conn.close()
    return events, heartbeats


def check_sse(httpd_pack, daemon: LiveDaemon) -> None:
    _, host, port = httpd_pack
    daemon.ingest_network_events(
        [
            _sample_evt("e1", "one"),
            _sample_evt("e2", "two"),
            _sample_evt("e3", "three"),
            _sample_evt("e1", "dup"),  # dedupe
        ]
    )
    events, _ = read_sse(host, port, max_events=3, timeout=5)
    ids = [e["id"] for e in events]
    record(
        "SSE streams events in order without duplicates",
        "PASS" if ids == ["e1", "e2", "e3"] else "FAIL",
        f"ids={ids}",
    )
    if ids != ["e1", "e2", "e3"]:
        finding(
            id="SSE-order-dedupe",
            component="MindmapHandler._handle_sse / NetworkEventLog",
            expected="e1,e2,e3 once each in order",
            actual=f"ids={ids}",
            repro="ingest 4 events with dup e1; GET /events",
            evidence="sse_order.json",
            environment=f"@{SHA[:7]}",
            severity="high",
            confidence="high",
        )
    (OUT / "sse_order.json").write_text(json.dumps(events, indent=2), encoding="utf-8")

    # Last-Event-ID reconnect
    daemon.ingest_network_events([_sample_evt("e4", "four")])
    replay, _ = read_sse(host, port, last_event_id="e2", max_events=2, timeout=5)
    rids = [e["id"] for e in replay]
    record(
        "SSE Last-Event-ID replay",
        "PASS" if rids == ["e3", "e4"] else "FAIL",
        f"ids={rids}",
    )
    if rids != ["e3", "e4"]:
        finding(
            id="SSE-last-event-id",
            component="network_events_after / SSE",
            expected="replay e3,e4 after Last-Event-ID=e2",
            actual=f"ids={rids}",
            repro="Last-Event-ID: e2",
            evidence="sse_replay.json",
            environment=f"@{SHA[:7]}",
            severity="high",
            confidence="high",
        )
    (OUT / "sse_replay.json").write_text(json.dumps(replay, indent=2), encoding="utf-8")

    # Heartbeat
    _, hbs = read_sse(host, port, last_event_id="e4", max_events=0, timeout=3.0, collect_heartbeats=True)
    # max_events=0 may exit early — force wait for heartbeat with dedicated reader
    conn = http.client.HTTPConnection(host, port, timeout=5)
    conn.request("GET", "/events", headers={"Host": f"{host}:{port}", "Last-Event-ID": "e4"})
    resp = conn.getresponse()
    assert resp.status == 200
    buf = b""
    saw_hb = False
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        chunk = resp.read(1)
        if not chunk:
            break
        buf += chunk
        if b": heartbeat" in buf:
            saw_hb = True
            break
    conn.close()
    record("SSE heartbeat comment", "PASS" if saw_hb else "FAIL", f"saw={saw_hb}")
    if not saw_hb:
        finding(
            id="SSE-heartbeat",
            component="MindmapHandler._handle_sse",
            expected=": heartbeat within ~heartbeat interval",
            actual="no heartbeat observed in 3s (server heartbeat=0.2s)",
            repro="GET /events after Last-Event-ID past end; wait",
            evidence="playwright/behavioral log",
            environment=f"@{SHA[:7]}",
            severity="medium",
            confidence="high",
        )

    # Concurrent clients
    barriers = []
    errors = []

    def client_worker(n: int) -> None:
        try:
            ev, _ = read_sse(host, port, last_event_id="e0-missing", max_events=2, timeout=6)
            barriers.append((n, [e["id"] for e in ev[:2]]))
        except Exception as exc:  # noqa: BLE001
            errors.append((n, str(exc)))

    threads = [threading.Thread(target=client_worker, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    record(
        "SSE many concurrent clients (6)",
        "PASS" if len(barriers) == 6 and not errors else "FAIL",
        f"ok={len(barriers)} errors={errors[:3]}",
    )

    # Disconnect cleanup / fd+thread leak over many connects
    import resource

    def fd_count() -> int:
        return len(os.listdir(f"/proc/{os.getpid()}/fd"))

    def thread_count() -> int:
        return threading.active_count()

    before_fd = fd_count()
    before_thr = thread_count()
    for i in range(40):
        conn = http.client.HTTPConnection(host, port, timeout=2)
        conn.request("GET", "/events", headers={"Host": f"{host}:{port}"})
        resp = conn.getresponse()
        assert resp.status in (200, 503)
        conn.close()
    time.sleep(0.5)
    after_fd = fd_count()
    after_thr = thread_count()
    fd_delta = after_fd - before_fd
    thr_delta = after_thr - before_thr
    (OUT / "sse_disconnect_leak.json").write_text(
        json.dumps(
            {"before_fd": before_fd, "after_fd": after_fd, "before_thr": before_thr, "after_thr": after_thr},
            indent=2,
        ),
        encoding="utf-8",
    )
    record(
        "SSE disconnect cleanup (40 connect/close; fd/thread bounded)",
        "PASS" if fd_delta < 20 and thr_delta < 20 else "FAIL",
        f"fd_delta={fd_delta} thr_delta={thr_delta}",
    )
    if fd_delta >= 20 or thr_delta >= 20:
        finding(
            id="SSE-leak",
            component="SSE handler / ThreadingHTTPServer",
            expected="no significant fd/thread leak after 40 connect/close",
            actual=f"fd_delta={fd_delta} thr_delta={thr_delta}",
            repro="open/close /events 40 times",
            evidence="sse_disconnect_leak.json",
            environment=f"@{SHA[:7]}",
            severity="high",
            confidence="medium",
        )


# --------------- (a) QA-MM011-2 flock ---------------
def check_flock(tmp: Path, env: dict) -> None:
    lock_path = process_lock_path(env["activity"])

    # Permissions + second instance message via CLI-like acquire
    first = ProcessSingletonLock(lock_path)
    first.acquire()
    mode = stat.S_IMODE(lock_path.stat().st_mode)
    record(
        "QA-MM011-2 lock file mode 0o600",
        "PASS" if mode == PROCESS_LOCK_MODE else "FAIL",
        f"mode={oct(mode)}",
    )

    # Second process clear message via main()-style
    script = f"""
import sys
from pathlib import Path
sys.path.insert(0, {str(ROOT)!r})
from ingest.live import ProcessSingletonLock, SingletonLockError
try:
    ProcessSingletonLock(Path({str(lock_path)!r})).acquire()
    print("UNEXPECTED_ACQUIRE")
    sys.exit(0)
except SingletonLockError as e:
    print(f"error: another mindmap live instance is already running (lock: {{e}})", file=sys.stderr)
    # mirror main() message shape
    print("REFUSED", file=sys.stderr)
    sys.exit(1)
"""
    # Better: invoke main-equivalent message
    script2 = f"""
import sys
from pathlib import Path
sys.path.insert(0, {str(ROOT)!r})
from ingest.live import ProcessSingletonLock, SingletonLockError, process_lock_path
lock_path = Path({str(lock_path)!r})
try:
    ProcessSingletonLock(lock_path).acquire()
except SingletonLockError:
    print(f"error: another mindmap live instance is already running (lock: {{lock_path}})", file=sys.stderr)
    sys.exit(1)
sys.exit(0)
"""
    proc = subprocess.run([sys.executable, "-c", script2], capture_output=True, text=True, cwd=str(ROOT))
    refused = proc.returncode == 1 and "another mindmap live instance is already running" in proc.stderr
    record(
        "QA-MM011-2 second instance refused with clear message",
        "PASS" if refused else "FAIL",
        f"rc={proc.returncode} stderr={proc.stderr.strip()!r}",
    )
    if not refused:
        finding(
            id="QA-MM011-2-refuse",
            component="ProcessSingletonLock / main",
            expected="exit 1 + clear 'another mindmap live instance' message",
            actual=f"rc={proc.returncode} stderr={proc.stderr!r}",
            repro="hold lock; second ProcessSingletonLock.acquire / live main",
            evidence="flock_second.txt",
            environment=f"@{SHA[:7]}",
            severity="high",
            confidence="high",
        )
    (OUT / "flock_second.txt").write_text(
        f"rc={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}\n",
        encoding="utf-8",
    )
    first.release()

    # kill -9 recovery: hold lock in child, kill -9, restart acquires
    hold = subprocess.Popen(
        [
            sys.executable,
            "-c",
            f"""
import sys, time
from pathlib import Path
sys.path.insert(0, {str(ROOT)!r})
from ingest.live import ProcessSingletonLock
lock = ProcessSingletonLock(Path({str(lock_path)!r}))
lock.acquire()
print("held", flush=True)
time.sleep(60)
""",
        ],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert hold.stdout is not None
    line = hold.stdout.readline().decode().strip()
    assert line == "held"
    os.kill(hold.pid, signal.SIGKILL)
    hold.wait(timeout=5)
    time.sleep(0.2)
    recover = ProcessSingletonLock(lock_path)
    try:
        recover.acquire()
        recover_ok = True
        recover.release()
    except SingletonLockError:
        recover_ok = False
    record(
        "QA-MM011-2 kill -9 releases flock; restart works",
        "PASS" if recover_ok else "FAIL",
        f"recover_ok={recover_ok}",
    )
    if not recover_ok:
        finding(
            id="QA-MM011-2-stale",
            component="ProcessSingletonLock",
            expected="after kill -9, new acquire succeeds",
            actual="SingletonLockError on restart",
            repro="child acquire; kill -9; acquire again",
            evidence="flock_kill9.txt",
            environment=f"@{SHA[:7]}",
            severity="high",
            confidence="high",
        )
    (OUT / "flock_kill9.txt").write_text(f"recover_ok={recover_ok}\n", encoding="utf-8")

    # Symlink attack
    symlink_path = tmp / "symlink-lock"
    if symlink_path.exists() or symlink_path.is_symlink():
        symlink_path.unlink()
    target = tmp / "elsewhere"
    target.write_text("x", encoding="utf-8")
    symlink_path.symlink_to(target)
    sym = ProcessSingletonLock(symlink_path)
    sym_ok = False
    try:
        sym.acquire()
    except SingletonLockError as exc:
        sym_ok = "symlink" in str(exc).lower() or exc.errno == errno.ELOOP
    record(
        "QA-MM011-2 refuses symlink lock path",
        "PASS" if sym_ok else "FAIL",
        f"sym_ok={sym_ok}",
    )
    if not sym_ok:
        finding(
            id="QA-MM011-2-symlink",
            component="ProcessSingletonLock.acquire",
            expected="SingletonLockError refusing symlink",
            actual="acquire did not refuse symlink",
            repro="lock path is symlink; acquire()",
            evidence="flock_symlink.txt",
            environment=f"@{SHA[:7]}",
            severity="high",
            confidence="high",
        )

    # Port conflict: two servers same port
    d1 = daemon_from_env(env)
    httpd1 = create_http_server(d1, port=0)
    h, p = httpd1.server_address
    t = threading.Thread(target=httpd1.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    t.start()
    port_conflict_ok = False
    detail = ""
    try:
        create_http_server(daemon_from_env(env), port=int(p))
        detail = "second bind unexpectedly succeeded"
    except OSError as exc:
        port_conflict_ok = True
        detail = f"{type(exc).__name__}: {exc}"
    httpd1.shutdown()
    httpd1.server_close()
    record(
        "Port conflict handled (Address already in use)",
        "PASS" if port_conflict_ok else "FAIL",
        detail,
    )
    (OUT / "port_conflict.txt").write_text(detail + "\n", encoding="utf-8")


# --------------- (b) SEC-MM020d-1 stream cap ---------------
def check_stream_cap(httpd_pack, daemon: LiveDaemon) -> None:
    _, host, port = httpd_pack
    headers = {"Host": f"{host}:{port}"}
    conns: list[http.client.HTTPConnection] = []
    try:
        for i in range(MAX_SSE_CONNECTIONS):
            c = http.client.HTTPConnection(host, port, timeout=5)
            c.request("GET", "/events", headers=headers)
            r = c.getresponse()
            assert r.status == 200, (i, r.status)
            conns.append(c)
        overflow = http.client.HTTPConnection(host, port, timeout=5)
        overflow.request("GET", "/events", headers=headers)
        r9 = overflow.getresponse()
        ra = r9.getheader("Retry-After")
        ok9 = r9.status == 503 and ra == str(SSE_RETRY_AFTER_SEC)
        record(
            "SEC-MM020d-1 9th SSE → 503 + Retry-After",
            "PASS" if ok9 else "FAIL",
            f"status={r9.status} Retry-After={ra}",
        )
        overflow.close()
        if not ok9:
            finding(
                id="SEC-MM020d-1-cap",
                component="SseConnectionLimiter / _handle_sse",
                expected="9th connection 503 with Retry-After",
                actual=f"status={r9.status} Retry-After={ra}",
                repro="open 8 SSE then 9th",
                evidence="stream_cap.json",
                environment=f"@{SHA[:7]}",
                severity="high",
                confidence="high",
            )

        # Graceful close frees slot
        conns[0].close()
        time.sleep(0.3)
        rep = http.client.HTTPConnection(host, port, timeout=5)
        rep.request("GET", "/events", headers=headers)
        st = rep.getresponse().status
        rep.close()
        record(
            "SEC-MM020d-1 slot frees after disconnect",
            "PASS" if st == 200 else "FAIL",
            f"status={st}",
        )

        # Abrupt disconnect: shutdown write side without close protocol
        # Fill to max again
        while len(conns) < MAX_SSE_CONNECTIONS:
            c = http.client.HTTPConnection(host, port, timeout=5)
            c.request("GET", "/events", headers=headers)
            assert c.getresponse().status == 200
            conns.append(c)
        # Abrupt: close socket of last
        abrupt = conns.pop()
        abrupt.sock.shutdown(socket.SHUT_RDWR)
        abrupt.close()
        time.sleep(0.8)  # allow handler finally to run
        rep2 = http.client.HTTPConnection(host, port, timeout=5)
        rep2.request("GET", "/events", headers=headers)
        st2 = rep2.getresponse().status
        rep2.close()
        record(
            "SEC-MM020d-1 slot frees after abrupt disconnect",
            "PASS" if st2 == 200 else "FAIL",
            f"status={st2} active={daemon.sse_limiter.active_count()}",
        )
        if st2 != 200:
            finding(
                id="SEC-MM020d-1-abrupt",
                component="SSE finally/release",
                expected="slot released after abrupt disconnect",
                actual=f"status={st2} active={daemon.sse_limiter.active_count()}",
                repro="SHUT_RDWR on SSE socket; open new /events",
                evidence="stream_cap.json",
                environment=f"@{SHA[:7]}",
                severity="high",
                confidence="high",
            )
    finally:
        for c in conns:
            try:
                c.close()
            except Exception:
                pass

    time.sleep(0.5)
    # 100 connect/disconnect cycles — no slot leak; thread bounded
    thr0 = threading.active_count()
    for i in range(100):
        c = http.client.HTTPConnection(host, port, timeout=3)
        c.request("GET", "/events", headers=headers)
        r = c.getresponse()
        assert r.status == 200, (i, r.status)
        c.close()
    time.sleep(0.5)
    active = daemon.sse_limiter.active_count()
    thr1 = threading.active_count()
    (OUT / "stream_cap.json").write_text(
        json.dumps(
            {
                "active_after_100": active,
                "threads_before": thr0,
                "threads_after": thr1,
                "max": MAX_SSE_CONNECTIONS,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    record(
        "SEC-MM020d-1 no slot leak across 100 cycles; threads bounded",
        "PASS" if active == 0 and (thr1 - thr0) < 30 else "FAIL",
        f"active={active} thr_delta={thr1 - thr0}",
    )
    if active != 0 or (thr1 - thr0) >= 30:
        finding(
            id="SEC-MM020d-1-leak",
            component="SseConnectionLimiter",
            expected="active_count==0 after 100 connect/close; threads bounded",
            actual=f"active={active} thr_delta={thr1 - thr0}",
            repro="100x open/close /events",
            evidence="stream_cap.json",
            environment=f"@{SHA[:7]}",
            severity="high",
            confidence="high",
        )


# --------------- Bind / XSS / outbound ---------------
def check_bind_xss(httpd_pack, daemon: LiveDaemon) -> None:
    _, host, port = httpd_pack
    # Bind evidence
    listen = []
    with open("/proc/net/tcp") as f:
        next(f)
        for line in f:
            parts = line.split()
            ip_hex, p_hex = parts[1].split(":")
            if int(p_hex, 16) == port:
                ip = ".".join(str(b) for b in bytes.fromhex(ip_hex)[::-1])
                listen.append(f"{ip}:{port}")
    (OUT / "bind.txt").write_text("\n".join(listen) + "\n", encoding="utf-8")
    record(
        "Bind 127.0.0.1 only",
        "PASS" if listen and all(x.startswith("127.0.0.1:") for x in listen) else "FAIL",
        str(listen),
    )

    # XSS via SSE payload — ensure JSON encoding does not break out; client would need eval —
    # we check that payload is JSON-encoded and script tags appear as string data only.
    xss = _sample_evt("xss1", '<img src=x onerror="window.__xss=1"><script>window.__xss=1</script>')
    daemon.ingest_network_events([xss])
    events, _ = read_sse(host, port, last_event_id="e4", max_events=1, timeout=4)
    # may need last id before xss — use None and filter
    events2, _ = read_sse(host, port, last_event_id="xss0", max_events=20, timeout=4)
    xss_evts = [e for e in events2 if e.get("id") == "xss1"]
    if not xss_evts:
        # full stream from start
        events2, _ = read_sse(host, port, max_events=20, timeout=4)
        xss_evts = [e for e in events2 if e.get("id") == "xss1"]
    raw_ok = False
    if xss_evts:
        summary = xss_evts[0].get("summary", "")
        # JSON parse already succeeded; ensure it's a string not executed — Python side can't exec HTML
        raw_ok = "<script>" in summary or "onerror" in summary
    record(
        "XSS SSE payload delivered as JSON string (not HTML frame)",
        "PASS" if raw_ok else "FAIL",
        f"found={bool(xss_evts)} summary_has_markup={raw_ok}",
    )
    (OUT / "sse_xss.json").write_text(json.dumps(xss_evts, indent=2), encoding="utf-8")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="qa-mm020d-"))
    env = make_env(tmp)
    daemon = daemon_from_env(env)
    httpd_pack = start_server(daemon, heartbeat=0.2)
    httpd, host, port = httpd_pack
    (OUT / "server.txt").write_text(f"{host}:{port}\n", encoding="utf-8")

    try:
        check_host_origin(httpd_pack)
        check_sse(httpd_pack, daemon)
        check_flock(tmp, env)
        # New server for stream cap (fresh limiter) — reuse same daemon limiter state may be dirty
        # Reset by using active_count — close all first
        time.sleep(0.5)
        # Drain: wait until active 0 or force new server
        httpd.shutdown()
        httpd.server_close()
        daemon2 = daemon_from_env(env)
        httpd_pack2 = start_server(daemon2, heartbeat=0.5)
        check_stream_cap(httpd_pack2, daemon2)
        check_bind_xss(httpd_pack2, daemon2)
        httpd_pack2[0].shutdown()
        httpd_pack2[0].server_close()
    finally:
        try:
            httpd.shutdown()
            httpd.server_close()
        except Exception:
            pass

    report = {"sha": SHA, "checks": checks, "findings": findings}
    (OUT / "behavioral_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("\n=== SUMMARY ===")
    print("PASS", sum(1 for c in checks if c["result"] == "PASS"))
    print("FAIL", sum(1 for c in checks if c["result"] == "FAIL"))
    print("FINDINGS", len(findings))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
