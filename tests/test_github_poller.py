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
    next_link_path,
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
        "repos/ManpreetS2/fencepost/pulls?state=all&per_page=100": _load("fencepost_pulls.json"),
        "repos/ManpreetS2/agent-mindmap/pulls?state=all&per_page=100": _load(
            "agent_mindmap_pulls.json"
        ),
        "repos/ManpreetS2/fencepost/pulls/5/reviews?per_page=100": _load("pr5_reviews.json"),
        "repos/ManpreetS2/fencepost/pulls/5/comments?per_page=100": _load("pr5_comments.json"),
        "repos/ManpreetS2/fencepost/issues/5/comments?per_page=100": _load(
            "pr5_issue_comments.json"
        ),
        "repos/ManpreetS2/fencepost/pulls/5/commits?per_page=100": _load("pr5_commits.json"),
        "repos/ManpreetS2/fencepost/pulls/6/reviews?per_page=100": _load("pr6_reviews.json"),
        "repos/ManpreetS2/fencepost/pulls/6/comments?per_page=100": _load("pr6_comments.json"),
        "repos/ManpreetS2/fencepost/issues/6/comments?per_page=100": _load(
            "pr6_issue_comments.json"
        ),
        "repos/ManpreetS2/fencepost/pulls/6/commits?per_page=100": _load("pr6_commits.json"),
        "repos/ManpreetS2/fencepost/commits/aaa1111bbbbbbbccccccccdddddddddeeeeeeee/check-runs": _load(
            "check_runs_empty.json"
        ),
        "repos/ManpreetS2/fencepost/commits/bbb2222cccccccdddddddddeeeeeeeeffffffff/check-runs": _load(
            "check_runs_empty.json"
        ),
    }


class MockGh:
    """Recorded-fixture `gh api` runner with ETag / 304 / Link / status overrides."""

    def __init__(
        self,
        mapping: dict[str, Any] | None = None,
        *,
        fail: bool = False,
        links: dict[str, str] | None = None,
        status_for: dict[str, int] | None = None,
        remaining_for: dict[str, str] | None = None,
        default_remaining: str = "4980",
    ) -> None:
        self.mapping = mapping if mapping is not None else _fixture_map()
        self.fail = fail
        self.links = links or {}
        self.status_for = status_for or {}
        self.remaining_for = remaining_for or {}
        self.default_remaining = default_remaining
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
            if a == "-H" and i + 1 < len(args) and args[i + 1].lower().startswith(
                "if-none-match:"
            ):
                if_none = args[i + 1].split(":", 1)[1].strip()

        status = self.status_for.get(path, 200)
        remaining = self.remaining_for.get(path, self.default_remaining)

        if status in (403, 429, 500, 502, 503) and path not in self.mapping:
            self.status_codes.append(status)
            body = (
                '{"message":"API rate limit exceeded"}'
                if status in (403, 429)
                else '{"message":"server error"}'
            )
            headers = {"x-ratelimit-remaining": remaining}
            if status in (403, 429) and remaining == "0":
                headers["x-ratelimit-remaining"] = "0"
            return GhResponse(status=status, headers=headers, body=body)

        if path not in self.mapping:
            self.status_codes.append(404)
            return GhResponse(
                status=404,
                headers={"x-ratelimit-remaining": "5000"},
                body='{"message":"Not Found"}',
            )

        etag = f'W/"{hash(path) & 0xFFFFFFFF:x}"'
        if if_none and path in self.etags and if_none == self.etags[path] and status == 200:
            self.status_codes.append(304)
            return GhResponse(
                status=304,
                headers={"etag": etag, "x-ratelimit-remaining": "4990"},
                body="",
            )

        if status >= 400:
            self.status_codes.append(status)
            headers = {"x-ratelimit-remaining": remaining, "etag": etag}
            if path in self.links:
                headers["link"] = self.links[path]
            body = (
                '{"message":"API rate limit exceeded"}'
                if status in (403, 429)
                else '{"message":"server error"}'
            )
            return GhResponse(status=status, headers=headers, body=body)

        self.etags[path] = etag
        body = json.dumps(self.mapping[path])
        self.status_codes.append(200)
        headers = {"etag": etag, "x-ratelimit-remaining": remaining}
        if path in self.links:
            headers["link"] = self.links[path]
        return GhResponse(status=200, headers=headers, body=body)


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    return tmp_path / "gh-cache"


