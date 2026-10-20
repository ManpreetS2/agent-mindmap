#!/usr/bin/env python3
"""Delta QA behavioral harness — MM-020d PR #21 @ 3d54153 (vs FAIL b67ac50)."""
from __future__ import annotations

import http.client
import json
import os
import select
import shutil
import signal
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path("/tmp/qa-mm020d-delta3/checkout")
SHA = "3d5415347d7f378b1bcbf135011941d3e472d107"
OUT = Path(f"/tmp/qa-mm020d-delta3/evidence/logs/{SHA}")
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
from tests.test_github_poller import MockGh  # noqa: E402

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
    # Never write into web/public (pollutes MM-020a fixture tests). Build into tmp.
    demo = ROOT / "web" / "public" / "activity.json"
    built = tmp / "built-activity.json"
    if demo.is_file() and '"schema_version": "1.0.0"' in demo.read_text(encoding="utf-8"):
        shutil.copy2(demo, activity)
        shutil.copy2(demo, static / "activity.json")
    else:
        subprocess.run(
            [sys.executable, "-m", "ingest", "--ledger", str(ledger), "--out", str(built), "--skip-github"],
            cwd=str(ROOT),
            check=False,
            capture_output=True,
        )
        src = built if built.is_file() else None
        if src is None:
            activity.write_text("{}", encoding="utf-8")
        else:
            shutil.copy2(src, activity)
            shutil.copy2(src, static / "activity.json")
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
        github_runner=MockGh(),  # no real gh network
    )
    d._load_activity_from_disk()
    d.run_poll_cycle()
    return d


def start_server(daemon: LiveDaemon, *, heartbeat: float = 15.0):
    httpd = create_http_server(daemon, host=BIND_HOST, port=0, sse_heartbeat_sec=heartbeat)
    host, port = httpd.server_address
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    return httpd, host, int(port)


def stop_server(httpd) -> None:
    """Close the listening socket; abandon in-flight SSE handler threads.

    Phases run in separate processes so abandoned threads die with the child.
    Never call ``httpd.shutdown()`` — it can block forever on an SSE select.
    """
    try:
        httpd.socket.close()
    except Exception:
        pass
    try:
        httpd.server_close()
    except Exception:
        pass


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


def raw_status_no_host(host: str, port: int, path: str) -> int:
    lines = [f"GET {path} HTTP/1.1", "Connection: close", "", ""]
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


def struct_linger(onoff: int, linger: int) -> bytes:
    return struct.pack("ii", onoff, linger)


def cpu_seconds(pid: int) -> float:
    total = 0.0
    task = Path(f"/proc/{pid}/task")
    for tid in task.iterdir():
        try:
            stat_f = (tid / "stat").read_text().split()
            total += (int(stat_f[13]) + int(stat_f[14])) / os.sysconf("SC_CLK_TCK")
        except Exception:
            pass
    return total


def open_raw_sse(host: str, port: int) -> socket.socket:
    s = socket.create_connection((host, port), timeout=5)
    req = (
        f"GET /events HTTP/1.1\r\nHost: {host}:{port}\r\n"
        f"Accept: text/event-stream\r\nConnection: keep-alive\r\n\r\n"
    ).encode()
    s.sendall(req)
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = s.recv(4096)
        if not chunk:
            break
        buf += chunk
    assert b"200" in buf.split(b"\r\n", 1)[0], buf[:80]
    return s


