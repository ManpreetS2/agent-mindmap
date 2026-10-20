"""MM-020i: DEMO mode for ingest.live."""

from __future__ import annotations

import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
from http import HTTPStatus
from pathlib import Path
from typing import Iterator
from unittest.mock import MagicMock

import pytest

from ingest.build import main as ingest_main
from ingest.demo_mode import (
    UnsafeActivityOutError,
    activity_bytes_match_server_mode,
    activity_meta_mode,
    assert_safe_activity_out_path,
    load_demo_activity_bytes,
    load_demo_network_events,
)
from ingest.live import LiveDaemon, build_arg_parser, create_http_server, main as live_main
from tests.test_github_poller import MockGh

ROOT = Path(__file__).resolve().parents[1]
BOTS_PATH = ROOT / "config" / "bots.json"
LEDGER = ROOT / "tests" / "fixtures" / "ledger-sample.md"
START_MAC = ROOT / "scripts" / "start-mac.sh"


@pytest.fixture
def bots() -> list[dict]:
    with BOTS_PATH.open(encoding="utf-8") as f:
        return json.load(f)["bots"]


@pytest.fixture
def live_env(tmp_path: Path, bots: list[dict]) -> dict:
    ledger = tmp_path / "task-ledger.md"
    shutil.copy(LEDGER, ledger)
    static = tmp_path / "dist"
    static.mkdir()
    (static / "index.html").write_text("<html>ok</html>", encoding="utf-8")
    activity = static / "activity.json"
    return {
        "ledger": ledger,
        "static": static,
        "activity": activity,
        "cache": tmp_path / "cache",
        "bots": bots,
    }


@pytest.fixture
def demo_env(tmp_path: Path, bots: list[dict]) -> dict:
    static = tmp_path / "dist"
    static.mkdir()
    (static / "index.html").write_text("<html>demo</html>", encoding="utf-8")
    activity = static / "activity.json"
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    shutil.copy(ROOT / "fixtures" / "sample-activity.json", fixtures / "sample-activity.json")
    shutil.copy(
        ROOT / "fixtures" / "demo-network-events.jsonl",
        fixtures / "demo-network-events.jsonl",
    )
    return {
        "static": static,
        "activity": activity,
        "cache": tmp_path / "cache",
        "bots": bots,
        "fixtures": fixtures,
    }


def _demo_daemon(env: dict) -> LiveDaemon:
    return LiveDaemon(
        ledger_source="path",
        ledger_path=None,
        activity_path=env["activity"],
        static_dir=env["static"],
        cache_dir=env["cache"],
        bots=env["bots"],
        demo_mode=True,
        fixtures_dir=env["fixtures"],
        github_runner=MockGh(),
    )