def test_pr5_merged_with_sha_693ebc7(cache_dir: Path) -> None:
    result = poll_github(cache_dir=cache_dir, runner=MockGh())
    assert result.meta_github == "ok"
    merged = [e for e in result.events if e["type"] == "merged" and e.get("pr") == 5]
    assert len(merged) == 1
    assert merged[0]["sha"].startswith("693ebc7")
    assert merged[0]["task_id"] == "RP-005"
    assert "pull/5" in merged[0]["source_url"]


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


def test_unsigned_comment_is_unknown(cache_dir: Path) -> None:
    result = poll_github(cache_dir=cache_dir, runner=MockGh())
    notes = [
        e
        for e in result.events
        if e.get("pr") == 6 and "Unsigned follow-up" in e.get("raw", "")
    ]
    assert len(notes) == 1
    assert notes[0]["attribution"]["method"] == "unknown"


def test_second_run_gets_304s(cache_dir: Path) -> None:
    mock = MockGh()
    first = poll_github(cache_dir=cache_dir, runner=mock)
    assert first.meta_github == "ok"
    assert first.status_304_count == 0

    second = poll_github(cache_dir=cache_dir, runner=mock)
    assert second.meta_github == "ok"
    assert second.status_304_count == second.request_count
    merged = [e for e in second.events if e["type"] == "merged" and e.get("pr") == 5]
    assert len(merged) == 1


def test_output_contains_no_credentials(cache_dir: Path) -> None:
    result = poll_github(cache_dir=cache_dir, runner=MockGh())
    payload = {"meta": {"github": result.meta_github}, "events": result.events}
    blob = json.dumps(payload)
    assert "ghp_" not in blob
    assert "GITHUB_TOKEN" not in blob
    assert "Authorization" not in blob
    assert_no_credentials(payload)


def test_gh_failure_sets_meta_github_error(cache_dir: Path) -> None:
    result = poll_github(cache_dir=cache_dir, runner=MockGh(fail=True))
    assert result.meta_github == "error"
    assert result.events == []


def test_rate_limited_when_remaining_under_floor(cache_dir: Path) -> None:
    """QA-MM003-1: remaining < 50 → meta.github = rate_limited."""
    pulls = "repos/ManpreetS2/fencepost/pulls?state=all&per_page=100"
    mock = MockGh(remaining_for={pulls: "49"})
    result = poll_github(
        cache_dir=cache_dir,
        runner=mock,
        repos=("ManpreetS2/fencepost",),
    )
    assert result.meta_github == "rate_limited"
    assert any(e.get("pr") == 5 and e["type"] == "merged" for e in result.events)


def test_rate_limited_on_403_rate_limit(cache_dir: Path) -> None:
    pulls = "repos/ManpreetS2/fencepost/pulls?state=all&per_page=100"
    mapping = {
        pulls: _load("fencepost_pulls.json"),
        "repos/ManpreetS2/fencepost/pulls/5/reviews?per_page=100": _load("pr5_reviews.json"),
    }
    mock = MockGh(
        mapping=mapping,
        status_for={"repos/ManpreetS2/fencepost/pulls/5/reviews?per_page=100": 403},
        remaining_for={"repos/ManpreetS2/fencepost/pulls/5/reviews?per_page=100": "0"},
    )
    result = poll_github(
        cache_dir=cache_dir,
        runner=mock,
        repos=("ManpreetS2/fencepost",),
    )
    assert result.meta_github == "rate_limited"


