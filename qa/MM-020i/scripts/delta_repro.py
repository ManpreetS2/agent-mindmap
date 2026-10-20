#!/usr/bin/env python3
"""Delta repros for QA-MM020i-1..6 @ f1a92a9."""
from __future__ import annotations

import http.client
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path("/tmp/qa-mm020i-delta/checkout")
SHA = "f1a92a95b1248ae9a01b71744736f910df7d31d8"
OUT = Path(f"/tmp/qa-mm020i-delta/evidence/logs/{SHA}")
OUT.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from ingest.demo_mode import load_demo_activity_bytes  # noqa: E402
from ingest.live import BIND_HOST, LiveDaemon, create_http_server, main as live_main  # noqa: E402
from tests.test_github_poller import MockGh  # noqa: E402

results: list[dict] = []


def record(fid: str, ok: bool, detail: str) -> None:
    results.append({"id": fid, "result": "PASS" if ok else "FAIL", "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {fid}: {detail}", flush=True)


def bots():
    return json.loads((ROOT / "config/bots.json").read_text())["bots"]


def http_get(host, port, path):
    c = http.client.HTTPConnection(host, port, timeout=5)
    c.request("GET", path, headers={"Host": f"{host}:{port}"})
    r = c.getresponse()
    body = r.read()
    c.close()
    return r.status, body


def stop(httpd):
    try:
        httpd.socket.close()
        httpd.server_close()
    except Exception:
        pass


def check_1_2():
    """Stale demo never served in live — pre-poll and missing ledger; healthz/activity agree."""
    demo = load_demo_activity_bytes(ROOT / "fixtures")

    # Pre-poll
    tmp = Path(tempfile.mkdtemp())
    static = tmp / "d"
    static.mkdir()
    (static / "index.html").write_text("x")
    act = static / "activity.json"
    act.write_bytes(demo)
    d = LiveDaemon(
        ledger_source="path",
        ledger_path=ROOT / "tests/fixtures/ledger-sample.md",
        activity_path=act,
        static_dir=static,
        cache_dir=tmp / "c",
        bots=bots(),
        demo_mode=False,
        github_runner=MockGh(),
        events_source="off",
    )
    d._load_activity_from_disk()
    assert d.activity_body() is None or json.loads(d.activity_body()).get("meta", {}).get("mode") != "demo"
    httpd = create_http_server(d, host=BIND_HOST, port=0, sse_heartbeat_sec=1)
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    host, port = httpd.server_address
    try:
        _, actb = http_get(host, int(port), "/activity.json")
        _, hzb = http_get(host, int(port), "/healthz")
        doc = json.loads(actb)
        hz = json.loads(hzb)
        mode_a = (doc.get("meta") or {}).get("mode")
        mode_h = hz.get("mode")
        ok = mode_a == "live" and mode_h == "live" and mode_a == mode_h
        record("QA-MM020i-1", ok, f"pre-poll healthz={mode_h} activity.meta.mode={mode_a}")
    finally:
        stop(httpd)

    # Missing ledger
    tmp2 = Path(tempfile.mkdtemp())
    static2 = tmp2 / "d"
    static2.mkdir()
    (static2 / "index.html").write_text("x")
    act2 = static2 / "activity.json"
    act2.write_bytes(demo)
    d2 = LiveDaemon(
        ledger_source="path",
        ledger_path=tmp2 / "MISSING.md",
        activity_path=act2,
        static_dir=static2,
        cache_dir=tmp2 / "c",
        bots=bots(),
        demo_mode=False,
        github_runner=MockGh(),
        events_source="off",
    )
    d2._load_activity_from_disk()
    d2.run_poll_cycle()
    httpd2 = create_http_server(d2, host=BIND_HOST, port=0, sse_heartbeat_sec=1)
    threading.Thread(target=httpd2.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    host2, port2 = httpd2.server_address
    try:
        _, actb = http_get(host2, int(port2), "/activity.json")
        _, hzb = http_get(host2, int(port2), "/healthz")
        doc = json.loads(actb)
        hz = json.loads(hzb)
        mode_a = (doc.get("meta") or {}).get("mode")
        mode_h = hz.get("mode")
        ok = mode_a == "live" and mode_h == "live"
        record("QA-MM020i-2", ok, f"fail-ledger healthz={mode_h} activity.meta={doc.get('meta')}")
    finally:
        stop(httpd2)


def check_3_4_5():
    """Banner contract from source + unit-test backed semantics."""
    hook = (ROOT / "web/src/hooks/useServerMode.ts").read_text()
    banner = (ROOT / "web/src/components/ModeBanner.tsx").read_text()
    app = (ROOT / "web/src/App.tsx").read_text()

    always = "bannerState" in app and "serverMode ?" not in app.replace("\n", "")
    has_loading = "LOADING MODE" in banner
    has_unknown = "UNKNOWN MODE" in banner
    initial_loading = 'useState<ModeBannerState>("loading")' in hook
    always_visible = always and has_loading and has_unknown and initial_loading
    record(
        "QA-MM020i-3",
        always_visible,
        f"always_render={always} loading={has_loading} unknown={has_unknown} initial=loading:{initial_loading}",
    )

    # no mode / garbage → unknown, never coerced to live
    parse = (
        'if (raw === "demo") return "demo"' in hook
        and 'if (raw === "live") return "live"' in hook
        and 'return "unknown"' in hook
    )
    no_default_live = 'body.mode === "demo" ? "demo" : "live"' not in hook
    record(
        "QA-MM020i-4",
        parse and no_default_live,
        f"parseHealthzMode_strict={parse} no_default_live={no_default_live}",
    )

    # retry after failure + periodic refresh on success
    has_retry = (
        "INITIAL_BACKOFF_MS" in hook
        and "schedule(" in hook
        and "setBannerState(\"unknown\")" in hook.replace("'", '"')
        or ('setBannerState("unknown")' in hook)
    )
    has_backoff = "attemptRef" in hook and "MAX_BACKOFF_MS" in hook
    record(
        "QA-MM020i-5",
        bool(has_retry and has_backoff),
        f"backoff={has_backoff} unknown_on_error={'setBannerState(\"unknown\")' in hook}",
    )


def check_6():
    rc = live_main(["--demo", "--events-source", "gh"])
    # also CLI subprocess for stderr message
    proc = subprocess.run(
        [sys.executable, "-m", "ingest.live", "--demo", "--events-source", "gh"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=15,
    )
    ok = rc == 2 and proc.returncode == 2 and "cannot be used" in (proc.stderr + proc.stdout)
    record("QA-MM020i-6", ok, f"rc={rc} proc_rc={proc.returncode} stderr={proc.stderr.strip()[:160]}")


def check_new_issues_smoke():
    """Lean: conflict markers gone; assemble_activity sets mode=live; demo still boots."""
    sm = (ROOT / "scripts/start-mac.sh").read_text()
    no_markers = "<<<<<<" not in sm and ">>>>>>" not in sm
    from ingest.live import assemble_activity
    from ingest.github_poller import GitHubPollResult
    from ingest.ledger_parser import parse_ledger_file

    ledger = parse_ledger_file(ROOT / "tests/fixtures/ledger-sample.md", bots=bots())
    act = assemble_activity(
        ledger=ledger,
        gh=GitHubPollResult(events=[], meta_github="skipped"),
        bots=bots(),
        generated_at="2026-10-20T00:00:00+00:00",
        meta_ledger="ok",
    )
    live_mode = (act.get("meta") or {}).get("mode") == "live"

    tmp = Path(tempfile.mkdtemp())
    static = tmp / "d"
    static.mkdir()
    (static / "index.html").write_text("x")
    d = LiveDaemon(
        ledger_source="path",
        ledger_path=None,
        activity_path=static / "a.json",
        static_dir=static,
        cache_dir=tmp / "c",
        bots=bots(),
        demo_mode=True,
        fixtures_dir=ROOT / "fixtures",
        github_runner=MockGh(),
        events_source="off",
    )
    d.bootstrap_demo()
    served = json.loads(d.activity_bytes_for_serve())
    demo_ok = served["meta"]["mode"] == "demo"
    record(
        "DELTA-no-new-issues-smoke",
        no_markers and live_mode and demo_ok,
        f"no_markers={no_markers} assemble_mode_live={live_mode} demo_serve={demo_ok}",
    )


def main() -> int:
    check_1_2()
    check_3_4_5()
    check_6()
    check_new_issues_smoke()
    (OUT / "delta_repro.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    fails = sum(1 for r in results if r["result"] == "FAIL")
    print(f"\nPASS {sum(1 for r in results if r['result']=='PASS')} FAIL {fails}", flush=True)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
