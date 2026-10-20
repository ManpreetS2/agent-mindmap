#!/usr/bin/env python3
"""Playwright screenshots of LIVE/DEMO ModeBanner @ 06e5bda."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path("/tmp/qa-mm020i/checkout")
SHOTS = Path("/tmp/qa-mm020i/evidence/screenshots")
SHOTS.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from ingest.live import BIND_HOST, LiveDaemon, create_http_server  # noqa: E402
from tests.test_github_poller import MockGh  # noqa: E402


def bots():
    return json.loads((ROOT / "config/bots.json").read_text())["bots"]


def copy_dist(static: Path) -> None:
    dist = ROOT / "web" / "dist"
    for p in dist.iterdir():
        dst = static / p.name
        if p.is_file():
            shutil.copy2(p, dst)
        elif p.is_dir():
            shutil.copytree(p, dst, dirs_exist_ok=True)


def start(demo: bool, port: int):
    tmp = Path(tempfile.mkdtemp())
    static = tmp / "dist"
    static.mkdir()
    copy_dist(static)
    activity = static / "activity.json"
    d = LiveDaemon(
        ledger_source="path",
        ledger_path=ROOT / "tests/fixtures/ledger-sample.md",
        activity_path=activity,
        static_dir=static,
        cache_dir=tmp / "cache",
        bots=bots(),
        demo_mode=demo,
        fixtures_dir=ROOT / "fixtures",
        github_runner=MockGh(),
        events_source="off",
        ledger_poll_sec=3600,
        gh_poll_sec=3600,
        events_poll_sec=3600,
    )
    if demo:
        d.bootstrap_demo()
    else:
        d._load_activity_from_disk()
        d.run_poll_cycle()
    httpd = create_http_server(d, host=BIND_HOST, port=port, sse_heartbeat_sec=1.0)
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    return httpd, httpd.server_address[1]


def main() -> int:
    from playwright.sync_api import sync_playwright

    demo_httpd, demo_port = start(True, 18791)
    live_httpd, live_port = start(False, 18792)
    time.sleep(0.4)
    results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for name, port in (("demo", demo_port), ("live", live_port)):
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle", timeout=15000)
            # wait for banner
            page.wait_for_selector("[data-mode]", timeout=8000)
            mode = page.get_attribute("[data-mode]", "data-mode")
            text = page.locator("[data-mode]").inner_text()
            path = SHOTS / f"mode-banner-{name}.png"
            page.screenshot(path=str(path), full_page=False)
            # also crop banner region
            box = page.locator("[data-mode]").bounding_box()
            results[name] = {
                "port": port,
                "data_mode": mode,
                "text": text,
                "screenshot": str(path),
                "banner_box": box,
                "visible": page.locator("[data-mode]").is_visible(),
            }
            page.close()
        browser.close()
    for h in (demo_httpd, live_httpd):
        try:
            h.socket.close()
            h.server_close()
        except Exception:
            pass
    out = Path("/tmp/qa-mm020i/evidence/logs/06e5bdaf4efeb7db0d958d59a730b88c9f467e86/screenshots.json")
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))
    ok = (
        results.get("demo", {}).get("data_mode") == "demo"
        and "DEMO" in (results.get("demo", {}).get("text") or "")
        and results.get("live", {}).get("data_mode") == "live"
        and "LIVE" in (results.get("live", {}).get("text") or "")
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
