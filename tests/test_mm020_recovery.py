"""Recovery: GitHub health, snapshot SSE, roster, and task-id suffixes."""

from __future__ import annotations

import json
import shutil
import threading
import time
from http.client import HTTPConnection
from pathlib import Path

import pytest

from ingest.attribute import attribute_from_body, extract_task_id, load_bots
from ingest.build import build_nodes
from ingest.github_poller import GhResponse
from ingest.ledger_parser import task_id_from_column
from ingest.live import MAX_HEALTH_ERRORS, create_http_server
from tests.test_github_poller import MockGh
from tests.test_live import LEDGER, _daemon, _wait_for_port
from tools.events_mirror import validate_network_event


@pytest.fixture
def live_env(tmp_path: Path) -> dict:
    ledger = tmp_path / "task-ledger.md"
    shutil.copy(LEDGER, ledger)
    static = tmp_path / "dist"
    static.mkdir()
    (static / "index.html").write_text("<html>ok</html>", encoding="utf-8")
    return {
        "ledger": ledger,
        "static": static,
        "activity": static / "activity.json",
        "cache": tmp_path / "cache",
        "bots": load_bots(),
    }


def _fail_runner(status: int, headers: dict[str, str] | None = None):
    def runner(args: list[str], **kwargs: object) -> GhResponse:
        del args, kwargs
        return GhResponse(status=status, headers=headers or {}, body="nope")

    return runner


def test_github_outage_keeps_events_and_bounds_errors(live_env: dict) -> None:
    daemon = _daemon(live_env, events_source="off")
    daemon.run_poll_cycle()
    first = json.loads(daemon.activity_bytes_for_serve())
    assert first["meta"]["github"] == "ok"
    ids = [e["id"] for e in first["events"]]
    assert ids

    daemon.github_runner = _fail_runner(502)
    for _ in range(3):
        daemon.run_poll_cycle()
    second = json.loads(daemon.activity_bytes_for_serve())
    assert second["meta"]["github"] == "error"
    assert [e["id"] for e in second["events"]] == ids
    health = daemon.health()
    assert health.github_status == "error"
    assert len(health.errors) <= MAX_HEALTH_ERRORS

    for _ in range(12):
        daemon.run_poll_cycle()
    assert len(daemon.health().errors) <= MAX_HEALTH_ERRORS
    assert json.loads(daemon.activity_bytes_for_serve())["meta"]["github"] == "error"

    daemon.github_runner = MockGh()
    daemon._gh_backoff_until = 0
    daemon.run_poll_cycle()
    recovered = json.loads(daemon.activity_bytes_for_serve())
    assert recovered["meta"]["github"] == "ok"
    assert daemon.health().github_status == "ok"


def test_github_rate_limit_is_visible_and_keeps_events(live_env: dict) -> None:
    daemon = _daemon(live_env, events_source="off")
    daemon.run_poll_cycle()
    ids = [e["id"] for e in json.loads(daemon.activity_bytes_for_serve())["events"]]
    daemon.github_runner = _fail_runner(
        403,
        {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "0"},
    )
    daemon.run_poll_cycle()
    body = json.loads(daemon.activity_bytes_for_serve())
    assert body["meta"]["github"] == "rate_limited"
    assert [e["id"] for e in body["events"]] == ids
    assert daemon.health().github_status == "rate_limited"


def test_fresh_github_failure_is_error_not_skipped(live_env: dict) -> None:
    daemon = _daemon(live_env, events_source="off", github_runner=_fail_runner(502))
    daemon.run_poll_cycle()
    body = json.loads(daemon.activity_bytes_for_serve())
    assert body["meta"]["github"] == "error"


