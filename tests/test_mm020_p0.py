"""MM-020-P0: network→activity without ledger, /refresh, honest fallback."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http import HTTPStatus
from pathlib import Path

import pytest

from ingest.build import resolve_project_name
from ingest.demo_mode import empty_live_activity_bytes
from ingest.github_poller import GitHubPollResult
from ingest.ledger_parser import LedgerParseResult
from ingest.live import (
    LiveDaemon,
    assemble_activity,
    create_http_server,
    host_header_allowed,
    localhost_request_allowed,
    network_event_to_activity_event,
)
from tests.test_live import _daemon, _http_get, _wait_for_port, live_env

ROOT = Path(__file__).resolve().parents[1]
BOTS_PATH = ROOT / "config" / "bots.json"


@pytest.fixture
def bots() -> list[dict]:
    with BOTS_PATH.open(encoding="utf-8") as f:
        return json.load(f)["bots"]


def test_no_ledger_plus_network_events_nonempty_activity(
    tmp_path: Path, bots: list[dict]
) -> None:
    daemon = LiveDaemon(
        ledger_path=tmp_path / "missing.md",
        activity_path=tmp_path / "activity.json",
        static_dir=tmp_path,
        cache_dir=tmp_path / "cache",
        bots=bots,
        ledger_source="path",
        events_source="off",
    )
    daemon._meta_ledger = "unavailable"
    daemon._health.github_status = "ok"
    daemon._gh = GitHubPollResult(
        events=[
            {
                "id": "gh-evt-1",
                "type": "note",
                "actor": "dev-1",
                "target": None,
                "task_id": None,
                "attribution": {"method": "unknown"},
                "source_url": "https://github.com/ManpreetS2/agent-mindmap/pull/1",
                "source_time": "2026-10-20T12:00:00Z",
                "raw": "note",
                "provenance": "github-verified",
            }
        ],
        meta_github="ok",
    )
    daemon._gh_fp = "fp"
    daemon.ingest_network_events(
        [
            {
                "id": "net-1",
                "ts": "2026-10-20T12:01:00+00:00",
                "sender": "director",
                "recipients": ["architect"],
                "group": "build",
                "type": "message",
                "summary": "ping",
                "provenance": "agent-reported",
            }
        ]
    )
    assert daemon.maybe_rebuild(force=True)
    doc = json.loads(daemon.activity_path.read_text(encoding="utf-8"))
    assert doc["meta"]["ledger"] == "unavailable"
    assert doc["meta"]["github"] == "ok"
    assert doc["events"]
    assert any(e["id"] == "net-1" for e in doc["events"])
    assert any(e["type"] == "message" for e in doc["edges"])


def test_new_network_event_after_rebuild(live_env: dict) -> None:
    daemon = _daemon(live_env, events_source="off")
    daemon.run_poll_cycle()
    daemon.ingest_network_events(
        [
            {
                "id": "p0-new-evt",
                "ts": "2026-10-20T12:00:00+00:00",
                "sender": "dev-1",
                "recipients": ["dev-2"],
                "group": "build",
                "type": "message",
                "summary": "after rebuild",
                "provenance": "agent-reported",
            }
        ]
    )
    assert daemon.maybe_rebuild(force=True)
    doc = json.loads(live_env["activity"].read_text(encoding="utf-8"))
    assert any(e.get("id") == "p0-new-evt" for e in doc["events"])


def test_refresh_post_gated_rate_limited_and_polls(live_env: dict) -> None:
    daemon = _daemon(live_env, events_source="off")
    daemon.run_poll_cycle()
    httpd = create_http_server(daemon, port=0, sse_heartbeat_sec=0.15)
    thread = threading.Thread(
        target=httpd.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True
    )
    thread.start()
    host, port = httpd.server_address
    _wait_for_port(host, port)
    url = f"http://{host}:{port}/refresh"
    try:

        def post(headers: dict[str, str] | None = None) -> tuple[int, bytes]:
            req = urllib.request.Request(url, method="POST", headers=headers or {})
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    return resp.status, resp.read()
            except urllib.error.HTTPError as exc:
                return exc.code, exc.read()

        status, _ = post({"Host": "evil.example"})
        assert status == HTTPStatus.FORBIDDEN

        status, body = post({"Host": f"{host}:{port}"})
        assert status == HTTPStatus.OK
        assert json.loads(body.decode())["ok"] is True

        status, body = post({"Host": f"{host}:{port}"})
        assert status == HTTPStatus.TOO_MANY_REQUESTS
        assert json.loads(body.decode())["error"] == "rate_limited"
    finally:
        httpd.shutdown()
        thread.join(timeout=3)
        httpd.server_close()


def test_empty_fallback_no_idle_no_fencepost(bots: list[dict]) -> None:
    body = empty_live_activity_bytes(
        bots,
        generated_at="2026-10-20T12:00:00Z",
        meta_github="never_run",
        meta_ledger="unavailable",
    )
    doc = json.loads(body.decode())
    assert doc["project"] != "fencepost"
    assert doc["project"] == resolve_project_name()
    assert doc["meta"]["github"] == "never_run"
    assert doc["meta"]["ledger"] == "unavailable"
    assert all(n["status"] == "UNKNOWN" for n in doc["nodes"])


def test_assemble_partial_errored_sources(bots: list[dict]) -> None:
    empty = assemble_activity(
        ledger=LedgerParseResult(source_url="x"),
        gh=GitHubPollResult(events=[], meta_github="never_run"),
        bots=bots,
        generated_at="2026-10-20T12:00:00Z",
        meta_ledger="unavailable",
        network_events=[],
        meta_github="never_run",
    )
    assert empty["meta"]["github"] == "never_run"
    assert empty["meta"]["ledger"] == "unavailable"

    errored = assemble_activity(
        ledger=LedgerParseResult(source_url="x"),
        gh=GitHubPollResult(events=[], meta_github="error"),
        bots=bots,
        generated_at="2026-10-20T12:00:00Z",
        meta_ledger="error",
        network_events=[
            {
                "id": "n1",
                "ts": "2026-10-20T12:00:00+00:00",
                "sender": "dev-1",
                "recipients": ["dev-2"],
                "group": "build",
                "type": "message",
                "summary": "hi",
                "provenance": "agent-reported",
            }
        ],
        meta_github="error",
    )
    assert errored["meta"]["ledger"] == "error"
    assert any(e["id"] == "n1" for e in errored["events"])


def test_network_event_edges_need_explicit_recipients(bots: list[dict]) -> None:
    ne = {
        "id": "m1",
        "ts": "2026-10-20T12:00:00+00:00",
        "sender": "director",
        "group": "build",
        "type": "message",
        "summary": "no recipients",
        "provenance": "agent-reported",
    }
    evt = network_event_to_activity_event(ne, bots=bots)
    assert evt is not None
    from ingest.edges import derive_edges

    edges = derive_edges([evt])
    assert not any(
        e["type"] == "message" and e["target"] == "architect" for e in edges
    )
