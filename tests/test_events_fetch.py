"""MM-020c: gh events mirror fetch (ETag / base64 / missing branch / parse)."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from pathlib import Path

from ingest.events_fetch import (
    EVENTS_API_PATH,
    EVENTS_REF,
    EVENTS_REPO,
    EventsFetcher,
    fetch_events_from_gh,
    parse_events_jsonl,
)
from ingest.github_poller import GhResponse

NOW = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)


def _sample_event(
    eid: str = "evt-1",
    *,
    group: str = "build",
) -> dict:
    return {
        "id": eid,
        "ts": NOW.isoformat(),
        "sender": "dev-2",
        "group": group,
        "type": "message",
        "summary": "ping",
        "provenance": "agent-reported",
    }


def _jsonl(events: list[dict]) -> str:
    return "".join(json.dumps(e, sort_keys=True) + "\n" for e in events)


def _contents_body(text: str, *, sha: str = "abc") -> str:
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    wrapped = "\n".join(encoded[i : i + 60] for i in range(0, len(encoded), 60))
    return json.dumps(
        {
            "name": "events.jsonl",
            "path": "events.jsonl",
            "sha": sha,
            "size": len(text),
            "encoding": "base64",
            "content": (wrapped + "\n") if text else "",
        }
    )


class EventsMockGh:
    def __init__(
        self,
        *,
        status: int = 200,
        body: str = "",
        etag: str = '"etag-1"',
        fail: bool = False,
    ) -> None:
        self.status = status
        self.body = body
        self.etag = etag
        self.fail = fail
        self.calls: list[str] = []

    def __call__(self, args: list[str], *, timeout: float = 60.0) -> GhResponse:
        joined = " ".join(args)
        self.calls.append(joined)
        if self.fail:
            raise RuntimeError("boom")
        if EVENTS_API_PATH in joined or "contents/events.jsonl" in joined:
            return GhResponse(
                status=self.status,
                headers={"etag": self.etag},
                body=self.body,
            )
        return GhResponse(status=200, headers={}, body="{}")


def test_api_path_is_hardcoded_allowlist() -> None:
    assert EVENTS_API_PATH == (
        "repos/ManpreetS2/agent-mindmap/contents/events.jsonl?ref=data/events"
    )


def test_fetch_parse_with_mocked_gh(tmp_path: Path) -> None:
    text = _jsonl([_sample_event("a"), _sample_event("b", group="qr")])
    runner = EventsMockGh(status=200, body=_contents_body(text))
    events = fetch_events_from_gh(
        EVENTS_REPO,
        branch=EVENTS_REF,
        cache_dir=tmp_path / "cache",
        runner=runner,
    )
    assert [e["id"] for e in events] == ["a", "b"]
    assert events[1]["group"] == "qr"


def test_fetch_304_keeps_cache(tmp_path: Path) -> None:
    text = _jsonl([_sample_event("cached")])
    cache = tmp_path / "cache"
    first = EventsMockGh(status=200, body=_contents_body(text), etag='"e1"')
    r1 = EventsFetcher(cache_dir=cache, runner=first).fetch()
    assert r1.status == 200 and r1.events

    second = EventsMockGh(status=304, body="", etag='"e1"')
    r2 = EventsFetcher(cache_dir=cache, runner=second).fetch()
    assert r2.meta_events == "ok"
    assert r2.status == 304
    assert r2.from_cache is True
    assert [e["id"] for e in r2.events] == ["cached"]
    assert any("If-None-Match" in c for c in second.calls)


def test_missing_branch_returns_empty(tmp_path: Path) -> None:
    runner = EventsMockGh(status=404, body="Not Found")
    events = fetch_events_from_gh(
        EVENTS_REPO,
        branch=EVENTS_REF,
        cache_dir=tmp_path / "cache",
        runner=runner,
    )
    assert events == []
    result = EventsFetcher(cache_dir=tmp_path / "cache2", runner=runner).fetch()
    assert result.meta_events == "missing"
    assert result.events == []


def test_unknown_group_passthrough_no_throw() -> None:
    text = _jsonl([_sample_event("u1", group="brand-new-squad")])
    events = parse_events_jsonl(text)
    assert len(events) == 1
    assert events[0]["group"] == "brand-new-squad"


def test_parse_skips_invalid_lines() -> None:
    text = (
        "{bad\n"
        + json.dumps(_sample_event("ok")) + "\n"
        + json.dumps({"id": "nope"}) + "\n"
    )
    events = parse_events_jsonl(text)
    assert [e["id"] for e in events] == ["ok"]


def test_non_allowlisted_repo_returns_empty(tmp_path: Path) -> None:
    runner = EventsMockGh(status=200, body=_contents_body(_jsonl([_sample_event()])))
    events = fetch_events_from_gh(
        "evil/other",
        branch=EVENTS_REF,
        cache_dir=tmp_path / "cache",
        runner=runner,
    )
    assert events == []
    assert runner.calls == []  # refused before gh


def test_empty_file_ok(tmp_path: Path) -> None:
    runner = EventsMockGh(status=200, body=_contents_body(""))
    events = fetch_events_from_gh(
        EVENTS_REPO,
        branch="data/events",
        cache_dir=tmp_path / "cache",
        runner=runner,
    )
    assert events == []