def test_ledger_rebuild_emits_named_activity_event(live_env: dict) -> None:
    daemon = _daemon(live_env, events_source="off")
    daemon.run_poll_cycle()
    before, _etag = daemon.activity_notice()
    httpd = create_http_server(daemon, port=0, sse_heartbeat_sec=0.2)
    thread = threading.Thread(
        target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    )
    thread.start()
    host, port = httpd.server_address
    _wait_for_port(host, port)
    chunks: list[bytes] = []

    def read_stream() -> None:
        conn = HTTPConnection(host, port, timeout=5)
        conn.request(
            "GET",
            "/events",
            headers={"Host": f"{host}:{port}", "Accept": "text/event-stream"},
        )
        resp = conn.getresponse()
        assert resp.status == 200
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            chunks.append(resp.read(256))
            text = b"".join(chunks).decode("utf-8", errors="replace")
            if f'"revision":{before + 1}' in text.replace(" ", ""):
                break
        conn.close()

    reader = threading.Thread(target=read_stream, daemon=True)
    reader.start()
    time.sleep(0.3)
    ledger = Path(live_env["ledger"])
    ledger.write_text(ledger.read_text(encoding="utf-8") + "\nrecovery marker\n", encoding="utf-8")
    assert daemon.poll_ledger_once() is True
    assert daemon.maybe_rebuild() is True
    after, etag = daemon.activity_notice()
    assert after == before + 1
    assert etag
    reader.join(timeout=5)
    httpd.shutdown()
    thread.join(timeout=3)
    httpd.server_close()
    text = b"".join(chunks).decode("utf-8", errors="replace")
    assert "event: activity" in text
    assert f'"revision":{after}' in text.replace(" ", "")
    # The activity notice must not steal Last-Event-ID from network events.
    activity_at = text.find("event: activity")
    window = text[activity_at : activity_at + 80]
    assert not window.startswith("id:")


def test_current_roster_is_eight_bots_and_one_project_manager() -> None:
    bots = load_bots()
    nodes = build_nodes(bots, [], [])
    ids = [n["id"] for n in nodes]
    assert ids.count("project-manager") == 1
    assert "director" not in ids
    assert "manpreet" in ids
    active = [n for n in nodes if n["id"] != "manpreet"]
    assert {n["id"] for n in active} == {
        "project-manager",
        "scout",
        "advocate",
        "skeptic",
        "bug-hunter",
        "engineering-researcher",
        "experiment-designer",
        "technical-tutor",
    }
    assert all(n["status"] == "UNKNOWN" for n in nodes)
    pm = next(n for n in nodes if n["id"] == "project-manager")
    assert pm["group"] == "radar"
    assert set(pm["groups"]) == {"radar", "hq"}

    evidenced = build_nodes(
        bots,
        [],
        [{"actor": "director", "source_time": "2026-10-20T00:00:00Z", "raw": ""}],
    )
    director = next(n for n in evidenced if n["id"] == "director")
    assert director["group"] == "historical"
    assert director["status"] == "UNKNOWN"
    assert attribute_from_body("ship it ~Director")[0] == "director"
    assert attribute_from_body("ship it ~Project Manager")[0] == "project-manager"


def test_task_id_suffix_is_not_truncated() -> None:
    assert extract_task_id("see MM-020-1 please") == "MM-020-1"
    assert extract_task_id("QA-RP004-1") == "QA-RP004-1"
    assert extract_task_id("MM-020-1a") is None
    assert extract_task_id("xRP-004") is None
    assert task_id_from_column("MM-020-1") == "MM-020-1"
    assert task_id_from_column("MM-020-1a") is None
    assert task_id_from_column("MM-002/MM-003") == "MM-002"
    kept = validate_network_event(
        {
            "id": "e1",
            "ts": "2026-10-20T00:00:00Z",
            "sender": "scout",
            "group": "radar",
            "type": "message",
            "summary": "suffix",
            "provenance": "agent-reported",
            "task_id": "MM-020-1",
        }
    )
    assert kept is not None and kept["task_id"] == "MM-020-1"
    dropped = validate_network_event(
        {
            "id": "e2",
            "ts": "2026-10-20T00:00:00Z",
            "sender": "scout",
            "group": "radar",
            "type": "message",
            "summary": "bad suffix",
            "provenance": "agent-reported",
            "task_id": "MM-020-1a",
        }
    )
    assert dropped is None
