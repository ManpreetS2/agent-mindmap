"""MM-020-P0: network→activity without ledger, /refresh, honest fallback."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from http import HTTPStatus
from pathlib import Path
from unittest.mock import patch

import pytest

from ingest.build import PROJECT_NAME_RE, resolve_project_name
from ingest.demo_mode import empty_live_activity_bytes
from ingest.github_poller import GitHubPollResult
from ingest.ledger_fetch import LedgerFetchResult
from ingest.ledger_parser import LedgerParseResult
from ingest.live import (
    LiveDaemon,
    assemble_activity,
    create_http_server,
    network_event_to_activity_event,
)
from tests.test_live import _daemon, _wait_for_port, live_env

ROOT = Path(__file__).resolve().parents[1]
BOTS_PATH = ROOT / "config" / "bots.json"
LEDGER_FIXTURE = ROOT / "tests" / "fixtures" / "ledger-sample.md"


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
    assert doc["meta"]["project"] == doc["project"]
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


def _refresh_server(daemon: LiveDaemon) -> tuple:
    httpd = create_http_server(daemon, port=0, sse_heartbeat_sec=0.15)
    thread = threading.Thread(
        target=httpd.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True
    )
    thread.start()
    host, port = httpd.server_address
    _wait_for_port(host, port)
    return httpd, thread, host, port


def test_refresh_post_gated_rate_limited_and_polls(live_env: dict) -> None:
    daemon = _daemon(live_env, events_source="off")
    daemon.ledger_poll_sec = 3600.0
    daemon.gh_poll_sec = 3600.0
    daemon.events_poll_sec = 3600.0
    daemon.start_polling()
    httpd, thread, host, port = _refresh_server(daemon)
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

        status, _ = post(
            {"Host": f"{host}:{port}", "Origin": "https://evil.example"}
        )
        assert status == HTTPStatus.FORBIDDEN

        status, body = post({"Host": f"{host}:{port}"})
        assert status == HTTPStatus.ACCEPTED
        assert json.loads(body.decode())["queued"] is True

        status, body = post({"Host": f"{host}:{port}"})
        assert status == HTTPStatus.TOO_MANY_REQUESTS
        payload = json.loads(body.decode())
        assert payload["retry_after_s"] >= 1
    finally:
        daemon.stop_polling()
        httpd.shutdown()
        thread.join(timeout=3)
        httpd.server_close()


def test_refresh_handler_returns_fast_with_slow_gh(
    live_env: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    daemon = _daemon(live_env, events_source="off")
    daemon.ledger_poll_sec = 3600.0
    daemon.gh_poll_sec = 3600.0
    daemon.events_poll_sec = 3600.0

    def slow_poll(*_args: object, **_kwargs: object) -> GitHubPollResult:
        time.sleep(2.0)
        return GitHubPollResult(events=[], meta_github="never_run")

    monkeypatch.setattr("ingest.live.poll_github", slow_poll)
    daemon.start_polling()
    httpd, thread, host, port = _refresh_server(daemon)
    url = f"http://{host}:{port}/refresh"
    try:
        req = urllib.request.Request(
            url, method="POST", headers={"Host": f"{host}:{port}"}
        )
        t0 = time.monotonic()
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == HTTPStatus.ACCEPTED
        assert time.monotonic() - t0 < 0.15
    finally:
        daemon.stop_polling()
        httpd.shutdown()
        thread.join(timeout=3)
        httpd.server_close()


def test_refresh_forbidden_does_not_queue_or_record(live_env: dict) -> None:
    daemon = _daemon(live_env, events_source="off")
    assert daemon._last_refresh_at == 0.0
    httpd, thread, host, port = _refresh_server(daemon)
    url = f"http://{host}:{port}/refresh"
    try:
        for headers in (
            {"Host": "evil.example"},
            {"Host": f"{host}:{port}", "Origin": "null"},
            {"Host": f"{host}:{port}", "Origin": "https://evil.example"},
        ):
            req = urllib.request.Request(url, method="POST", headers=headers)
            with pytest.raises(urllib.error.HTTPError) as exc:
                urllib.request.urlopen(req, timeout=5)
            assert exc.value.code == HTTPStatus.FORBIDDEN
        assert daemon._last_refresh_at == 0.0
        assert not daemon.refresh_pending()
    finally:
        httpd.shutdown()
        thread.join(timeout=3)
        httpd.server_close()


def test_try_refresh_queues_poll_thread_work(live_env: dict) -> None:
    daemon = _daemon(live_env, events_source="off")
    daemon.ledger_poll_sec = 3600.0
    daemon.gh_poll_sec = 3600.0
    daemon.events_poll_sec = 3600.0
    done = threading.Event()
    real = daemon._run_refresh_cycle

    def wrapped() -> None:
        real()
        done.set()

    daemon._run_refresh_cycle = wrapped  # type: ignore[method-assign]
    daemon.start_polling()
    ok, reason, _ = daemon.try_refresh()
    assert ok and reason == ""
    assert done.wait(timeout=3.0)
    daemon.stop_polling()


def test_refresh_flood_rate_limited_no_pileup(live_env: dict) -> None:
    daemon = _daemon(live_env, events_source="off")
    daemon.ledger_poll_sec = 3600.0
    daemon.gh_poll_sec = 3600.0
    daemon.events_poll_sec = 3600.0
    daemon.start_polling()
    httpd, thread, host, port = _refresh_server(daemon)
    url = f"http://{host}:{port}/refresh"
    headers = {"Host": f"{host}:{port}"}
    try:
        accepted = 0
        limited = 0
        for _ in range(8):
            req = urllib.request.Request(url, method="POST", headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if resp.status == HTTPStatus.ACCEPTED:
                        accepted += 1
            except urllib.error.HTTPError as exc:
                if exc.code == HTTPStatus.TOO_MANY_REQUESTS:
                    limited += 1
        assert accepted == 1
        assert limited >= 1
    finally:
        daemon.stop_polling()
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
    assert doc["meta"]["project"] == doc["project"]
    assert doc["meta"]["github"] == "never_run"
    assert doc["meta"]["ledger"] == "unavailable"
    assert all(n["status"] == "UNKNOWN" for n in doc["nodes"])


def test_mindmap_project_invalid_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MINDMAP_PROJECT", "NOT VALID!")
    name = resolve_project_name()
    assert PROJECT_NAME_RE.match(name)


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
    assert empty["meta"]["project"] == empty["project"]

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


@pytest.mark.parametrize(
    ("mode", "setup", "expect_error", "expect_cleared"),
    [
        ("path_missing", "missing", True, False),
        ("path_ok", "ok_file", False, True),
        ("path_read_fail", "unreadable", True, False),
        ("gh_not_found", "gh_404", True, False),
        ("gh_ok", "gh_ok", False, True),
    ],
)
def test_ledger_error_lifecycle(
    tmp_path: Path,
    bots: list[dict],
    mode: str,
    setup: str,
    expect_error: bool,
    expect_cleared: bool,
) -> None:
    ledger_path = tmp_path / "ledger.md"
    daemon = LiveDaemon(
        ledger_path=ledger_path,
        activity_path=tmp_path / "activity.json",
        static_dir=tmp_path,
        cache_dir=tmp_path / "cache",
        bots=bots,
        ledger_source="path" if setup != "gh_404" and setup != "gh_ok" else "gh",
        events_source="off",
    )
    if setup == "ok_file":
        ledger_path.write_text(LEDGER_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
        daemon.poll_ledger_once()
    elif setup == "unreadable":
        ledger_path.write_text("x", encoding="utf-8")
        ledger_path.chmod(0)
        try:
            daemon.poll_ledger_once()
        finally:
            ledger_path.chmod(0o644)
    elif setup == "gh_404":
        fetch = LedgerFetchResult(
            text=None, meta_ledger="not_found", errors=["ledger not found at data/ledger"]
        )
        with patch("ingest.live.fetch_ledger_from_gh", return_value=fetch):
            daemon.poll_ledger_once()
    elif setup == "gh_ok":
        text = LEDGER_FIXTURE.read_text(encoding="utf-8")
        fetch = LedgerFetchResult(text=text, meta_ledger="ok")
        with patch("ingest.live.fetch_ledger_from_gh", return_value=fetch):
            daemon.poll_ledger_once()
    else:
        daemon.poll_ledger_once()

    if expect_error:
        assert daemon._ledger_error
    if expect_cleared:
        assert daemon._ledger_error is None


def test_network_event_missing_ts_recorded_in_health(
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
    daemon.ingest_network_events(
        [
            {
                "id": "no-ts",
                "sender": "dev-1",
                "type": "message",
                "summary": "x",
                "provenance": "agent-reported",
            }
        ]
    )
    errs = daemon.health().errors
    assert any("no-ts" in e and "missing ts" in e for e in errs)
    assert network_event_to_activity_event(
        {
            "id": "no-ts",
            "summary": "x",
            "type": "message",
            "provenance": "agent-reported",
        },
        bots=bots,
    ) is None


def test_malformed_network_events_dropped_not_in_activity(
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
    daemon.ingest_network_events(
        [
            {"summary": "no id"},
            {
                "id": "ok-1",
                "ts": "2026-10-20T12:00:00+00:00",
                "sender": "dev-1",
                "recipients": ["dev-2"],
                "group": "build",
                "type": "message",
                "summary": "valid",
                "provenance": "agent-reported",
            },
        ]
    )
    assert daemon.maybe_rebuild(force=True)
    doc = json.loads(daemon.activity_path.read_text(encoding="utf-8"))
    ids = {e["id"] for e in doc["events"]}
    assert ids == {"ok-1"}


def test_message_edges_one_per_recipient(bots: list[dict]) -> None:
    from ingest.edges import derive_edges

    ne = {
        "id": "m2",
        "ts": "2026-10-20T12:00:00+00:00",
        "sender": "director",
        "recipients": ["architect", "dev-1"],
        "group": "build",
        "type": "message",
        "summary": "multi",
        "provenance": "agent-reported",
    }
    evt = network_event_to_activity_event(ne, bots=bots)
    assert evt is not None
    edges = derive_edges([evt])
    msg = [e for e in edges if e["type"] == "message"]
    assert len(msg) == 2
    targets = {e["target"] for e in msg}
    assert targets == {"architect", "dev-1"}


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
    assert not any(e["type"] == "message" for e in edges)