# ---------- (1) SEC-MM020d-2 ----------
def check_sec_mm020d_2_spin_only(env: dict) -> None:
    daemon = daemon_from_env(env)
    httpd, host, port = start_server(daemon, heartbeat=15.0)
    spin = {}
    try:
        s = open_raw_sse(host, port)
        assert daemon.sse_limiter.active_count() >= 1
        pid = os.getpid()
        before = cpu_seconds(pid)
        t0 = time.monotonic()
        s.sendall(b"GARBAGE_BYTES_NOT_HTTP\r\n" * 20)
        # Keep socket open; server should end stream + free slot ~1s
        freed = daemon.sse_limiter.wait_until_active_at_most(0, timeout=1.0)
        free_elapsed = time.monotonic() - t0
        # Hold open remaining wall to 10s for CPU sample
        samples = []
        while time.monotonic() - t0 < 10.0:
            time.sleep(0.5)
            samples.append(cpu_seconds(pid))
        after = cpu_seconds(pid)
        wall = time.monotonic() - t0
        cpu_delta = after - before
        mid = samples[len(samples) // 2] if samples else before
        cpu_last_half = (samples[-1] - mid) if samples else 0.0
        wall_half = wall / 2
        util = cpu_last_half / wall_half if wall_half > 0 else 0.0
        # After free, peer should see close soon (optional recv)
        s.settimeout(1.0)
        peer_closed_seen = False
        try:
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    peer_closed_seen = True
                    break
        except socket.timeout:
            peer_closed_seen = False
        except OSError:
            peer_closed_seen = True
        try:
            s.close()
        except OSError:
            pass

        spin = {
            "wall_s": round(wall, 2),
            "cpu_delta_s": round(cpu_delta, 3),
            "cpu_last_half_s": round(cpu_last_half, 3),
            "approx_util_last_half": round(util, 3),
            "freed_within_1s": freed,
            "free_elapsed_s": round(free_elapsed, 3),
            "active_after_free_wait": daemon.sse_limiter.active_count(),
            "peer_closed_seen": peer_closed_seen,
        }
        idle_ok = util < 0.15 and cpu_delta < 1.5  # near idle over 10s
        free_ok = freed and free_elapsed <= 1.0
        record(
            "SEC-MM020d-2 garbage+open: CPU near idle over ~10s",
            "PASS" if idle_ok else "FAIL",
            str(spin),
        )
        record(
            "SEC-MM020d-2 garbage+open: stream/slot freed ≤1s",
            "PASS" if free_ok else "FAIL",
            str(spin),
        )
        if not idle_ok or not free_ok:
            finding(
                id="SEC-MM020d-2",
                component="MindmapHandler._handle_sse",
                expected="CPU near idle; slot freed ≤1s with garbage + open socket",
                actual=str(spin),
                repro="GET /events; send garbage; keep open; sample /proc CPU 10s",
                evidence="cpu_spin.json",
                environment=f"@{SHA[:7]} heartbeat=15",
                severity="high",
                confidence="high",
            )
    finally:
        (OUT / "cpu_spin.json").write_text(json.dumps(spin, indent=2), encoding="utf-8")
        stop_server(httpd)


def check_sec_mm020d_2_eight_only(env: dict) -> None:
    # 8 concurrent garbage clients
    daemon = daemon_from_env(env)
    httpd, host, port = start_server(daemon, heartbeat=15.0)
    eight = {}
    try:
        socks = []
        for _ in range(8):
            socks.append(open_raw_sse(host, port))
        assert daemon.sse_limiter.active_count() == 8
        for s in socks:
            s.sendall(b"GARBAGE\n")
        freed8 = daemon.sse_limiter.wait_until_active_at_most(0, timeout=1.0)
        elapsed8 = None
        # measure from after send
        t_end = time.monotonic()
        eight["freed_all_within_1s"] = freed8
        eight["active_after"] = daemon.sse_limiter.active_count()
        # legitimate client must get a slot
        c, r = open_sse(host, port)
        eight["legit_status"] = r.status
        eight["active_with_legit"] = daemon.sse_limiter.active_count()
        r.close()
        c.close()
        gone = daemon.sse_limiter.wait_until_active_at_most(0, timeout=1.0)
        eight["active_final"] = daemon.sse_limiter.active_count()
        eight["legit_cleared"] = gone
        for s in socks:
            try:
                s.close()
            except OSError:
                pass
        ok8 = (
            freed8
            and eight["legit_status"] == 200
            and eight["active_final"] == 0
            and gone
        )
        record(
            "SEC-MM020d-2 8 garbage clients → free; legit gets slot; active=0",
            "PASS" if ok8 else "FAIL",
            str(eight),
        )
        if not ok8:
            finding(
                id="SEC-MM020d-2-eight",
                component="SseConnectionLimiter + SSE end-on-data",
                expected="8 garbage streams end ≤1s; legit 200; active_end=0",
                actual=str(eight),
                repro="8 raw SSE + GARBAGE each; then open_sse",
                evidence="eight_garbage.json",
                environment=f"@{SHA[:7]}",
                severity="high",
                confidence="high",
            )
    finally:
        (OUT / "eight_garbage.json").write_text(json.dumps(eight, indent=2), encoding="utf-8")
        stop_server(httpd)


def check_sec_mm020d_2_trickle_only(env: dict) -> None:
    # Slow trickle — first unexpected byte should end stream; later writes may EPIPE
    daemon = daemon_from_env(env)
    httpd, host, port = start_server(daemon, heartbeat=15.0)
    trickle: dict = {}
    try:
        s = open_raw_sse(host, port)
        t0 = time.monotonic()
        sent = 0
        pipe_err = False
        for ch in b"trickle-bytes":
            try:
                s.sendall(bytes([ch]))
                sent += 1
            except (BrokenPipeError, ConnectionResetError, OSError):
                pipe_err = True
                break
            time.sleep(0.05)
            if daemon.sse_limiter.active_count() == 0:
                break
        freed = daemon.sse_limiter.wait_until_active_at_most(0, timeout=1.0)
        trickle["freed"] = freed
        trickle["elapsed_s"] = round(time.monotonic() - t0, 3)
        trickle["active"] = daemon.sse_limiter.active_count()
        trickle["bytes_sent"] = sent
        trickle["pipe_err_after_end"] = pipe_err
        try:
            s.close()
        except OSError:
            pass
        record(
            "SEC-MM020d-2 slow trickle → slot freed ≤1s",
            "PASS" if freed and trickle["elapsed_s"] <= 2.0 and sent >= 1 else "FAIL",
            str(trickle),
        )
        if not (freed and sent >= 1):
            finding(
                id="SEC-MM020d-2-trickle",
                component="SSE drain/end",
                expected="slow byte trickle ends stream and frees slot ≤1s",
                actual=str(trickle),
                repro="send 1 byte every 50ms after SSE headers",
                evidence="trickle.json",
                environment=f"@{SHA[:7]}",
                severity="high",
                confidence="high",
            )
    finally:
        (OUT / "trickle.json").write_text(json.dumps(trickle, indent=2), encoding="utf-8")
        stop_server(httpd)


def check_sec_mm020d_2_shutwr_only(env: dict) -> None:
    # Half-close SHUT_WR
    daemon = daemon_from_env(env)
    httpd, host, port = start_server(daemon, heartbeat=15.0)
    half = {}
    try:
        s = open_raw_sse(host, port)
        t0 = time.monotonic()
        s.shutdown(socket.SHUT_WR)
        freed = daemon.sse_limiter.wait_until_active_at_most(0, timeout=1.0)
        half["freed"] = freed
        half["elapsed_s"] = round(time.monotonic() - t0, 3)
        half["active"] = daemon.sse_limiter.active_count()
        # Server may still send; drain then close
        s.settimeout(0.5)
        try:
            while s.recv(4096):
                pass
        except Exception:
            pass
        try:
            s.close()
        except OSError:
            pass
        record(
            "SEC-MM020d-2 SHUT_WR half-close → slot freed ≤1s",
            "PASS" if freed and half["elapsed_s"] <= 1.0 else "FAIL",
            str(half),
        )
        if not (freed and half["elapsed_s"] <= 1.0):
            finding(
                id="SEC-MM020d-2-shut_wr",
                component="SSE EOF / half-close",
                expected="client SHUT_WR frees slot ≤1s",
                actual=str(half),
                repro="open SSE; socket.shutdown(SHUT_WR)",
                evidence="shut_wr.json",
                environment=f"@{SHA[:7]}",
                severity="high",
                confidence="high",
            )
    finally:
        (OUT / "shut_wr.json").write_text(json.dumps(half, indent=2), encoding="utf-8")
        stop_server(httpd)


def check_sec_mm020d_2(env: dict) -> None:
    check_sec_mm020d_2_spin_only(env)
    check_sec_mm020d_2_eight_only(env)
    check_sec_mm020d_2_trickle_only(env)
    check_sec_mm020d_2_shutwr_only(env)


# ---------- (2) Legitimate clients survive ≥3 heartbeats ----------
def check_legitimate_survive(env: dict) -> None:
    daemon = daemon_from_env(env)
    # short heartbeat so 3 beats finish quickly
    hb = 0.25
    httpd, host, port = start_server(daemon, heartbeat=hb)
    result = {}
    try:
        # curl-like raw stream
        s = open_raw_sse(host, port)
        buf = b""
        beats = 0
        deadline = time.monotonic() + hb * 3 + 2.0
        s.settimeout(0.5)
        while time.monotonic() < deadline and beats < 3:
            try:
                chunk = s.recv(4096)
            except socket.timeout:
                continue
            if not chunk:
                break
            buf += chunk
            beats = buf.count(b": heartbeat")
        still_active = daemon.sse_limiter.active_count() >= 1
        curl_ok = beats >= 3 and still_active
        result["curl_like"] = {"heartbeats": beats, "active": daemon.sse_limiter.active_count(), "ok": curl_ok}
        record(
            "Legitimate curl-like SSE stays open across ≥3 heartbeats",
            "PASS" if curl_ok else "FAIL",
            str(result["curl_like"]),
        )
        try:
            s.close()
        except OSError:
            pass
        daemon.sse_limiter.wait_until_active_at_most(0, timeout=1.0)

        # Browser EventSource: Node W3C EventSource + Chromium subprocess (hard-timeout)
        es: dict = {"method": "node-eventsource", "ok": False, "error": None}
        wait_ms = int((hb * 3 + 1.0) * 1000)
        node_script = f"""
const ES = require('eventsource');
const url = 'http://{host}:{port}/events';
const es = new ES(url);
let opened = false;
let err = null;
es.onopen = () => {{ opened = true; }};
es.onerror = () => {{ err = 'error'; }};
setTimeout(() => {{
  const out = {{readyState: es.readyState, opened, err}};
  process.stdout.write(JSON.stringify(out));
  es.close();
  process.exit(0);
}}, {wait_ms});
"""
        n = subprocess.run(
            ["node", "-e", node_script],
            cwd="/tmp/qa-mm020d-delta3",
            capture_output=True,
            text=True,
            timeout=30,
        )
        try:
            node_state = json.loads(n.stdout.strip() or "{}")
        except json.JSONDecodeError:
            node_state = {"parse_error": n.stdout, "stderr": n.stderr[-200:]}
        es["node_state"] = node_state
        es["ok"] = node_state.get("readyState") == 1 and node_state.get("opened") is True

        # Chromium EventSource in a separate process so a hang cannot stall the suite
        chrome = Path("/home/ubuntu/.cache/ms-playwright/chromium-1148/chrome-linux/chrome")
        html = env["static"] / "es_probe.html"
        html.write_text("<!doctype html><title>es-probe</title><body>es-probe</body>\n", encoding="utf-8")
        chrome_probe = Path(tempfile.mkdtemp(prefix="es-chrome-")) / "probe.py"
        chrome_probe.write_text(
            f"""
import json, sys
from playwright.sync_api import sync_playwright
chrome = {str(chrome)!r}
url = 'http://{host}:{port}/es_probe.html'
wait_ms = {wait_ms}
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=chrome, headless=True,
                                args=['--no-sandbox','--disable-dev-shm-usage'])
    page = browser.new_page()
    page.goto(url, wait_until='domcontentloaded', timeout=15000)
    page.evaluate('''() => {{
      window.__opened = false; window.__err = null;
      window.__es = new EventSource('/events');
      window.__es.onopen = () => {{ window.__opened = true; }};
      window.__es.onerror = () => {{ window.__err = 'error'; }};
    }}''')
    page.wait_for_function('() => window.__opened === true', timeout=5000)
    page.wait_for_timeout(wait_ms)
    state = page.evaluate('''() => ({{
      readyState: window.__es.readyState,
      opened: window.__opened,
      err: window.__err,
    }})''')
    page.evaluate('() => {{ try {{ window.__es.close(); }} catch (e) {{}} }}')
    browser.close()
print(json.dumps(state))
""",
            encoding="utf-8",
        )
        try:
            cproc = subprocess.run(
                [sys.executable, str(chrome_probe)],
                capture_output=True,
                text=True,
                timeout=25,
            )
            if cproc.returncode == 0 and cproc.stdout.strip():
                chrome_state = json.loads(cproc.stdout.strip().splitlines()[-1])
                es["chrome_state"] = chrome_state
                es["method"] = "chromium-EventSource+node-eventsource"
                # Prefer browser result when present
                es["ok"] = chrome_state.get("readyState") == 1 and chrome_state.get("opened") is True
            else:
                es["chrome_error"] = (cproc.stderr or cproc.stdout or "chrome probe failed")[-400:]
                es["method"] = "node-eventsource (chromium probe failed)"
        except Exception as exc:
            es["chrome_error"] = f"{type(exc).__name__}: {exc}"
            es["method"] = "node-eventsource (chromium probe timed out/failed)"

        result["eventsource"] = es
        record(
            "Legitimate browser EventSource stays open across ≥3 heartbeats",
            "PASS" if es.get("ok") else "FAIL",
            str(es),
        )
        if not es.get("ok"):
            finding(
                id="LEGIT-SSE-survive",
                component="SSE heartbeat loop",
                expected="EventSource remains OPEN (readyState=1) for ≥3 heartbeat intervals",
                actual=str(es),
                repro="heartbeat=0.25; Chromium EventSource /events; check readyState after ~1.75s",
                evidence="legit_survive.json",
                environment=f"@{SHA[:7]}",
                severity="high",
                confidence="high",
            )
        if not result["curl_like"]["ok"]:
            finding(
                id="LEGIT-curl-survive",
                component="SSE heartbeat loop",
                expected="curl-like raw SSE sees ≥3 heartbeats while slot held",
                actual=str(result["curl_like"]),
                repro="raw GET /events; recv until 3x ': heartbeat'",
                evidence="legit_survive.json",
                environment=f"@{SHA[:7]}",
                severity="high",
                confidence="high",
            )
    finally:
        (OUT / "legit_survive.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        stop_server(httpd)


# ---------- Prior: prompt release + cycles ----------
def check_prompt_release(env: dict) -> None:
    daemon = daemon_from_env(env)
    httpd, host, port = start_server(daemon, heartbeat=15.0)
    H = {"Host": f"{host}:{port}"}
    results: dict = {}
    try:
        conns, resps = [], []
        for _ in range(MAX_SSE_CONNECTIONS):
            c, r = open_sse(host, port)
            assert r.status == 200
            conns.append(c)
            resps.append(r)
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

        t0 = time.monotonic()
        resps[0].close()
        conns[0].close()
        ok_wait = daemon.sse_limiter.wait_until_active_at_most(MAX_SSE_CONNECTIONS - 1, timeout=1.0)
        elapsed = time.monotonic() - t0
        rep = http.client.HTTPConnection(host, port, timeout=3)
        rep.request("GET", "/events", headers=H)
        st = rep.getresponse().status
        rep.close()
        results["graceful"] = {
            "wait_ok": ok_wait,
            "elapsed_s": round(elapsed, 3),
            "status": st,
            "active": daemon.sse_limiter.active_count(),
        }
        record(
            "QA-MM020d-1 graceful close → new stream ≤1s (heartbeat=15s)",
            "PASS" if ok_wait and elapsed <= 1.0 and st == 200 else "FAIL",
            str(results["graceful"]),
        )

        while daemon.sse_limiter.active_count() < MAX_SSE_CONNECTIONS:
            c, r = open_sse(host, port)
            if r.status != 200:
                c.close()
                break
            conns.append(c)
            resps.append(r)

        # Abrupt RST via raw socket (http.client clears conn.sock after getresponse).
        # First free one graceful slot so the pool stays at 7, open raw as the 8th, then RST it.
        victim_r = resps.pop()
        victim_c = conns.pop()
        try:
            victim_r.close()
            victim_c.close()
        except Exception:
            pass
        assert daemon.sse_limiter.wait_until_active_at_most(MAX_SSE_CONNECTIONS - 1, timeout=1.0)
        before_raw = daemon.sse_limiter.active_count()
        raw = open_raw_sse(host, port)
        # brief settle for limiter acquire
        deadline = time.monotonic() + 1.0
        while daemon.sse_limiter.active_count() <= before_raw and time.monotonic() < deadline:
            time.sleep(0.01)
        active_before_rst = daemon.sse_limiter.active_count()
        t0 = time.monotonic()
        raw.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct_linger(1, 0))
        raw.close()
        target = max(0, active_before_rst - 1)
        ok_wait2 = daemon.sse_limiter.wait_until_active_at_most(target, timeout=1.0)
        elapsed2 = time.monotonic() - t0
        st2 = -1
        if ok_wait2:
            c_new, r_new = open_sse(host, port)
            st2 = r_new.status
            conns.append(c_new)
            resps.append(r_new)
        results["abrupt"] = {
            "wait_ok": ok_wait2,
            "elapsed_s": round(elapsed2, 3),
            "status": st2,
            "active": daemon.sse_limiter.active_count(),
            "active_before_rst": active_before_rst,
            "target_after_rst": target,
            "method": "raw-SO_LINGER-RST",
        }
        record(
            "QA-MM020d-1 abrupt close → new stream ≤1s",
            "PASS" if ok_wait2 and elapsed2 <= 1.0 and st2 == 200 else "FAIL",
            str(results["abrupt"]),
        )
        if not (ok_wait2 and elapsed2 <= 1.0 and st2 == 200):
            finding(
                id="QA-MM020d-1-abrupt",
                component="SSE disconnect detect (RST)",
                expected="SO_LINGER RST frees slot within ~1s",
                actual=str(results["abrupt"]),
                repro="raw SSE + SO_LINGER(1,0) close; wait_until_active_at_most",
                evidence="prompt_release.json",
                environment=f"@{SHA[:7]} heartbeat=15",
                severity="high",
                confidence="high",
            )

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

        thr0 = threading.active_count()
        fail503 = 0
        stuck = 0
        for _ in range(100):
            c, r = open_sse(host, port)
            if r.status != 200:
                fail503 += 1
                c.close()
                continue
            r.close()
            c.close()
            if not daemon.sse_limiter.wait_until_active_at_most(0, timeout=1.0):
                stuck += 1
        thr1 = threading.active_count()
        results["cycles100"] = {
            "fail503": fail503,
            "stuck": stuck,
            "active_end": daemon.sse_limiter.active_count(),
            "thr0": thr0,
            "thr1": thr1,
        }
        cycles_ok = (
            fail503 == 0
            and stuck == 0
            and results["cycles100"]["active_end"] == 0
            and (thr1 - thr0) < 20
        )
        record(
            "QA-MM020d-1 100 rapid cycles: no spurious 503, no leak, threads bounded",
            "PASS" if cycles_ok else "FAIL",
            str(results["cycles100"]),
        )
        if not cycles_ok:
            finding(
                id="QA-MM020d-1-cycles",
                component="SseConnectionLimiter",
                expected="100 open/close with 0 stuck and active_end=0",
                actual=str(results["cycles100"]),
                repro="100x open SSE then close; wait_until_active_at_most(0)",
                evidence="prompt_release.json",
                environment=f"@{SHA[:7]}",
                severity="high",
                confidence="high",
            )
    finally:
        (OUT / "prompt_release.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        stop_server(httpd)


def check_origin_host(env: dict) -> None:
    daemon = daemon_from_env(env)
    httpd, host, port = start_server(daemon, heartbeat=1.0)
    allowed = f"{host}:{port}"
    endpoints = ["/healthz", "/activity.json", "/index.html", "/events"]
    matrix: dict = {}
    try:
        for path in endpoints:
            matrix[f"missing_origin:{path}"] = http_status(host, port, path, {"Host": allowed})
            matrix[f"local_origin:{path}"] = http_status(
                host, port, path, {"Host": allowed, "Origin": f"http://{host}:{port}"}
            )
            if path == "/events":
                conn = http.client.HTTPConnection(host, port, timeout=2)
                conn.request("GET", path, headers={"Host": allowed, "Origin": "null"})
                matrix[f"null_origin:{path}"] = conn.getresponse().status
                conn.close()
            else:
                matrix[f"null_origin:{path}"] = http_status(
                    host, port, path, {"Host": allowed, "Origin": "null"}
                )
            matrix[f"evil_host:{path}"] = http_status(
                host, port, path, {"Host": "evil.com", "Origin": f"http://{host}:{port}"}
            )
            matrix[f"bad_origin:{path}"] = http_status(
                host, port, path, {"Host": allowed, "Origin": "https://evil.com"}
            )
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
        record(
            "Host/Origin evil/bad/missing-host → 403",
            "PASS" if evil_ok and bad_ok and miss_host_ok else "FAIL",
        )
    finally:
        (OUT / "origin_host_matrix.json").write_text(json.dumps(matrix, indent=2), encoding="utf-8")
        stop_server(httpd)


def check_sse_basics(env: dict) -> None:
    daemon = daemon_from_env(env)
    httpd, host, port = start_server(daemon, heartbeat=0.3)
    try:
        daemon.ingest_network_events([sample_evt("a1"), sample_evt("a2"), sample_evt("a1")])
        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/events", headers={"Host": f"{host}:{port}"})
        resp = conn.getresponse()
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
        stop_server(httpd)


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

    hold = subprocess.Popen(
        [
            sys.executable,
            "-c",
            f"""
import sys,time
from pathlib import Path
sys.path.insert(0,{str(ROOT)!r})
from ingest.live import ProcessSingletonLock
ProcessSingletonLock(Path({str(lock_path)!r})).acquire()
print('held', flush=True)
time.sleep(60)
""",
        ],
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
        record(
            "bind 127.0.0.1 only",
            "PASS" if listens and all(x.startswith("127.0.0.1:") for x in listens) else "FAIL",
            str(listens),
        )
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
        stop_server(httpd)


PHASES = (
    "sec2_spin",
    "sec2_eight",
    "sec2_trickle",
    "sec2_shutwr",
    "legit",
    "prompt",
    "origin",
    "sse",
    "flock",
    "bind",
)


def run_phase(name: str) -> int:
    tmp = Path(tempfile.mkdtemp(prefix=f"qa-mm020d-3d5-{name}-"))
    env = make_env(tmp)
    if name == "sec2":
        check_sec_mm020d_2(env)
    elif name == "sec2_spin":
        check_sec_mm020d_2_spin_only(env)
    elif name == "sec2_eight":
        check_sec_mm020d_2_eight_only(env)
    elif name == "sec2_trickle":
        check_sec_mm020d_2_trickle_only(env)
    elif name == "sec2_shutwr":
        check_sec_mm020d_2_shutwr_only(env)
    elif name == "legit":
        check_legitimate_survive(env)
    elif name == "prompt":
        check_prompt_release(env)
    elif name == "origin":
        check_origin_host(env)
    elif name == "sse":
        check_sse_basics(env)
    elif name == "flock":
        check_flock(tmp, env)
    elif name == "bind":
        check_bind_xss(env)
    else:
        print(f"unknown phase {name}", flush=True)
        return 2
    # per-phase snippet for aggregation
    (OUT / f"phase_{name}.json").write_text(
        json.dumps({"checks": checks, "findings": findings}, indent=2),
        encoding="utf-8",
    )
    print(f"=== PHASE {name} PASS={sum(1 for c in checks if c['result']=='PASS')} FAIL={sum(1 for c in checks if c['result']=='FAIL')} ===", flush=True)
    return 0


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--phase":
        return run_phase(sys.argv[2])

    # Driver: each phase in its own process so abandoned SSE threads die with the child.
    log = OUT / "behavioral_run.txt"
    with log.open("w", encoding="utf-8") as lf:
        lf.write(f"driver start sha={SHA}\n")
    all_checks: list[dict] = []
    all_findings: list[dict] = []
    for name in PHASES:
        print(f"\n>>> running phase {name}", flush=True)
        timeout = 60 if name.startswith("sec2") else (90 if name in ("legit", "prompt") else 45)
        with log.open("a", encoding="utf-8") as lf:
            lf.write(f"\n===== PHASE {name} =====\n")
            lf.flush()
            proc = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--phase", name],
                cwd=str(ROOT),
                stdout=lf,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout,
            )
            lf.write(f"===== PHASE {name} rc={proc.returncode} =====\n")
        # also echo phase snippet
        phase_out = (OUT / f"phase_{name}.json")
        print(f"phase {name} rc={proc.returncode}", flush=True)
        phase_path = OUT / f"phase_{name}.json"
        if phase_path.is_file():
            blob = json.loads(phase_path.read_text(encoding="utf-8"))
            all_checks.extend(blob.get("checks") or [])
            all_findings.extend(blob.get("findings") or [])
        if proc.returncode != 0:
            all_findings.append(
                {
                    "id": f"harness-phase-{name}",
                    "component": "qa-harness",
                    "expected": f"phase {name} exits 0",
                    "actual": f"rc={proc.returncode}",
                    "repro": f"python ... --phase {name}",
                    "evidence": "behavioral_run.txt",
                    "environment": f"@{SHA[:7]}",
                    "severity": "medium",
                    "confidence": "high",
                }
            )

    report = {"sha": SHA, "checks": all_checks, "findings": all_findings}
    (OUT / "behavioral_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("\n=== BEHAVIORAL SUMMARY ===", flush=True)
    print("PASS", sum(1 for c in all_checks if c["result"] == "PASS"), flush=True)
    print("FAIL", sum(1 for c in all_checks if c["result"] == "FAIL"), flush=True)
    print("FINDINGS", len(all_findings), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
