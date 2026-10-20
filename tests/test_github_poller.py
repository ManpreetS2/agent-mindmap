"""MM-003: GitHub poller + signature attribution (mocked `gh api`, no network)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from ingest.attribute import attribute_from_body
from ingest.github_poller import (
    GhResponse,
    assert_no_credentials,
    poll_github,
)

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "github"
SCHEMA_PATH = ROOT / "schema" / "activity.schema.json"


def _load(name: str) -> Any:
    with (FIX / name).open(encoding="utf-8") as f:
        return json.load(f)


def _fixture_map() -> dict[str, Any]:
    return {
        "repos/ManpreetS2/fencepost/pulls?state=all&per_page=50": _load("fencepost_pulls.json"),
        "repos/ManpreetS2/agent-mindmap/pulls?state=all&per_page=50": _load(
            "agent_mindmap_pulls.json"
        ),
        "repos/ManpreetS2/fencepost/pulls/5/reviews": _load("pr5_reviews.json"),
        "repos/ManpreetS2/fencepost/pulls/5/comments": _load("pr5_comments.json"),
        "repos/ManpreetS2/fencepost/issues/5/comments": _load("pr5_issue_comments.json"),
        "repos/ManpreetS2/fencepost/pulls/5/commits": _load("pr5_commits.json"),
        "repos/ManpreetS2/fencepost/pulls/6/reviews": _load("pr6_reviews.json"),
        "repos/ManpreetS2/fencepost/pulls/6/comments": _load("pr6_comments.json"),
        "repos/ManpreetS2/fencepost/issues/6/comments": _load("pr6_issue_comments.json"),
        "repos/ManpreetS2/fencepost/pulls/6/commits": _load("pr6_commits.json"),
        "repos/ManpreetS2/fencepost/commits/aaa1111bbbbbbbccccccccdddddddddeeeeeeee/check-runs": _load(
            "check_runs_empty.json"
        ),
        "repos/ManpreetS2/fencepost/commits/bbb2222cccccccdddddddddeeeeeeeeffffffff/check-runs": _load(
            "check_runs_empty.json"
        ),
    }


class MockGh:
    """Recorded-fixture `gh api` runner with ETag / 304 behaviour."""

    def __init__(self, mapping: dict[str, Any] | None = None, *, fail: bool = False) -> None:
        self.mapping = mapping if mapping is not None else _fixture_map()
        self.fail = fail
        self.etags: dict[str, str] = {}
        self.calls: list[str] = []
        self.status_codes: list[int] = []

    def __call__(self, args: list[str], **_kwargs: Any) -> GhResponse:
        if self.fail:
            self.status_codes.append(0)
            return GhResponse(status=0, headers={}, body="gh: Not logged in (simulated)")

        path = args[-1]
        self.calls.append(path)
        if_none = None
        for i, a in enumerate(args):
            if a == "-H" and i + 1 < len(args) and args[i + 1].lower().startswith("if-none-match:"):
                if_none = args[i + 1].split(":", 1)[1].strip()

        if path not in self.mapping:
            self.status_codes.append(404)
            return GhResponse(
                status=404,
                headers={"x-ratelimit-remaining": "5000"},
                body='{"message":"Not Found"}',
            )

        etag = f'W/"{hash(path) & 0xFFFFFFFF:x}"'
        if if_none and path in self.etags and if_none == self.etags[path]:
            self.status_codes.append(304)
            return GhResponse(
                status=304,
                headers={"etag": etag, "x-ratelimit-remaining": "4990"},
                body="",
            )

        self.etags[path] = etag
        body = json.dumps(self.mapping[path])
        self.status_codes.append(200)
        return GhResponse(
            status=200,
            headers={"etag": etag, "x-ratelimit-remaining": "4980"},
            body=body,
        )


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    return tmp_path / "gh-cache"


def test_pr5_merged_with_sha_693ebc7(cache_dir: Path) -> None:
    result = poll_github(cache_dir=cache_dir, runner=MockGh())
    assert result.meta_github == "ok"
    merged = [e for e in result.events if e["type"] == "merged" and e.get("pr") == 5]
    assert len(merged) == 1
    assert merged[0]["sha"].startswith("693ebc7")
    assert merged[0]["sha"] == "693ebc7a1b2c3d4e5f60718293a4b5c6d7e8f901"
    assert merged[0]["task_id"] == "RP-005"
    assert "source_url" in merged[0] and "pull/5" in merged[0]["source_url"]
    assert merged[0]["source_time"]


def test_security_review_attributed_by_signature(cache_dir: Path) -> None:
    result = poll_github(cache_dir=cache_dir, runner=MockGh())
    security = [
        e
        for e in result.events
        if e.get("pr") == 6 and e["type"] == "verdict" and e.get("verdict") == "PASS"
    ]
    assert len(security) == 1
    assert security[0]["actor"] == "security-engineer"
    assert security[0]["attribution"]["method"] == "signature"
    assert "~Security Engineer" in security[0]["raw"]


def test_unsigned_comment_is_unknown(cache_dir: Path) -> None:
    result = poll_github(cache_dir=cache_dir, runner=MockGh())
    notes = [
        e
        for e in result.events
        if e.get("pr") == 6 and "Unsigned follow-up" in e.get("raw", "")
    ]
    assert len(notes) == 1
    assert notes[0]["actor"] is None
    assert notes[0]["attribution"]["method"] == "unknown"


def test_second_run_gets_304s(cache_dir: Path) -> None:
    mock = MockGh()
    first = poll_github(cache_dir=cache_dir, runner=mock)
    assert first.meta_github == "ok"
    assert first.status_304_count == 0
    assert first.request_count > 0

    second = poll_github(cache_dir=cache_dir, runner=mock)
    assert second.meta_github == "ok"
    assert second.status_304_count > 0
    assert second.status_304_count == second.request_count
    # Same merged event still present from cache
    merged = [e for e in second.events if e["type"] == "merged" and e.get("pr") == 5]
    assert len(merged) == 1
    assert merged[0]["sha"].startswith("693ebc7")


def test_output_contains_no_credentials(cache_dir: Path) -> None:
    result = poll_github(cache_dir=cache_dir, runner=MockGh())
    payload = {
        "meta": {"github": result.meta_github},
        "events": result.events,
        "errors": result.errors,
    }
    blob = json.dumps(payload)
    assert "ghp_" not in blob
    assert "gho_" not in blob
    assert "github_pat_" not in blob
    assert "GITHUB_TOKEN" not in blob
    assert "GH_TOKEN" not in blob
    assert "Authorization" not in blob
    assert_no_credentials(payload)


def test_gh_failure_sets_meta_github_error(cache_dir: Path) -> None:
    result = poll_github(cache_dir=cache_dir, runner=MockGh(fail=True))
    assert result.meta_github == "error"
    assert result.events == []


def test_events_conform_to_schema(cache_dir: Path) -> None:
    with SCHEMA_PATH.open(encoding="utf-8") as f:
        schema = json.load(f)
    result = poll_github(cache_dir=cache_dir, runner=MockGh())
    activity = {
        "schema_version": "1.0.0",
        "generated_at": "2026-10-20T05:00:00-07:00",
        "project": "fencepost",
        "meta": {"github": result.meta_github},
        "nodes": [],
        "tasks": [],
        "events": result.events,
        "edges": [],
        "unparsed": [],
    }
    jsonschema.validate(instance=activity, schema=schema)


def test_attribute_from_body_signature_helpers() -> None:
    bot_id, method = attribute_from_body("~Security Engineer 🔐 PASS")
    assert bot_id == "security-engineer"
    assert method == "signature"
    bot_id, method = attribute_from_body("no signature here")
    assert bot_id is None
    assert method == "unknown"
