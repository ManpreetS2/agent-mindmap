#!/usr/bin/env python3
"""Delta QA behavioral harness — MM-020d PR #21 @ b67ac50."""
from __future__ import annotations

import errno
import http.client
import json
import os
import resource
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

ROOT = Path("/tmp/qa-mm020d-delta2/checkout")
SHA = "b67ac506dbf8edbbe8e6f796b6c99deed530049a"
OUT = Path(f"/tmp/qa-mm020d-delta2/evidence/logs/{SHA}")
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
    print(f"[{result}] {check}" + (f" — {detail}" if detail else ""), flush=True)


def finding(**kwargs) -> None:
    findings.append(kwargs)
    print(f"[FINDING:{kwargs.get('severity')}] {kwargs.get('id')}: {kwargs.get('actual')}", flush=True)


def make_env(tmp: Path) -> dict:
    ledger = ROOT / "tests" / "fixtures" / "ledger-sample.md"
    activity = tmp / "activity.json"
    static = tmp / "static"
    static.mkdir()
    dist = ROOT / "web" / "dist"
    if dist.is_dir():
        for p in dist.iterdir():
            if p.is_file():
                shutil.copy2(p, static / p.name)
            elif p.is_dir():
                shutil.copytree(p, static / p.name, dirs_exist_ok=True)
    demo = ROOT / "web" / "public" / "activity.json"
    if not demo.is_file():
        # build one
        subprocess.run(
            [sys.executable, "-m", "ingest", "--ledger", str(ledger), "--out", str(demo), "--skip-github"],
            cwd=str(ROOT),
            check=False,
        )
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


def daemon_from_env(env: dict) -> LiveDaemon:
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
        ledger_poll_sec=3600,
        gh_poll_sec=3600,
        events_source="off",
        events_poll_sec=3600,
    )
    d._load_activity_from_disk()
    d.run_poll_cycle()
    return d


def start_server(daemon: LiveDaemon, *, heartbeat: float = 15.0):
    httpd = create_http_server(daemon, host=BIND_HOST, port=0, sse_heartbeat_sec=heartbeat)
    host, port = httpd.server_address
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    return httpd, host, int(port)


def open_sse(host: str, port: int) -> tuple[http.client.HTTPConnection, http.client.HTTPResponse]:
    conn = http.client.HTTPConnection(host, port, timeout=5)
    conn.request("GET", "/events", headers={"Host": f"{host}:{port}"})
    resp = conn.getresponse()
    return conn, resp


def http_status(host: str, port: int, path: str, headers: dict) -> int:
    conn = http.client.HTTPConnection(host, port, timeout=3)
    try:
        conn.request("GET", path, headers=headers)
        return conn.getresponse().status
    finally:
        conn.close()


def raw_status_no_host(host: str, port: int, path: str, origin: str | None = None) -> int:
    lines = [f"GET {path} HTTP/1.1"]
    if origin is not None:
        lines.append(f"Origin: {origin}")
    lines += ["Connection: close", "", ""]
    payload = "\r\n".join(lines).encode()
    with socket.create_connection((host, port), timeout=3) as s:
        s.sendall(payload)
        data = b""
        s.settimeout(3)
        try:
            while b"\r\n" not in data:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
        except socket.timeout:
            pass
    parts = data.split(b"\r\n", 1)[0].decode("latin1", errors="replace").split()
    return int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else -1


def sample_evt(eid: str) -> dict:
    return {
        "id": eid,
        "ts": "2026-10-20T12:00:00-07:00",
        "sender": "director",
        "group": "build",
        "type": "message",
        "summary": "hi",
        "provenance": "agent-reported",
    }


