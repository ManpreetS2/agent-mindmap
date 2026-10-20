#!/usr/bin/env python3
"""Independent QA behavioral harness — MM-020i PR #24 @ 06e5bda."""
from __future__ import annotations

import http.client
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path("/tmp/qa-mm020i/checkout")
SHA = "06e5bdaf4efeb7db0d958d59a730b88c9f467e86"
OUT = Path(f"/tmp/qa-mm020i/evidence/logs/{SHA}")
OUT.mkdir(parents=True, exist_ok=True)
SHOTS = Path("/tmp/qa-mm020i/evidence/screenshots")
SHOTS.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from ingest.live import (  # noqa: E402
    BIND_HOST,
    LiveDaemon,
    create_http_server,
    main as live_main,
)
from tests.test_github_poller import MockGh  # noqa: E402

checks: list[dict] = []
findings: list[dict] = []


def record(check: str, result: str, detail: str = "") -> None:
    checks.append({"check": check, "result": result, "detail": detail})
    print(f"[{result}] {check}" + (f" — {detail}" if detail else ""), flush=True)


def finding(**kwargs) -> None:
    findings.append(kwargs)
    print(f"[FINDING:{kwargs.get('severity')}] {kwargs.get('id')}: {kwargs.get('actual')[:200]}", flush=True)


def bots() -> list:
    with (ROOT / "config" / "bots.json").open(encoding="utf-8") as f:
        return json.load(f)["bots"]


def start_demo(*, port: int = 0, fixtures: Path | None = None, activity: Path | None = None, static: Path | None = None):
    tmp = Path(tempfile.mkdtemp(prefix="demo-"))
    static = static or (tmp / "dist")
    static.mkdir(parents=True, exist_ok=True)
    if not (static / "index.html").is_file():
        # copy built UI if available
        dist = ROOT / "web" / "dist"
        if dist.is_dir():
            for p in dist.iterdir():
                if p.is_file():
                    shutil.copy2(p, static / p.name)
                elif p.is_dir():
                    shutil.copytree(p, static / p.name, dirs_exist_ok=True)
        else:
            (static / "index.html").write_text("<html>demo</html>", encoding="utf-8")
    activity = activity or (static / "activity.json")
    fx = fixtures or (ROOT / "fixtures")
    d = LiveDaemon(
        ledger_source="path",
        ledger_path=None,
        activity_path=activity,
        static_dir=static,
        cache_dir=tmp / "cache",
        bots=bots(),
        demo_mode=True,
        fixtures_dir=fx,
        github_runner=MockGh(),
        events_source="off",
    )
    d.bootstrap_demo()
    httpd = create_http_server(d, host=BIND_HOST, port=port, sse_heartbeat_sec=0.2)
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    host, p = httpd.server_address
    return d, httpd, host, int(p), tmp


def start_live(*, port: int = 0, activity: Path | None = None, ledger: Path | None = None, runner=None):
    tmp = Path(tempfile.mkdtemp(prefix="live-"))
    static = tmp / "dist"
    static.mkdir()
    dist = ROOT / "web" / "dist"
    if dist.is_dir():
        for p in dist.iterdir():
            if p.is_file():
                shutil.copy2(p, static / p.name)
            elif p.is_dir():
                shutil.copytree(p, static / p.name, dirs_exist_ok=True)
    else:
        (static / "index.html").write_text("<html>live</html>", encoding="utf-8")
    activity = activity or (static / "activity.json")
    ledger = ledger or (ROOT / "tests" / "fixtures" / "ledger-sample.md")
    calls: list = []

    def tracking_runner(args, **kwargs):
        calls.append(list(args))
        return MockGh()(args, **kwargs)

    d = LiveDaemon(
        ledger_source="path",
        ledger_path=ledger,
        activity_path=activity,
        static_dir=static,
        cache_dir=tmp / "cache",
        bots=bots(),
        demo_mode=False,
        github_runner=runner or tracking_runner,
        events_source="off",
        ledger_poll_sec=3600,
        gh_poll_sec=3600,
        events_poll_sec=3600,
    )
    d._load_activity_from_disk()
    d.run_poll_cycle()
    httpd = create_http_server(d, host=BIND_HOST, port=port, sse_heartbeat_sec=0.2)
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    host, p = httpd.server_address
    return d, httpd, host, int(p), tmp, calls