@pytest.fixture
def demo_http(demo_env: dict) -> Iterator[tuple[LiveDaemon, str, int]]:
    daemon = _demo_daemon(demo_env)
    daemon.bootstrap_demo()
    httpd = create_http_server(daemon, port=0, sse_heartbeat_sec=0.15)
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True)
    thread.start()
    host, port = httpd.server_address
    deadline = 3.0
    import time

    end = time.monotonic() + deadline
    while time.monotonic() < end:
        try:
            with socket.create_connection((host, port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.05)
    try:
        yield daemon, host, port
    finally:
        httpd.shutdown()
        thread.join(timeout=3)
        httpd.server_close()


def _read_sse_until(host: str, port: int, want_id: str, timeout: float = 3.0) -> list[dict]:
    import time

    conn = http.client.HTTPConnection(host, port, timeout=5)
    conn.request("GET", "/events", headers={"Host": f"{host}:{port}"})
    resp = conn.getresponse()
    assert resp.status == HTTPStatus.OK
    buf = b""
    events: list[dict] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        chunk = resp.read(256)
        if not chunk:
            break
        buf += chunk
        while b"\n\n" in buf:
            block, buf = buf.split(b"\n\n", 1)
            text = block.decode("utf-8", errors="replace")
            data_lines = [ln[6:] for ln in text.splitlines() if ln.startswith("data:")]
            if not data_lines:
                continue
            evt = json.loads("\n".join(data_lines))
            events.append(evt)
            if evt.get("id") == want_id:
                conn.close()
                return events
    conn.close()
    return events


def test_demo_healthz_and_sse_mode_field(demo_http: tuple[LiveDaemon, str, int]) -> None:
    daemon, host, port = demo_http
    conn = http.client.HTTPConnection(host, port, timeout=5)
    conn.request("GET", "/healthz", headers={"Host": f"{host}:{port}"})
    health = json.loads(conn.getresponse().read().decode())
    assert health["mode"] == "demo"
    assert health["network_event_count"] >= 3

    events = _read_sse_until(host, port, "demo-evt-1")
    assert events[0]["id"] == "demo-evt-1"
    assert events[0]["mode"] == "demo"


def test_demo_last_event_id_replay(demo_http: tuple[LiveDaemon, str, int]) -> None:
    _, host, port = demo_http
    import time

    conn = http.client.HTTPConnection(host, port, timeout=5)
    conn.request(
        "GET",
        "/events",
        headers={"Host": f"{host}:{port}", "Last-Event-ID": "demo-evt-1"},
    )
    resp = conn.getresponse()
    assert resp.status == HTTPStatus.OK
    buf = b""
    ids: list[str] = []
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        chunk = resp.read(256)
        if not chunk:
            break
        buf += chunk
        while b"\n\n" in buf:
            block, buf = buf.split(b"\n\n", 1)
            text = block.decode("utf-8", errors="replace")
            data_lines = [ln[6:] for ln in text.splitlines() if ln.startswith("data:")]
            if not data_lines:
                continue
            evt = json.loads("\n".join(data_lines))
            ids.append(str(evt.get("id")))
            if "demo-evt-3" in ids:
                break
    conn.close()
    assert "demo-evt-2" in ids
    assert "demo-evt-1" not in ids


def test_demo_never_calls_live_poll_or_writes_activity(demo_env: dict, tmp_path: Path) -> None:
    daemon = _demo_daemon(demo_env)
    runner = MagicMock(side_effect=AssertionError("gh must not run in demo"))
    daemon.github_runner = runner
    daemon.bootstrap_demo()
    assert daemon.activity_body() is not None
    before = demo_env["activity"].exists()
    daemon.run_poll_cycle()
    daemon.start_polling()
    assert daemon.ingest_network_events([{"id": "x", "summary": "nope"}]) == []
    assert not demo_env["activity"].exists() or before == demo_env["activity"].exists()
    runner.assert_not_called()


def test_demo_malformed_fixture_line_skipped(tmp_path: Path) -> None:
    fixtures = tmp_path / "fx"
    fixtures.mkdir()
    path = fixtures / "demo-network-events.jsonl"
    path.write_text(
        "not json\n"
        '{"id":"ok-1","ts":"2026-10-20T12:00:00+00:00","sender":"director",'
        '"group":"build","type":"message","summary":"ok","provenance":"agent-reported"}\n',
        encoding="utf-8",
    )
    loaded = load_demo_network_events(fixtures)
    assert len(loaded) == 1
    assert loaded[0]["id"] == "ok-1"


def test_demo_empty_fixtures_dir_no_events(tmp_path: Path, bots: list[dict]) -> None:
    fixtures = tmp_path / "empty"
    fixtures.mkdir()
    shutil.copy(ROOT / "fixtures" / "sample-activity.json", fixtures / "sample-activity.json")
    daemon = LiveDaemon(
        activity_path=tmp_path / "out" / "activity.json",
        static_dir=tmp_path / "static",
        cache_dir=tmp_path / "cache",
        bots=bots,
        demo_mode=True,
        fixtures_dir=fixtures,
    )
    daemon.bootstrap_demo()
    assert daemon.health().network_event_count == 0
    assert daemon.health().mode == "demo"


def test_unsafe_symlink_activity_out_rejected(tmp_path: Path) -> None:
    target = tmp_path / "real" / "activity.json"
    target.parent.mkdir(parents=True)
    link = tmp_path / "activity-link.json"
    link.symlink_to(target)
    with pytest.raises(UnsafeActivityOutError):
        assert_safe_activity_out_path(link)


def test_refresh_demo_writes_activity_out(tmp_path: Path) -> None:
    out = tmp_path / "nested" / "demo-activity.json"
    rc = ingest_main(
        [
            "--ledger",
            str(LEDGER),
            "--activity-out",
            str(out),
            "--skip-github",
        ]
    )
    assert rc == 0
    assert out.is_file()
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["meta"]["github"] == "skipped"


def test_live_main_demo_skips_ledger(tmp_path: Path, bots: list[dict]) -> None:
    static = tmp_path / "dist"
    static.mkdir()
    (static / "index.html").write_text("x", encoding="utf-8")
    activity = static / "activity.json"
    port = 0
    # bind ephemeral via server in subprocess — smoke argparse + bootstrap only
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    shutil.copy(ROOT / "fixtures" / "sample-activity.json", fixtures / "sample-activity.json")
    shutil.copy(
        ROOT / "fixtures" / "demo-network-events.jsonl",
        fixtures / "demo-network-events.jsonl",
    )
    parser = build_arg_parser()
    args = parser.parse_args(
        [
            "--demo",
            "--activity-out",
            str(activity),
            "--static-dir",
            str(static),
            "--cache-dir",
            str(tmp_path / "cache"),
            "--port",
            str(port),
            "--fixtures-dir",
            str(fixtures),
        ]
    )
    assert args.demo is True


def test_start_mac_demo_skips_gh_auth_check(tmp_path: Path) -> None:
    if not START_MAC.is_file():
        pytest.skip("start-mac.sh not present")
    gh = tmp_path / "gh"
    gh.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    gh.chmod(0o755)
    text = START_MAC.read_text(encoding="utf-8")
    assert "require_gh_auth" in text
    assert "DEMO_MODE" in text
    proc = subprocess.run(
        ["/bin/bash", str(START_MAC), "--demo"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=3,
        env={
            **os.environ,
            "PATH": f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}",
        },
    )
    # Should not fail solely because gh auth exits 1 (demo skips require_gh_auth).
    assert "gh is not authenticated" not in proc.stderr


def test_live_main_unknown_flag_exits_2() -> None:
    with pytest.raises(SystemExit) as exc:
        live_main(["--not-a-real-flag"])
    assert exc.value.code == 2


def test_live_health_includes_mode_live(live_env: dict) -> None:
    from tests.test_live import _daemon

    daemon = _daemon(live_env, events_source="off")
    daemon.run_poll_cycle()
    assert daemon.health().to_json()["mode"] == "live"


def test_activity_mode_validator_demo_vs_live() -> None:
    demo = load_demo_activity_bytes(ROOT / "fixtures", mode="demo")
    assert activity_meta_mode(demo) == "demo"
    assert activity_bytes_match_server_mode(demo, "demo")
    assert not activity_bytes_match_server_mode(demo, "live")


def test_live_serves_empty_live_not_stale_demo_on_disk(
    live_env: dict, bots: list[dict]
) -> None:
    demo_body = load_demo_activity_bytes(ROOT / "fixtures", mode="demo")
    live_env["activity"].write_bytes(demo_body)
    daemon = LiveDaemon(
        ledger_source="path",
        ledger_path=live_env["ledger"].with_name("missing-ledger.md"),
        activity_path=live_env["activity"],
        static_dir=live_env["static"],
        cache_dir=live_env["cache"],
        bots=bots,
        github_runner=MockGh(),
        events_source="off",
    )
    daemon._load_activity_from_disk()
    assert daemon.activity_body() is None
    served = json.loads(daemon.activity_bytes_for_serve().decode())
    assert served["meta"]["mode"] == "live"
    assert daemon.health().mode == "live"


def test_demo_rejects_live_artifact_bytes(demo_env: dict) -> None:
    daemon = _demo_daemon(demo_env)
    live_snap = json.dumps(
        {"meta": {"mode": "live"}, "nodes": [], "tasks": [], "events": [], "edges": []}
    ).encode()
    assert not daemon._store_activity_bytes(live_snap)
    daemon.bootstrap_demo()
    served = json.loads(daemon.activity_bytes_for_serve().decode())
    assert served["meta"]["mode"] == "demo"


def test_live_main_rejects_demo_with_events_source_gh() -> None:
    assert live_main(["--demo", "--events-source", "gh"]) == 2