# ---------- (1) QA-MM020d-1 prompt release ----------
def check_prompt_release(env: dict) -> None:
    daemon = daemon_from_env(env)
    # Use production-like 15s heartbeat to prove release << heartbeat
    httpd, host, port = start_server(daemon, heartbeat=15.0)
    H = {"Host": f"{host}:{port}"}
    results = {}

    try:
        # Fill 8, keep responses alive
        conns, resps = [], []
        for _ in range(MAX_SSE_CONNECTIONS):
            c, r = open_sse(host, port)
            assert r.status == 200
            conns.append(c)
            resps.append(r)
        assert daemon.sse_limiter.active_count() == 8

        # 9th = 503
        c9 = http.client.HTTPConnection(host, port, timeout=3)
        c9.request("GET", "/events", headers=H)
        r9 = c9.getresponse()
        results["ninth"] = {"status": r9.status, "retry": r9.getheader("Retry-After")}
        c9.close()
        record(
            "Cap: 9th → 503 + Retry-After",
            "PASS" if r9.status == 503 and r9.getheader("Retry-After") == str(SSE_RETRY_AFTER_SEC) else "FAIL",
            str(results["ninth"]),
        )

        # Graceful close → accept within ~1s (<< 15s heartbeat)
        t0 = time.monotonic()
        resps[0].close()
        conns[0].close()
        ok_wait = daemon.sse_limiter.wait_until_active_at_most(MAX_SSE_CONNECTIONS - 1, timeout=1.0)
        elapsed = time.monotonic() - t0
        rep = http.client.HTTPConnection(host, port, timeout=3)
        rep.request("GET", "/events", headers=H)
        st = rep.getresponse().status
        rep.close()
        results["graceful"] = {"wait_ok": ok_wait, "elapsed_s": round(elapsed, 3), "status": st, "active": daemon.sse_limiter.active_count()}
        record(
            "QA-MM020d-1 graceful close → new stream ≤1s (heartbeat=15s)",
            "PASS" if ok_wait and elapsed <= 1.0 and st == 200 else "FAIL",
            str(results["graceful"]),
        )
        if not (ok_wait and elapsed <= 1.0 and st == 200):
            finding(
                id="QA-MM020d-1-graceful",
                component="SSE _peer_closed / limiter",
                expected="slot free + new stream accepted within ~1s after graceful close",
                actual=str(results["graceful"]),
                repro="8 streams; close one; wait_until_active_at_most(7,1s); open",
                evidence="prompt_release.json",
                environment=f"@{SHA[:7]} heartbeat=15",
                severity="high",
                confidence="high",
            )

        # Abrupt RST-style close
        # Refill to 8
        while daemon.sse_limiter.active_count() < MAX_SSE_CONNECTIONS:
            c, r = open_sse(host, port)
            if r.status != 200:
                c.close()
                break
            conns.append(c)
            resps.append(r)

        victim_c = conns.pop()
        victim_r = resps.pop()
        t0 = time.monotonic()
        try:
            if victim_c.sock:
                victim_c.sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct_linger(1, 0))
                victim_c.sock.close()
        except Exception:
            try:
                victim_r.close()
                victim_c.close()
            except Exception:
                pass
        ok_wait2 = daemon.sse_limiter.wait_until_active_at_most(MAX_SSE_CONNECTIONS - 1, timeout=1.0)
        elapsed2 = time.monotonic() - t0
        rep2 = http.client.HTTPConnection(host, port, timeout=3)
        rep2.request("GET", "/events", headers=H)
        st2 = rep2.getresponse().status
        rep2.close()
        results["abrupt"] = {"wait_ok": ok_wait2, "elapsed_s": round(elapsed2, 3), "status": st2, "active": daemon.sse_limiter.active_count()}
        record(
            "QA-MM020d-1 abrupt close → new stream ≤1s",
            "PASS" if ok_wait2 and elapsed2 <= 1.0 and st2 == 200 else "FAIL",
            str(results["abrupt"]),
        )
        if not (ok_wait2 and elapsed2 <= 1.0 and st2 == 200):
            finding(
                id="QA-MM020d-1-abrupt",
                component="SSE _peer_closed",
                expected="slot free within ~1s after abrupt/RST close",
                actual=str(results["abrupt"]),
                repro="SO_LINGER RST close on SSE client",
                evidence="prompt_release.json",
                environment=f"@{SHA[:7]}",
                severity="high",
                confidence="high",
            )

        # Drain
        for r in resps:
            try:
                r.close()
            except Exception:
                pass
        for c in conns:
            try:
                c.close()
            except Exception:
                pass
        daemon.sse_limiter.wait_until_active_at_most(0, timeout=2.0)

        # 100 rapid cycles — no 503 beyond true cap; no leak; threads bounded
        thr0 = threading.active_count()
        unexpected_503 = 0
        for i in range(100):
            c, r = open_sse(host, port)
            if r.status != 200:
                unexpected_503 += 1
                c.close()
                # brief wait then retry once to distinguish flake from leak
                time.sleep(0.05)
                continue
            r.close()
            c.close()
            # ensure slot released before next (should be fast now)
            if not daemon.sse_limiter.wait_until_active_at_most(0, timeout=1.0):
                unexpected_503 += 1
        thr1 = threading.active_count()
        active_end = daemon.sse_limiter.active_count()
        results["cycles100"] = {
            "unexpected_503_or_stuck": unexpected_503,
            "active_end": active_end,
            "thr0": thr0,
            "thr1": thr1,
        }
        record(
            "QA-MM020d-1 100 rapid cycles: no spurious 503, no leak, threads bounded",
            "PASS" if unexpected_503 == 0 and active_end == 0 and (thr1 - thr0) < 20 else "FAIL",
            str(results["cycles100"]),
        )
        if not (unexpected_503 == 0 and active_end == 0):
            finding(
                id="QA-MM020d-1-cycles",
                component="SseConnectionLimiter",
                expected="100 open/close with 0 unexpected 503 and active_end=0",
                actual=str(results["cycles100"]),
                repro="100x open SSE then close",
                evidence="prompt_release.json",
                environment=f"@{SHA[:7]}",
                severity="high",
                confidence="high",
            )
    finally:
        (OUT / "prompt_release.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        httpd.shutdown()
        httpd.server_close()


def struct_linger(onoff: int, linger: int) -> bytes:
    import struct

    return struct.pack("ii", onoff, linger)


# ---------- (2) Origin null + Host matrix ----------
def check_origin_host(env: dict) -> None:
    daemon = daemon_from_env(env)
    httpd, host, port = start_server(daemon, heartbeat=1.0)
    allowed = f"{host}:{port}"
    endpoints = ["/healthz", "/activity.json", "/index.html", "/events"]
    matrix = {}
    try:
        for path in endpoints:
            # allowed missing Origin
            st = http_status(host, port, path, {"Host": allowed})
            matrix[f"missing_origin:{path}"] = st
            # local origin
            st2 = http_status(host, port, path, {"Host": allowed, "Origin": f"http://{host}:{port}"})
            matrix[f"local_origin:{path}"] = st2
            # null origin
            if path == "/events":
                conn = http.client.HTTPConnection(host, port, timeout=2)
                conn.request("GET", path, headers={"Host": allowed, "Origin": "null"})
                st3 = conn.getresponse().status
                conn.close()
            else:
                st3 = http_status(host, port, path, {"Host": allowed, "Origin": "null"})
            matrix[f"null_origin:{path}"] = st3
            # evil host
            st4 = http_status(host, port, path, {"Host": "evil.com", "Origin": f"http://{host}:{port}"})
            matrix[f"evil_host:{path}"] = st4
            # mismatched origin
            st5 = http_status(host, port, path, {"Host": allowed, "Origin": "https://evil.com"})
            matrix[f"bad_origin:{path}"] = st5
            # missing host
            matrix[f"missing_host:{path}"] = raw_status_no_host(host, port, path)

        null_ok = all(matrix[f"null_origin:{p}"] == 403 for p in endpoints)
        missing_ok = all(matrix[f"missing_origin:{p}"] == 200 for p in endpoints)
        local_ok = all(matrix[f"local_origin:{p}"] == 200 for p in endpoints)
        evil_ok = all(matrix[f"evil_host:{p}"] == 403 for p in endpoints)
        bad_ok = all(matrix[f"bad_origin:{p}"] == 403 for p in endpoints)
        miss_host_ok = all(matrix[f"missing_host:{p}"] == 403 for p in endpoints)

        record("QA-MM020d-2 Origin:null → 403 all routes", "PASS" if null_ok else "FAIL", str({k: v for k, v in matrix.items() if k.startswith("null_")}))
        record("Missing Origin → 200", "PASS" if missing_ok else "FAIL")
        record("Local Origin → 200", "PASS" if local_ok else "FAIL")
        record("Host/Origin evil/bad/missing-host → 403", "PASS" if evil_ok and bad_ok and miss_host_ok else "FAIL")

        if not null_ok:
            finding(
                id="QA-MM020d-2",
                component="origin_header_allowed",
                expected="Origin: null → 403 on every route incl /events",
                actual=str({k: v for k, v in matrix.items() if k.startswith("null_")}),
                repro="Origin: null on /healthz,/activity.json,static,/events",
                evidence="origin_host_matrix.json",
                environment=f"@{SHA[:7]}",
                severity="high",
                confidence="high",
            )
    finally:
        (OUT / "origin_host_matrix.json").write_text(json.dumps(matrix, indent=2), encoding="utf-8")
        httpd.shutdown()
        httpd.server_close()


# ---------- SSE order / Last-Event-ID ----------
def check_sse_basics(env: dict) -> None:
    daemon = daemon_from_env(env)
    httpd, host, port = start_server(daemon, heartbeat=0.3)
    try:
        daemon.ingest_network_events([sample_evt("a1"), sample_evt("a2"), sample_evt("a1")])
        # read events
        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/events", headers={"Host": f"{host}:{port}"})
        resp = conn.getresponse()
        assert resp.status == 200
        buf = b""
        ids = []
        deadline = time.monotonic() + 3
        while len(ids) < 2 and time.monotonic() < deadline:
            buf += resp.read(1)
            while b"\n\n" in buf:
                block, buf = buf.split(b"\n\n", 1)
                text = block.decode()
                if text.startswith(":"):
                    continue
                data = "\n".join(ln[5:].lstrip() for ln in text.splitlines() if ln.startswith("data:"))
                if data:
                    ids.append(json.loads(data)["id"])
        conn.close()
        record("SSE order+dedupe", "PASS" if ids == ["a1", "a2"] else "FAIL", f"ids={ids}")

        daemon.ingest_network_events([sample_evt("a3")])
        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/events", headers={"Host": f"{host}:{port}", "Last-Event-ID": "a1"})
        resp = conn.getresponse()
        buf = b""
        ids2 = []
        deadline = time.monotonic() + 3
        while len(ids2) < 2 and time.monotonic() < deadline:
            chunk = resp.read(1)
            if not chunk:
                break
            buf += chunk
            while b"\n\n" in buf:
                block, buf = buf.split(b"\n\n", 1)
                text = block.decode()
                if text.startswith(":"):
                    continue
                data = "\n".join(ln[5:].lstrip() for ln in text.splitlines() if ln.startswith("data:"))
                if data:
                    ids2.append(json.loads(data)["id"])
        conn.close()
        record("SSE Last-Event-ID", "PASS" if ids2 == ["a2", "a3"] else "FAIL", f"ids={ids2}")
    finally:
        httpd.shutdown()
        httpd.server_close()


# ---------- flock smoke ----------
def check_flock(tmp: Path, env: dict) -> None:
    lock_path = process_lock_path(env["activity"])
    first = ProcessSingletonLock(lock_path)
    first.acquire()
    mode = stat.S_IMODE(lock_path.stat().st_mode)
    record("flock mode 0o600", "PASS" if mode == PROCESS_LOCK_MODE else "FAIL", oct(mode))
    second = ProcessSingletonLock(lock_path)
    refused = False
    try:
        second.acquire()
    except SingletonLockError:
        refused = True
    record("flock second refused", "PASS" if refused else "FAIL")
    first.release()

    # kill -9
    hold = subprocess.Popen(
        [sys.executable, "-c", f"""
import sys,time
from pathlib import Path
sys.path.insert(0,{str(ROOT)!r})
from ingest.live import ProcessSingletonLock
ProcessSingletonLock(Path({str(lock_path)!r})).acquire()
print('held', flush=True)
time.sleep(60)
"""],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
    )
    assert hold.stdout and hold.stdout.readline().decode().strip() == "held"
    os.kill(hold.pid, signal.SIGKILL)
    hold.wait(timeout=5)
    time.sleep(0.1)
    rec = ProcessSingletonLock(lock_path)
    try:
        rec.acquire()
        ok = True
        rec.release()
    except SingletonLockError:
        ok = False
    record("flock after kill -9", "PASS" if ok else "FAIL")

    # symlink
    sym = tmp / "sym.lock"
    if sym.exists() or sym.is_symlink():
        sym.unlink()
    sym.symlink_to(tmp / "x")
    (tmp / "x").write_text("z")
    s = ProcessSingletonLock(sym)
    sym_ok = False
    try:
        s.acquire()
    except SingletonLockError:
        sym_ok = True
    record("flock refuses symlink", "PASS" if sym_ok else "FAIL")


# ---------- SEC-MM020d-2 CPU spin ----------
def check_cpu_spin(env: dict) -> None:
    """Open SSE, send garbage without closing; measure server thread CPU ~10s."""
    daemon = daemon_from_env(env)
    httpd, host, port = start_server(daemon, heartbeat=15.0)
    result = {}
    try:
        # Identify worker by opening SSE via raw socket so we can send extra bytes
        s = socket.create_connection((host, port), timeout=5)
        req = (
            f"GET /events HTTP/1.1\r\nHost: {host}:{port}\r\n"
            f"Accept: text/event-stream\r\nConnection: keep-alive\r\n\r\n"
        ).encode()
        s.sendall(req)
        # Read response headers
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
        assert b"200" in buf.split(b"\r\n", 1)[0], buf[:80]
        assert daemon.sse_limiter.active_count() >= 1

        # Find the busy SSE handler thread CPU via /proc
        # Sample process CPU time before/after sending garbage
        proc = os.getpid()  # same process as httpd threads

        def cpu_seconds() -> float:
            # sum utime+stime for all threads of this process
            total = 0.0
            task = Path(f"/proc/{proc}/task")
            for tid in task.iterdir():
                try:
                    stat = (tid / "stat").read_text().split()
                    # fields 14,15 are utime stime in clock ticks
                    total += (int(stat[13]) + int(stat[14])) / os.sysconf("SC_CLK_TCK")
                except Exception:
                    pass
            return total

        before = cpu_seconds()
        t0 = time.monotonic()
        # Send garbage and KEEP SOCKET OPEN
        s.sendall(b"GARBAGE_BYTES_NOT_HTTP\r\n" * 20)
        # Wait ~10s while server may spin
        samples = []
        for i in range(20):
            time.sleep(0.5)
            samples.append(cpu_seconds())
        after = cpu_seconds()
        wall = time.monotonic() - t0
        cpu_delta = after - before
        # Also measure incremental over last 5s of the window
        mid = samples[len(samples) // 2]
        cpu_last_half = samples[-1] - mid
        wall_half = wall / 2
        util = cpu_last_half / wall_half if wall_half > 0 else 0

        result = {
            "wall_s": round(wall, 2),
            "cpu_delta_s": round(cpu_delta, 3),
            "cpu_last_half_s": round(cpu_last_half, 3),
            "approx_util_last_half": round(util, 3),
            "active_during": daemon.sse_limiter.active_count(),
        }

        # Stream/slot still held (client didn't close)
        slot_held = daemon.sse_limiter.active_count() >= 1

        # Close and ensure slot frees promptly
        s.close()
        freed = daemon.sse_limiter.wait_until_active_at_most(0, timeout=1.0)
        result["slot_held_during_garbage"] = slot_held
        result["freed_after_close"] = freed

        # Severity: if util ~1.0 (100% of one core) for sustained period → high
        spinning = util >= 0.5  # half a core or more sustained in last half
        record(
            "SEC-MM020d-2 no CPU spin on garbage-after-request",
            "FAIL" if spinning else "PASS",
            str(result),
        )
        if spinning:
            finding(
                id="SEC-MM020d-2",
                component="MindmapHandler._handle_sse select/MSG_PEEK loop",
                expected="Readable non-EOF client data must not busy-spin; sleep/backoff or drain/close",
                actual=(
                    f"After sending garbage with socket left open, process CPU util≈{util:.0%} "
                    f"over ~{wall_half:.1f}s (cpu_last_half={cpu_last_half:.2f}s). "
                    f"Loop: select readable → _peer_closed False (peek≠EOF) → continue with no delay."
                ),
                repro=(
                    "GET /events; read headers; send non-empty bytes; keep TCP open; "
                    "sample /proc/<pid>/task/*/stat over 10s"
                ),
                evidence="cpu_spin.json",
                environment=f"@{SHA[:7]} heartbeat=15",
                severity="high",
                confidence="high",
            )
        record(
            "SEC-MM020d-2 slot still held during garbage, frees on close",
            "PASS" if slot_held and freed else "FAIL",
            str(result),
        )
    finally:
        (OUT / "cpu_spin.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        httpd.shutdown()
        httpd.server_close()


# ---------- bind / XSS smoke ----------
def check_bind_xss(env: dict) -> None:
    daemon = daemon_from_env(env)
    httpd, host, port = start_server(daemon, heartbeat=1.0)
    try:
        listens = []
        with open("/proc/net/tcp") as f:
            next(f)
            for line in f:
                parts = line.split()
                ip_hex, p_hex = parts[1].split(":")
                if int(p_hex, 16) == port:
                    ip = ".".join(str(b) for b in bytes.fromhex(ip_hex)[::-1])
                    listens.append(f"{ip}:{port}")
        record("bind 127.0.0.1 only", "PASS" if listens and all(x.startswith("127.0.0.1:") for x in listens) else "FAIL", str(listens))
        (OUT / "bind.txt").write_text("\n".join(listens) + "\n", encoding="utf-8")

        xss = sample_evt("xss1")
        xss["summary"] = '<img src=x onerror="window.__xss=1">'
        daemon.ingest_network_events([xss])
        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/events", headers={"Host": f"{host}:{port}"})
        resp = conn.getresponse()
        body = b""
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and b"xss1" not in body:
            body += resp.read(256)
        conn.close()
        record(
            "XSS SSE payload is JSON text",
            "PASS" if b"onerror" in body and b"data:" in body else "FAIL",
            body[:200].decode("utf-8", errors="replace"),
        )
    finally:
        httpd.shutdown()
        httpd.server_close()


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="qa-mm020d-b67-"))
    env = make_env(tmp)

    check_prompt_release(env)
    check_origin_host(env)
    check_sse_basics(env)
    check_flock(tmp, env)
    check_bind_xss(env)
    check_cpu_spin(env)

    report = {"sha": SHA, "checks": checks, "findings": findings}
    (OUT / "behavioral_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("\n=== BEHAVIORAL SUMMARY ===", flush=True)
    print("PASS", sum(1 for c in checks if c["result"] == "PASS"), flush=True)
    print("FAIL", sum(1 for c in checks if c["result"] == "FAIL"), flush=True)
    print("FINDINGS", len(findings), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