def stop(httpd) -> None:
    try:
        httpd.socket.close()
    except Exception:
        pass
    try:
        httpd.server_close()
    except Exception:
        pass


def http_get(host, port, path, headers=None):
    conn = http.client.HTTPConnection(host, port, timeout=5)
    h = {"Host": f"{host}:{port}"}
    if headers:
        h.update(headers)
    conn.request("GET", path, headers=h)
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    return resp.status, dict(resp.headers), body


def read_sse_events(host, port, *, last_id=None, want_n=3, timeout=4.0):
    conn = http.client.HTTPConnection(host, port, timeout=5)
    hdrs = {"Host": f"{host}:{port}"}
    if last_id:
        hdrs["Last-Event-ID"] = last_id
    conn.request("GET", "/events", headers=hdrs)
    resp = conn.getresponse()
    assert resp.status == 200, resp.status
    buf = b""
    events = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and len(events) < want_n:
        chunk = resp.read(256)
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
                events.append(json.loads(data))
    conn.close()
    return events


# ---------- (1) Demo SSE ----------
def check_demo_sse():
    d, httpd, host, port, tmp = start_demo()
    try:
        st, _, body = http_get(host, port, "/healthz")
        health = json.loads(body)
        record("demo /healthz mode=demo", "PASS" if st == 200 and health.get("mode") == "demo" else "FAIL", str(health)[:200])
        if health.get("mode") != "demo":
            finding(id="DEMO-healthz-mode", component="/healthz", expected="mode=demo", actual=str(health),
                    repro="GET /healthz on --demo server", evidence="demo_sse.json", environment="@06e5bda",
                    severity="high", confidence="high")

        ev = read_sse_events(host, port, want_n=3)
        ids = [e.get("id") for e in ev]
        modes = [e.get("mode") for e in ev]
        order_ok = ids[:3] == ["demo-evt-1", "demo-evt-2", "demo-evt-3"]
        mode_ok = all(m == "demo" for m in modes[:3])
        record("demo SSE order demo-evt-1..3", "PASS" if order_ok else "FAIL", str(ids))
        record("demo SSE payloads include mode=demo", "PASS" if mode_ok else "FAIL", str(modes))
        if not order_ok or not mode_ok:
            finding(id="DEMO-sse-order", component="/events", expected="ordered demo-evt-* with mode=demo",
                    actual=f"ids={ids} modes={modes}", repro="GET /events on demo", evidence="demo_sse.json",
                    environment="@06e5bda", severity="high", confidence="high")

        ev2 = read_sse_events(host, port, last_id="demo-evt-1", want_n=2)
        ids2 = [e.get("id") for e in ev2]
        replay_ok = "demo-evt-1" not in ids2 and "demo-evt-2" in ids2
        record("demo SSE Last-Event-ID replay", "PASS" if replay_ok else "FAIL", str(ids2))
        if not replay_ok:
            finding(id="DEMO-sse-replay", component="/events Last-Event-ID", expected="skip demo-evt-1",
                    actual=str(ids2), repro="Last-Event-ID: demo-evt-1", evidence="demo_sse.json",
                    environment="@06e5bda", severity="high", confidence="high")

        # poll fallback — /activity.json
        st, _, act = http_get(host, port, "/activity.json")
        doc = json.loads(act) if st == 200 else {}
        meta = doc.get("meta") or {}
        poll_ok = st == 200 and meta.get("mode") == "demo" and meta.get("ledger") == "demo"
        # fixture sample markers — not live ledger-only content required
        record("demo poll /activity.json serves fixture (meta.mode=demo)", "PASS" if poll_ok else "FAIL", str(meta)[:200])
        if not poll_ok:
            finding(id="DEMO-poll-activity", component="/activity.json", expected="meta.mode=demo from fixtures",
                    actual=f"status={st} meta={meta}", repro="GET /activity.json demo", evidence="demo_sse.json",
                    environment="@06e5bda", severity="high", confidence="high")

        (OUT / "demo_sse.json").write_text(json.dumps({
            "health": health, "ids": ids, "modes": modes, "replay": ids2, "activity_meta": meta
        }, indent=2), encoding="utf-8")
    finally:
        stop(httpd)