def test_paginate_reviews_over_thirty_items(cache_dir: Path) -> None:
    """QA-MM003-2: follow Link rel=next; collect >30 review items."""
    page1 = [
        {
            "id": i,
            "body": f"review {i}",
            "html_url": f"https://github.com/ManpreetS2/fencepost/pull/5#pullrequestreview-{i}",
            "submitted_at": "2026-10-19T21:00:00-07:00",
            "state": "COMMENTED",
            "user": {"login": "ManpreetS2"},
        }
        for i in range(1, 31)
    ]
    page2 = [
        {
            "id": i,
            "body": f"review {i}",
            "html_url": f"https://github.com/ManpreetS2/fencepost/pull/5#pullrequestreview-{i}",
            "submitted_at": "2026-10-19T21:01:00-07:00",
            "state": "COMMENTED",
            "user": {"login": "ManpreetS2"},
        }
        for i in range(31, 36)
    ]
    p1 = "repos/ManpreetS2/fencepost/pulls/5/reviews?per_page=100"
    p2 = "repos/ManpreetS2/fencepost/pulls/5/reviews?per_page=100&page=2"
    mapping = {
        "repos/ManpreetS2/fencepost/pulls?state=all&per_page=100": [
            {
                "number": 5,
                "title": "feat/RP-005-ingest-hardening",
                "body": "~DEV 1 ⚙️",
                "html_url": "https://github.com/ManpreetS2/fencepost/pull/5",
                "created_at": "2026-10-19T21:35:00-07:00",
                "merged_at": None,
                "merge_commit_sha": None,
                "head": {"ref": "feat/RP-005-ingest-hardening", "sha": "aaa"},
                "user": {"login": "ManpreetS2"},
            }
        ],
        p1: page1,
        p2: page2,
        "repos/ManpreetS2/fencepost/pulls/5/comments?per_page=100": [],
        "repos/ManpreetS2/fencepost/issues/5/comments?per_page=100": [],
        "repos/ManpreetS2/fencepost/pulls/5/commits?per_page=100": [],
    }
    link = (
        f'<https://api.github.com/{p2}>; rel="next", '
        f'<https://api.github.com/{p1}>; rel="prev"'
    )
    mock = MockGh(mapping=mapping, links={p1: link})
    result = poll_github(
        cache_dir=cache_dir,
        runner=mock,
        repos=("ManpreetS2/fencepost",),
    )
    review_notes = [
        e for e in result.events if e.get("pr") == 5 and e["raw"].startswith("review ")
    ]
    assert len(review_notes) == 35
    assert p2 in mock.calls
    assert next_link_path(link) == p2


def test_subresource_5xx_sets_error_keeps_partial(cache_dir: Path) -> None:
    """QA-MM003-3: sub-resource 5xx → meta.error while keeping earlier events."""
    mapping = _fixture_map()
    # Drop agent-mindmap to keep the run focused on fencepost.
    mapping = {k: v for k, v in mapping.items() if "agent-mindmap" not in k}
    reviews = "repos/ManpreetS2/fencepost/pulls/6/reviews?per_page=100"
    mock = MockGh(mapping=mapping, status_for={reviews: 503})
    result = poll_github(
        cache_dir=cache_dir,
        runner=mock,
        repos=("ManpreetS2/fencepost",),
    )
    assert result.meta_github == "error"
    assert any(e.get("pr") == 5 and e["type"] == "merged" for e in result.events)
    assert any(e.get("pr") == 6 and e["type"] == "pr_opened" for e in result.events)
    # Security review from PR #6 should be missing because reviews 5xx'd
    assert not any(
        e.get("pr") == 6 and e["type"] == "verdict" and e.get("verdict") == "PASS"
        for e in result.events
    )


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


def test_schema_allows_rate_limited_meta() -> None:
    with SCHEMA_PATH.open(encoding="utf-8") as f:
        schema = json.load(f)
    activity = {
        "schema_version": "1.0.0",
        "generated_at": "2026-10-20T05:00:00-07:00",
        "project": "fencepost",
        "meta": {"github": "rate_limited"},
        "nodes": [],
        "tasks": [],
        "events": [],
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


def test_next_link_path_helper() -> None:
    link = (
        '<https://api.github.com/repos/ManpreetS2/fencepost/pulls?page=2&per_page=100>; '
        'rel="next"'
    )
    assert next_link_path(link) == (
        "repos/ManpreetS2/fencepost/pulls?page=2&per_page=100"
    )