# ---------- (3) No mixing ----------
def check_no_mixing():
    # Demo: stub gh that raises; ledger path that must not be read
    poison_ledger = Path(tempfile.mkdtemp()) / "POISON-LIVE-LEDGER.md"
    poison_ledger.write_text("# LIVE ONLY CONTENT unique-live-marker-ZZZ\n", encoding="utf-8")
    calls: list = []

    def boom_runner(args, **kwargs):
        calls.append(list(args))
        raise AssertionError(f"gh called in demo: {args}")

    tmp = Path(tempfile.mkdtemp())
    static = tmp / "dist"
    static.mkdir()
    (static / "index.html").write_text("x", encoding="utf-8")
    # Place a LIVE-looking activity on disk that demo must ignore
    live_looking = {
        "schema_version": "1.1.0",
        "meta": {"mode": "live", "ledger": "path", "github": "ok", "marker": "STALE-LIVE-ON-DISK"},
        "nodes": [{"id": "live-only-node", "kind": "agent", "label": "LIVE-ONLY"}],
        "edges": [],
        "events": [],
        "unparsed": [],
    }
    activity = static / "activity.json"
    activity.write_text(json.dumps(live_looking), encoding="utf-8")

    d = LiveDaemon(
        ledger_source="path",
        ledger_path=poison_ledger,  # must never be read
        activity_path=activity,
        static_dir=static,
        cache_dir=tmp / "cache",
        bots=bots(),
        demo_mode=True,
        fixtures_dir=ROOT / "fixtures",
        github_runner=boom_runner,
        events_source="gh",  # even if requested
    )
    # instrument ledger read
    original_read = Path.read_bytes
    reads: list[str] = []

    def tracking_read(self):
        reads.append(str(self))
        return original_read(self)

    Path.read_bytes = tracking_read  # type: ignore
    try:
        d.bootstrap_demo()
        d.run_poll_cycle()
        d.start_polling()
        time.sleep(0.2)
        httpd = create_http_server(d, host=BIND_HOST, port=0, sse_heartbeat_sec=0.2)
        threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        host, port = httpd.server_address
        st, _, act = http_get(host, int(port), "/activity.json")
        doc = json.loads(act)
        meta = doc.get("meta") or {}
        node_ids = [n.get("id") for n in doc.get("nodes") or []]
        body_txt = act.decode("utf-8", errors="replace")
        gh_ok = len(calls) == 0
        ledger_ok = not any("POISON-LIVE-LEDGER" in r for r in reads)
        disk_ok = "STALE-LIVE-ON-DISK" not in body_txt and "live-only-node" not in node_ids
        mode_ok = meta.get("mode") == "demo"
        record("demo never calls gh", "PASS" if gh_ok else "FAIL", f"calls={calls}")
        record("demo never reads poison ledger path", "PASS" if ledger_ok else "FAIL", str(reads)[:200])
        record("demo ignores stale live activity.json on disk", "PASS" if disk_ok else "FAIL", str(meta))
        record("demo activity meta.mode=demo", "PASS" if mode_ok else "FAIL", str(meta))
        if not (gh_ok and ledger_ok and disk_ok and mode_ok):
            finding(
                id="DEMO-no-live-mix",
                component="LiveDaemon demo_mode",
                expected="no gh/ledger/disk-live activity in demo responses",
                actual=f"gh_calls={calls} ledger_reads={reads} meta={meta} nodes={node_ids[:5]}",
                repro="demo with poison ledger + stale live activity.json + boom gh runner",
                evidence="no_mix.json",
                environment="@06e5bda",
                severity="high",
                confidence="high",
            )
        stop(httpd)
    finally:
        Path.read_bytes = original_read  # type: ignore

    # Live: must not serve demo-evt-* or sample fixture mode=demo
    d2, httpd2, host2, port2, tmp2, live_calls = start_live()
    try:
        st, _, act = http_get(host2, port2, "/activity.json")
        doc = json.loads(act) if st == 200 else {}
        meta = doc.get("meta") or {}
        text = act.decode("utf-8", errors="replace") if st == 200 else ""
        ev = read_sse_events(host2, port2, want_n=1, timeout=2.0)
        # live with events_source=off may have 0 SSE events — OK
        no_demo_ids = "demo-evt-" not in text and all("demo-evt" not in str(e.get("id")) for e in ev)
        no_demo_mode = meta.get("mode") != "demo"
        hz = json.loads(http_get(host2, port2, "/healthz")[2])
        record("live /healthz mode=live", "PASS" if hz.get("mode") == "live" else "FAIL", str(hz)[:120])
        record("live activity is not demo fixture (no demo-evt / mode!=demo)", "PASS" if no_demo_ids and no_demo_mode else "FAIL", str(meta))
        if not (no_demo_ids and no_demo_mode and hz.get("mode") == "live"):
            finding(
                id="LIVE-no-demo-fixtures",
                component="live mode activity/SSE",
                expected="no demo-evt-* and meta.mode!=demo",
                actual=f"meta={meta} sse={ev[:1]}",
                repro="start live with MockGh; GET /activity.json /events",
                evidence="no_mix.json",
                environment="@06e5bda",
                severity="high",
                confidence="high",
            )
    finally:
        stop(httpd2)

    # Restart / mode switch with stale file: save demo activity bytes (meta.mode=demo) then start LIVE.
    # Happy-path main() rebuilds before listen; probe (1) pre-poll serve window and (2) failed ledger rebuild.
    from ingest.demo_mode import load_demo_activity_bytes  # noqa: E402

    demo_bytes = load_demo_activity_bytes(ROOT / "fixtures")

    # (1) Load-from-disk before first successful rebuild → serves meta.mode=demo while healthz=live
    tmp3 = Path(tempfile.mkdtemp())
    static3 = tmp3 / "dist"
    static3.mkdir()
    (static3 / "index.html").write_text("x", encoding="utf-8")
    stale = static3 / "activity.json"
    stale.write_bytes(demo_bytes)
    d_pre = LiveDaemon(
        ledger_source="path",
        ledger_path=ROOT / "tests" / "fixtures" / "ledger-sample.md",
        activity_path=stale,
        static_dir=static3,
        cache_dir=tmp3 / "cache",
        bots=bots(),
        demo_mode=False,
        github_runner=MockGh(),
        events_source="off",
        ledger_poll_sec=3600,
        gh_poll_sec=3600,
        events_poll_sec=3600,
    )
    d_pre._load_activity_from_disk()
    httpd_pre = create_http_server(d_pre, host=BIND_HOST, port=0, sse_heartbeat_sec=1.0)
    threading.Thread(target=httpd_pre.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    host_pre, port_pre = httpd_pre.server_address
    try:
        _, _, act_pre = http_get(host_pre, int(port_pre), "/activity.json")
        doc_pre = json.loads(act_pre)
        hz_pre = json.loads(http_get(host_pre, int(port_pre), "/healthz")[2])
        pre_poll_demo = (doc_pre.get("meta") or {}).get("mode") == "demo" and hz_pre.get("mode") == "live"
        record(
            "live pre-poll with stale demo activity: healthz=live but activity.meta.mode=demo",
            "FAIL" if pre_poll_demo else "PASS",
            f"healthz={hz_pre.get('mode')} meta={doc_pre.get('meta')}",
        )
        if pre_poll_demo:
            finding(
                id="LIVE-stale-demo-activity-meta-prepoll",
                component="_load_activity_from_disk",
                expected="live must not serve meta.mode=demo (strip/reject stale demo snapshot)",
                actual=f"healthz={hz_pre.get('mode')} activity.meta={doc_pre.get('meta')}",
                repro="write load_demo_activity_bytes() to activity-out; LiveDaemon._load_activity_from_disk(); GET /activity.json before run_poll_cycle",
                evidence="no_mix.json",
                environment="@06e5bda",
                severity="medium",
                confidence="high",
            )
    finally:
        stop(httpd_pre)

    # (2) Stale demo activity + failed ledger rebuild → lasting mix (healthz=live, activity mode=demo)
    tmp4 = Path(tempfile.mkdtemp())
    static4 = tmp4 / "dist"
    static4.mkdir()
    (static4 / "index.html").write_text("x", encoding="utf-8")
    stale4 = static4 / "activity.json"
    stale4.write_bytes(demo_bytes)
    d4 = LiveDaemon(
        ledger_source="path",
        ledger_path=tmp4 / "MISSING-LEDGER.md",
        activity_path=stale4,
        static_dir=static4,
        cache_dir=tmp4 / "cache",
        bots=bots(),
        demo_mode=False,
        github_runner=MockGh(),
        events_source="off",
        ledger_poll_sec=3600,
        gh_poll_sec=3600,
        events_poll_sec=3600,
    )
    d4._load_activity_from_disk()
    d4.run_poll_cycle()
    httpd4 = create_http_server(d4, host=BIND_HOST, port=0, sse_heartbeat_sec=1.0)
    threading.Thread(target=httpd4.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    host4, port4 = httpd4.server_address
    try:
        _, _, act4 = http_get(host4, int(port4), "/activity.json")
        doc4 = json.loads(act4)
        hz4 = json.loads(http_get(host4, int(port4), "/healthz")[2])
        still_demo_meta = (doc4.get("meta") or {}).get("mode") == "demo"
        record(
            "live restart with stale demo activity + failed ledger: /healthz mode=live",
            "PASS" if hz4.get("mode") == "live" else "FAIL",
            str(hz4)[:120],
        )
        if still_demo_meta:
            finding(
                id="LIVE-stale-demo-activity-meta",
                component="_load_activity_from_disk + _maybe_rebuild",
                expected="live mode must not serve activity with meta.mode=demo after start",
                actual=f"healthz={hz4.get('mode')} activity.meta={doc4.get('meta')}",
                repro="write load_demo_activity_bytes() to activity-out; start live with missing ledger; GET /activity.json",
                evidence="no_mix.json",
                environment="@06e5bda",
                severity="high",
                confidence="high",
            )
            record("live does not serve meta.mode=demo from stale file when rebuild fails", "FAIL", str(doc4.get("meta")))
        else:
            record("live does not serve meta.mode=demo from stale file when rebuild fails", "PASS", str(doc4.get("meta"))[:160])
        (OUT / "no_mix.json").write_text(json.dumps({
            "demo_gh_calls": calls,
            "pre_poll": {"healthz": hz_pre.get("mode"), "meta": doc_pre.get("meta")},
            "fail_ledger": {"healthz": hz4.get("mode"), "meta": doc4.get("meta"), "still_demo_meta": still_demo_meta},
        }, indent=2), encoding="utf-8")
    finally:
        stop(httpd4)


# ---------- (4) refresh-demo ----------
def check_refresh_demo():
    tmp = Path(tempfile.mkdtemp())
    out = tmp / "nested" / "only-here" / "activity.json"
    live_out = tmp / "live-must-not-touch" / "activity.json"
    live_out.parent.mkdir(parents=True)
    live_out.write_text('{"sentinel": true}\n', encoding="utf-8")
    before = live_out.read_text()
    proc = subprocess.run(
        [
            sys.executable, "-m", "ingest",
            "--ledger", str(ROOT / "tests/fixtures/ledger-sample.md"),
            "--activity-out", str(out),
            "--skip-github",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    ok = proc.returncode == 0 and out.is_file() and live_out.read_text() == before
    record("make refresh-demo equivalent writes only --activity-out", "PASS" if ok else "FAIL",
           f"rc={proc.returncode} out_exists={out.is_file()} live_untouched={live_out.read_text()==before}")
    # Also invoke via make
    proc2 = subprocess.run(
        ["make", "refresh-demo", f"ACTIVITY_OUT={tmp / 'via-make' / 'activity.json'}", f"PYTHON={sys.executable}"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    made = tmp / "via-make" / "activity.json"
    ok2 = proc2.returncode == 0 and made.is_file() and live_out.read_text() == before
    record("make refresh-demo ACTIVITY_OUT", "PASS" if ok2 else "FAIL",
           f"rc={proc2.returncode} stderr={proc2.stderr[-200:]}")
    (OUT / "refresh_demo.json").write_text(json.dumps({
        "cli_rc": proc.returncode, "make_rc": proc2.returncode,
        "out": str(out), "make_out": str(made), "live_sentinel_ok": live_out.read_text() == before,
    }, indent=2), encoding="utf-8")
    if not ok or not ok2:
        finding(id="REFRESH-demo-path", component="make refresh-demo / --activity-out",
                expected="writes only to ACTIVITY_OUT", actual=f"cli={ok} make={ok2}",
                repro="make refresh-demo ACTIVITY_OUT=... with sentinel elsewhere",
                evidence="refresh_demo.json", environment="@06e5bda", severity="high", confidence="high")


# ---------- (5) start-mac --demo ----------
def check_start_mac_demo():
    # Ensure venv python
    py = ROOT / ".venv" / "bin" / "python"
    if not (py.is_file() and os.access(py, os.X_OK)):
        py = Path(sys.executable)
    # free 8787
    subprocess.run("ss -lptn 'sport = :8787' 2>/dev/null | awk -Fpid= 'NR>1{print $2}' | cut -d, -f1 | xargs -r kill -9", shell=True)
    time.sleep(0.3)
    env = {**os.environ, "MINDMAP_PYTHON": str(py), "PYTHONPATH": str(ROOT)}
    proc = subprocess.Popen(
        ["bash", str(ROOT / "scripts" / "start-mac.sh"), "--demo", "--", "--port", "8787",
         "--static-dir", str(ROOT / "web" / "dist"),
         "--activity-out", str(ROOT / "web" / "dist" / "activity.json"),
         "--cache-dir", str(Path(tempfile.mkdtemp()) / "cache")],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    ok = False
    health = {}
    ui = -1
    for _ in range(40):
        try:
            st, _, body = http_get("127.0.0.1", 8787, "/healthz")
            if st == 200:
                health = json.loads(body)
                if health.get("mode") == "demo":
                    ok = True
                    break
        except Exception:
            pass
        time.sleep(0.25)
    try:
        ui, _, _ = http_get("127.0.0.1", 8787, "/")
    except Exception:
        ui = -1
    # bind check
    bind_ok = False
    try:
        with socket.create_connection(("127.0.0.1", 8787), timeout=1):
            bind_ok = True
    except OSError:
        pass
    # ensure not on 0.0.0.0 by checking we can... hard on Linux without ss; try connecting via hostname
    record("start-mac.sh --demo: /healthz mode=demo on :8787", "PASS" if ok else "FAIL", str(health)[:200])
    record("start-mac.sh --demo: UI / 200", "PASS" if ui == 200 else "FAIL", f"status={ui}")
    record("start-mac.sh --demo: bind 127.0.0.1:8787 reachable", "PASS" if bind_ok else "FAIL")
    if not ok:
        err = ""
        try:
            proc.terminate()
            _, err = proc.communicate(timeout=2)
        except Exception:
            pass
        finding(id="STARTMAC-demo", component="scripts/start-mac.sh --demo",
                expected="demo server on 127.0.0.1:8787 with mode=demo",
                actual=f"health={health} ui={ui} stderr={err[-300:]}",
                repro="./scripts/start-mac.sh --demo -- --port 8787",
                evidence="start_mac_demo.json", environment="@06e5bda", severity="high", confidence="high")
    (OUT / "start_mac_demo.json").write_text(json.dumps({"health": health, "ui": ui, "bind_ok": bind_ok}, indent=2), encoding="utf-8")
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except Exception:
        proc.kill()
    subprocess.run("ss -lptn 'sport = :8787' 2>/dev/null | awk -Fpid= 'NR>1{print $2}' | cut -d, -f1 | xargs -r kill -9", shell=True)
    time.sleep(0.3)


# ---------- (6) Edge cases ----------
def check_edges():
    # malformed / missing fixtures — covered lightly + CLI
    # --demo with --events-source gh (should not mix; ideally reject or ignore safely)
    tmp = Path(tempfile.mkdtemp())
    static = tmp / "d"
    static.mkdir()
    (static / "index.html").write_text("x", encoding="utf-8")
    activity = static / "activity.json"
    # Run live_main in thread? Better subprocess with timeout
    proc = subprocess.Popen(
        [sys.executable, "-m", "ingest.live", "--demo", "--events-source", "gh",
         "--port", "0", "--static-dir", str(static), "--activity-out", str(activity),
         "--cache-dir", str(tmp / "c"), "--fixtures-dir", str(ROOT / "fixtures")],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    # parse port from stderr is hard with port 0 — use fixed high port
    proc.kill()
    try:
        proc.wait(timeout=2)
    except Exception:
        pass

    port = 18787
    subprocess.run(f"ss -lptn 'sport = :{port}' 2>/dev/null | awk -Fpid= 'NR>1{{print $2}}' | cut -d, -f1 | xargs -r kill -9", shell=True)
    proc = subprocess.Popen(
        [sys.executable, "-m", "ingest.live", "--demo", "--events-source", "gh",
         "--port", str(port), "--static-dir", str(static), "--activity-out", str(activity),
         "--cache-dir", str(tmp / "c2"), "--fixtures-dir", str(ROOT / "fixtures")],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    started = False
    for _ in range(30):
        try:
            st, _, body = http_get("127.0.0.1", port, "/healthz")
            if st == 200 and json.loads(body).get("mode") == "demo":
                started = True
                break
        except Exception:
            pass
        time.sleep(0.2)
    # Does combo get rejected? Currently accepted — record as finding if accepted without warning
    rejected = proc.poll() is not None and proc.returncode not in (None, 0)
    if started:
        record("--demo + --events-source gh starts as demo (ignores live events)", "PASS", "mode=demo")
        # Not necessarily a FAIL if safely ignored — note as low if no rejection
        finding(
            id="DEMO-flag-combo",
            component="CLI --demo + --events-source",
            expected="reject conflicting flags OR document ignore; must not enable live events ingest",
            actual="combination accepted; server runs mode=demo (events polling suppressed by demo_mode)",
            repro="python -m ingest.live --demo --events-source gh --port …",
            evidence="edges.json",
            environment="@06e5bda",
            severity="low",
            confidence="high",
        )
    else:
        record("--demo + --events-source gh", "FAIL" if not rejected else "PASS", f"started={started} rc={proc.poll()}")

    proc.terminate()
    try:
        proc.wait(timeout=2)
    except Exception:
        proc.kill()

    # port in use
    holder = socket.socket()
    holder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    holder.bind(("127.0.0.1", 18788))
    holder.listen(1)
    proc = subprocess.run(
        [sys.executable, "-m", "ingest.live", "--demo", "--port", "18788",
         "--static-dir", str(static), "--activity-out", str(tmp / "a2" / "activity.json"),
         "--cache-dir", str(tmp / "c3"), "--fixtures-dir", str(ROOT / "fixtures")],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=15,
    )
    holder.close()
    busy_ok = proc.returncode != 0 and ("Address already in use" in (proc.stderr + proc.stdout) or "error" in (proc.stderr + proc.stdout).lower())
    record("demo port-in-use → nonzero exit", "PASS" if busy_ok else "FAIL",
           f"rc={proc.returncode} stderr={proc.stderr[-200:]}")

    # missing sample-activity
    fx = tmp / "nofx"
    fx.mkdir()
    (fx / "demo-network-events.jsonl").write_text("{}\n", encoding="utf-8")  # invalid events ok
    # no sample-activity.json
    try:
        from ingest.demo_mode import load_demo_activity_bytes, DemoFixtureError
        try:
            load_demo_activity_bytes(fx)
            missing_ok = False
        except DemoFixtureError:
            missing_ok = True
    except Exception as e:
        missing_ok = False
        record("missing sample-activity raises DemoFixtureError", "FAIL", str(e))
    else:
        record("missing sample-activity raises DemoFixtureError", "PASS" if missing_ok else "FAIL")

    (OUT / "edges.json").write_text(json.dumps({
        "demo_events_source_started": started,
        "port_busy_rc": proc.returncode,
        "port_busy_stderr": proc.stderr[-300:],
        "missing_activity_fixture": missing_ok,
    }, indent=2), encoding="utf-8")


# ---------- Banner behavioral (server-side) ----------
def check_banner_server_contract():
    """Banner must be driven by /healthz mode; defaults / staleness issues."""
    # Read hook source for one-shot fetch + default-to-live
    hook = (ROOT / "web/src/hooks/useServerMode.ts").read_text(encoding="utf-8")
    app = (ROOT / "web/src/App.tsx").read_text(encoding="utf-8")
    banner = (ROOT / "web/src/components/ModeBanner.tsx").read_text(encoding="utf-8")
    oneshot = "setInterval" not in hook and "poll" not in hook.lower()
    default_live = 'body.mode === "demo" ? "demo" : "live"' in hook
    null_hides = "serverMode ? <ModeBanner" in app.replace("\n", "")
    unmistakable = "DEMO MODE" in banner and "LIVE MODE" in banner
    record("ModeBanner copy unmistakable (DEMO/LIVE strings)", "PASS" if unmistakable else "FAIL")
    record("useServerMode driven by /healthz", "PASS" if "healthz" in hook else "FAIL")
    if oneshot:
        finding(
            id="BANNER-no-refetch",
            component="useServerMode",
            expected="banner stays correct / not stale (refetch or SSE mode)",
            actual="healthz fetched once on mount; no interval/refetch — stale if mode signal changes without remount; null until fetch",
            repro="read web/src/hooks/useServerMode.ts",
            evidence="banner_contract.json",
            environment="@06e5bda",
            severity="medium",
            confidence="high",
        )
        record("banner refreshes / cannot go stale", "FAIL", "one-shot fetch only")
    else:
        record("banner refreshes / cannot go stale", "PASS")
    if null_hides:
        finding(
            id="BANNER-not-always-visible",
            component="App.tsx ModeBanner",
            expected="LIVE/DEMO bar always visible",
            actual="banner is null while serverMode===null (before/failed healthz)",
            repro="App: `const banner = serverMode ? <ModeBanner …/> : null`",
            evidence="banner_contract.json",
            environment="@06e5bda",
            severity="medium",
            confidence="high",
        )
        record("banner always visible (even before healthz)", "FAIL", "hidden when mode=null")
    else:
        record("banner always visible (even before healthz)", "PASS")
    if default_live:
        finding(
            id="BANNER-default-live",
            component="useServerMode",
            expected="unknown/missing mode must not be presented as LIVE",
            actual='any non-"demo" value (including missing) becomes "live"',
            repro='healthz without mode field → UI shows LIVE MODE',
            evidence="banner_contract.json",
            environment="@06e5bda",
            severity="medium",
            confidence="high",
        )
        record("missing mode not faked as LIVE", "FAIL", "defaults to live")
    else:
        record("missing mode not faked as LIVE", "PASS")
    (OUT / "banner_contract.json").write_text(json.dumps({
        "oneshot": oneshot, "default_live": default_live, "null_hides": null_hides, "unmistakable": unmistakable,
    }, indent=2), encoding="utf-8")


def main() -> int:
    check_demo_sse()
    check_no_mixing()
    check_refresh_demo()
    check_start_mac_demo()
    check_edges()
    check_banner_server_contract()
    report = {"sha": SHA, "checks": checks, "findings": findings}
    (OUT / "behavioral_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("\n=== SUMMARY ===", flush=True)
    print("PASS", sum(1 for c in checks if c["result"] == "PASS"), flush=True)
    print("FAIL", sum(1 for c in checks if c["result"] == "FAIL"), flush=True)
    print("FINDINGS", len(findings), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
