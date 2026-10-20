"""MM-003: GitHub poller + signature attribution (mocked `gh api`, no network)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from ingest.attribute import attribute_from_body
from ingest.github_poller import (
    MAX_PAGES,
    MAX_PRS,
    GhResponse,
    PaginationLinkError,
    assert_no_credentials,
    next_link_path,
    poll_github,
)

FENCEPOST_REPO_ID = 111001
AGENT_MINDMAP_REPO_ID = 111002

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "github"
SCHEMA_PATH = ROOT / "schema" / "activity.schema.json"


def _load(name: str) -> Any:
    with (FIX / name).open(encoding="utf-8") as f:
        return json.load(f)


def _fixture_map() -> dict[str, Any]:
    return {
        "repos/ManpreetS2/fencepost": {
            "id": FENCEPOST_REPO_ID,
            "full_name": "ManpreetS2/fencepost",
        },
        "repos/ManpreetS2/agent-mindmap": {
            "id": AGENT_MINDMAP_REPO_ID,
            "full_name": "ManpreetS2/agent-mindmap",
        },
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
        "repos/ManpreetS2/fencepost/commits/693ebc7a1b2c3d4e5f60718293a4b5c6d7e8f901/check-runs": _load(
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


def test_security_review_actor_from_github_login(cache_dir: Path) -> None:
    """SEC-MM020e-2: review actor from user.login, not ~Bot signature in body."""
    result = poll_github(cache_dir=cache_dir, runner=MockGh())
    security = [
        e
        for e in result.events
        if e.get("pr") == 6 and e["type"] == "verdict" and e.get("verdict") == "PASS"
    ]
    assert len(security) == 1
    assert security[0]["actor"] == "manpreet"
    assert security[0]["attribution"]["method"] == "github_login"
    assert security[0]["provenance"] == "github-verified"


def test_unsigned_comment_is_unknown(cache_dir: Path) -> None:
    result = poll_github(cache_dir=cache_dir, runner=MockGh())
    notes = [
        e
        for e in result.events
        if e.get("pr") == 6 and "Unsigned follow-up" in e.get("raw", "")
    ]
    assert len(notes) == 1
    assert notes[0]["attribution"]["method"] == "github_login"


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
        "repos/ManpreetS2/fencepost": {
            "id": FENCEPOST_REPO_ID,
            "full_name": "ManpreetS2/fencepost",
        },
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
        "repos/ManpreetS2/fencepost": {
            "id": FENCEPOST_REPO_ID,
            "full_name": "ManpreetS2/fencepost",
        },
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
    # Realistic GitHub Link uses /repositories/<id>/
    link_id = (
        f'<https://api.github.com/repositories/{FENCEPOST_REPO_ID}/pulls/5/reviews?page=2>; '
        'rel="next"'
    )
    assert next_link_path(
        link_id, allowed_repo_ids=frozenset({FENCEPOST_REPO_ID})
    ) == (f"repositories/{FENCEPOST_REPO_ID}/pulls/5/reviews?page=2")


def test_next_link_rejects_foreign_host() -> None:
    link = '<https://evil.example/repos/ManpreetS2/fencepost/pulls?page=2>; rel="next"'
    with pytest.raises(PaginationLinkError, match="host"):
        next_link_path(link)


def test_next_link_rejects_foreign_repo() -> None:
    link = (
        '<https://api.github.com/repos/OtherOrg/other-repo/pulls?page=2>; rel="next"'
    )
    with pytest.raises(PaginationLinkError, match="repo"):
        next_link_path(link)
    with pytest.raises(PaginationLinkError, match="repository id"):
        next_link_path(
            '<https://api.github.com/repositories/999999/pulls?page=2>; rel="next"',
            allowed_repo_ids=frozenset({FENCEPOST_REPO_ID}),
        )


def test_next_link_rejects_dotdot_and_percent() -> None:
    with pytest.raises(PaginationLinkError, match="unsafe"):
        next_link_path(
            '<https://api.github.com/repos/ManpreetS2/fencepost/../evil>; rel="next"'
        )
    with pytest.raises(PaginationLinkError, match="unsafe"):
        next_link_path(
            '<https://api.github.com/repos/ManpreetS2/fencepost/pulls?page=2%2F3>; '
            'rel="next"'
        )


def test_next_link_rejects_mismatched_resource() -> None:
    link = (
        f'<https://api.github.com/repositories/{FENCEPOST_REPO_ID}/pulls/6/reviews?page=2>; '
        'rel="next"'
    )
    with pytest.raises(PaginationLinkError, match="resource"):
        next_link_path(
            link,
            allowed_repo_ids=frozenset({FENCEPOST_REPO_ID}),
            expected_suffix="pulls/5/reviews",
        )


def test_failed_repo_id_lookup_sets_error(cache_dir: Path) -> None:
    """Failed GET repos/{owner}/{repo} → meta.github=error; no head.repo fallback."""
    mapping = {
        # Missing repos/ManpreetS2/fencepost metadata on purpose.
        "repos/ManpreetS2/fencepost/pulls?state=all&per_page=100": [
            {
                "number": 5,
                "title": "feat/RP-005",
                "body": "~DEV 1 ⚙️",
                "html_url": "https://github.com/ManpreetS2/fencepost/pull/5",
                "created_at": "2026-10-19T21:35:00-07:00",
                "merged_at": None,
                "merge_commit_sha": None,
                # head.repo must NOT be used as a fallback
                "head": {
                    "ref": "feat/RP-005",
                    "sha": "aaa",
                    "repo": {"id": FENCEPOST_REPO_ID, "full_name": "ManpreetS2/fencepost"},
                },
                "user": {"login": "ManpreetS2"},
            }
        ],
    }
    result = poll_github(
        cache_dir=cache_dir,
        runner=MockGh(mapping=mapping),
        repos=("ManpreetS2/fencepost",),
    )
    assert result.meta_github == "error"
    assert any("failed to resolve numeric id" in e for e in result.errors)
    assert result.events == []


def _single_pr_mapping() -> dict[str, Any]:
    return {
        "repos/ManpreetS2/fencepost": {
            "id": FENCEPOST_REPO_ID,
            "full_name": "ManpreetS2/fencepost",
        },
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
                "base": {
                    "repo": {"id": FENCEPOST_REPO_ID, "full_name": "ManpreetS2/fencepost"}
                },
                "user": {"login": "ManpreetS2"},
            }
        ],
        "repos/ManpreetS2/fencepost/pulls/5/comments?per_page=100": [],
        "repos/ManpreetS2/fencepost/issues/5/comments?per_page=100": [],
        "repos/ManpreetS2/fencepost/pulls/5/commits?per_page=100": [],
    }


def test_foreign_host_link_stops_pagination_sets_error(cache_dir: Path) -> None:
    """SEC-MM003-1: evil Link host → stop + meta.github=error; keep page-1 data."""
    p1 = "repos/ManpreetS2/fencepost/pulls/5/reviews?per_page=100"
    mapping = _single_pr_mapping()
    mapping[p1] = [
        {
            "id": 1,
            "body": "page1 review",
            "html_url": "https://github.com/ManpreetS2/fencepost/pull/5#pullrequestreview-1",
            "submitted_at": "2026-10-19T21:00:00-07:00",
            "state": "COMMENTED",
            "user": {"login": "ManpreetS2"},
        }
    ]
    mock = MockGh(
        mapping=mapping,
        links={p1: '<https://evil.example/repos/ManpreetS2/fencepost/pulls/5/reviews?page=2>; rel="next"'},
    )
    result = poll_github(
        cache_dir=cache_dir,
        runner=mock,
        repos=("ManpreetS2/fencepost",),
    )
    assert result.meta_github == "error"
    assert any("page1 review" in e.get("raw", "") for e in result.events)
    assert not any("evil.example" in c for c in mock.calls)


def test_foreign_repo_link_stops_pagination_sets_error(cache_dir: Path) -> None:
    """SEC-MM003-1: Link to non-allowlisted repo → stop + meta.github=error."""
    p1 = "repos/ManpreetS2/fencepost/pulls/5/reviews?per_page=100"
    mapping = _single_pr_mapping()
    mapping[p1] = [
        {
            "id": 1,
            "body": "ok review",
            "html_url": "https://github.com/ManpreetS2/fencepost/pull/5#pullrequestreview-1",
            "submitted_at": "2026-10-19T21:00:00-07:00",
            "state": "COMMENTED",
            "user": {"login": "ManpreetS2"},
        }
    ]
    mock = MockGh(
        mapping=mapping,
        links={
            p1: (
                '<https://api.github.com/repos/OtherOrg/other-repo/pulls/1/reviews?page=2>; '
                'rel="next"'
            )
        },
    )
    result = poll_github(
        cache_dir=cache_dir,
        runner=mock,
        repos=("ManpreetS2/fencepost",),
    )
    assert result.meta_github == "error"
    assert any("ok review" in e.get("raw", "") for e in result.events)
    assert not any("OtherOrg" in c for c in mock.calls)


def test_next_link_rejects_sibling_allowlisted_repo() -> None:
    """QA-MM003-12: next must stay in the *same* repo, not any allowlisted one."""
    link = (
        '<https://api.github.com/repos/ManpreetS2/agent-mindmap/pulls?page=2>; '
        'rel="next"'
    )
    with pytest.raises(PaginationLinkError, match="repo"):
        next_link_path(
            link,
            allowed_repos=frozenset({"ManpreetS2/fencepost"}),
            allowed_repo_ids=frozenset({FENCEPOST_REPO_ID}),
        )
    with pytest.raises(PaginationLinkError, match="repository id"):
        next_link_path(
            f'<https://api.github.com/repositories/{AGENT_MINDMAP_REPO_ID}/pulls?page=2>; '
            'rel="next"',
            allowed_repos=frozenset({"ManpreetS2/fencepost"}),
            allowed_repo_ids=frozenset({FENCEPOST_REPO_ID}),
        )


def test_sibling_allowlisted_repo_link_stops_pagination(cache_dir: Path) -> None:
    """QA-MM003-12: paging fencepost must refuse a next link into agent-mindmap."""
    p1 = "repos/ManpreetS2/fencepost/pulls/5/reviews?per_page=100"
    mapping = _single_pr_mapping()
    mapping[p1] = [
        {
            "id": 1,
            "body": "stay on fencepost",
            "html_url": "https://github.com/ManpreetS2/fencepost/pull/5#pullrequestreview-1",
            "submitted_at": "2026-10-19T21:00:00-07:00",
            "state": "COMMENTED",
            "user": {"login": "ManpreetS2"},
        }
    ]
    mock = MockGh(
        mapping=mapping,
        links={
            p1: (
                '<https://api.github.com/repos/ManpreetS2/agent-mindmap/pulls/1/reviews?page=2>; '
                'rel="next"'
            )
        },
    )
    result = poll_github(
        cache_dir=cache_dir,
        runner=mock,
        repos=("ManpreetS2/fencepost",),
    )
    assert result.meta_github == "error"
    assert any("stay on fencepost" in e.get("raw", "") for e in result.events)
    assert not any("agent-mindmap" in c and "reviews?page=2" in c for c in mock.calls)


def test_merged_by_login_maps_merger_to_bot(cache_dir: Path) -> None:
    """MM-020e2: merged actor from PR merged_by.login (bot mapping)."""
    result = poll_github(cache_dir=cache_dir, runner=MockGh())
    merged = [e for e in result.events if e["type"] == "merged" and e.get("pr") == 5]
    assert len(merged) == 1
    assert merged[0]["actor"] == "manpreet"
    assert merged[0]["attribution"]["method"] == "github_login"
    assert merged[0]["provenance"] == "github-verified"
    assert merged[0]["repo"] == "ManpreetS2/fencepost"
    opened = [e for e in result.events if e["type"] == "pr_opened" and e.get("pr") == 5]
    assert opened[0]["actor"] == "manpreet"
    assert opened[0]["attribution"]["method"] == "github_login"


def test_merged_without_merged_by_is_agent_reported_unknown(cache_dir: Path) -> None:
    mapping = _single_pr_mapping()
    mapping["repos/ManpreetS2/fencepost/pulls?state=all&per_page=100"] = [
        {
            "number": 5,
            "title": "feat/RP-005-ingest-hardening",
            "body": "~DEV 1 ⚙️",
            "html_url": "https://github.com/ManpreetS2/fencepost/pull/5",
            "created_at": "2026-10-19T21:35:00-07:00",
            "merged_at": "2026-10-19T21:39:00-07:00",
            "merge_commit_sha": "693ebc7a1b2c3d4e5f60718293a4b5c6d7e8f901",
            "head": {"ref": "feat/RP-005-ingest-hardening", "sha": "aaa"},
            "base": {
                "repo": {"id": FENCEPOST_REPO_ID, "full_name": "ManpreetS2/fencepost"}
            },
            "user": {"login": "ManpreetS2"},
        }
    ]
    mapping["repos/ManpreetS2/fencepost/pulls/5/commits?per_page=100"] = []
    result = poll_github(
        cache_dir=cache_dir,
        runner=MockGh(mapping=mapping),
        repos=("ManpreetS2/fencepost",),
    )
    merged = [e for e in result.events if e["type"] == "merged" and e.get("pr") == 5]
    assert len(merged) == 1
    assert merged[0]["actor"] is None
    assert merged[0]["provenance"] == "agent-reported"
    assert merged[0]["attribution"]["method"] == "unknown"


def test_merged_squash_sha_absent_from_commits_uses_merged_by(cache_dir: Path) -> None:
    """Squash merge SHAs are often missing from /pulls/N/commits."""
    mapping = _single_pr_mapping()
    mapping["repos/ManpreetS2/fencepost/pulls?state=all&per_page=100"] = [
        {
            "number": 5,
            "title": "feat/RP-005-ingest-hardening",
            "body": "~DEV 1 ⚙️",
            "html_url": "https://github.com/ManpreetS2/fencepost/pull/5",
            "created_at": "2026-10-19T21:35:00-07:00",
            "merged_at": "2026-10-19T21:39:00-07:00",
            "merge_commit_sha": "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
            "merged_by": {"login": "ManpreetS2"},
            "head": {"ref": "feat/RP-005-ingest-hardening", "sha": "aaa"},
            "base": {
                "repo": {"id": FENCEPOST_REPO_ID, "full_name": "ManpreetS2/fencepost"}
            },
            "user": {"login": "ManpreetS2"},
        }
    ]
    mapping["repos/ManpreetS2/fencepost/pulls/5/commits?per_page=100"] = []
    mapping[
        "repos/ManpreetS2/fencepost/commits/deadbeefdeadbeefdeadbeefdeadbeefdeadbeef/check-runs"
    ] = _load("check_runs_empty.json")
    result = poll_github(
        cache_dir=cache_dir,
        runner=MockGh(mapping=mapping),
        repos=("ManpreetS2/fencepost",),
    )
    merged = [e for e in result.events if e["type"] == "merged" and e.get("pr") == 5]
    assert len(merged) == 1
    assert merged[0]["actor"] == "manpreet"
    assert merged[0]["provenance"] == "github-verified"


def test_merged_by_unmapped_login_is_agent_reported(cache_dir: Path) -> None:
    mapping = _single_pr_mapping()
    mapping["repos/ManpreetS2/fencepost/pulls?state=all&per_page=100"] = [
        {
            "number": 5,
            "title": "feat/RP-005-ingest-hardening",
            "body": "~DEV 1 ⚙️",
            "html_url": "https://github.com/ManpreetS2/fencepost/pull/5",
            "created_at": "2026-10-19T21:35:00-07:00",
            "merged_at": "2026-10-19T21:39:00-07:00",
            "merge_commit_sha": "693ebc7a1b2c3d4e5f60718293a4b5c6d7e8f901",
            "merged_by": {"login": "dependabot[bot]"},
            "head": {"ref": "feat/RP-005-ingest-hardening", "sha": "aaa"},
            "base": {
                "repo": {"id": FENCEPOST_REPO_ID, "full_name": "ManpreetS2/fencepost"}
            },
            "user": {"login": "ManpreetS2"},
        }
    ]
    mapping["repos/ManpreetS2/fencepost/pulls/5/commits?per_page=100"] = []
    result = poll_github(
        cache_dir=cache_dir,
        runner=MockGh(mapping=mapping),
        repos=("ManpreetS2/fencepost",),
    )
    merged = [e for e in result.events if e["type"] == "merged" and e.get("pr") == 5]
    assert len(merged) == 1
    assert merged[0]["actor"] is None
    assert merged[0]["provenance"] == "agent-reported"
    assert merged[0]["attribution"]["method"] == "github_login_unmapped"


def test_ledger_style_merge_note_does_not_infer_merger_from_signature(cache_dir: Path) -> None:
    """SEC-MM020e-2: ~Bot signature in merge note does not set actor (login only)."""
    mapping = _single_pr_mapping()
    mapping["repos/ManpreetS2/fencepost/pulls?state=all&per_page=100"] = [
        {
            "number": 5,
            "title": "feat/RP-005-ingest-hardening",
            "body": "~DEV 1 ⚙️",
            "html_url": "https://github.com/ManpreetS2/fencepost/pull/5",
            "created_at": "2026-10-19T21:35:00-07:00",
            "merged_at": "2026-10-19T21:39:00-07:00",
            "merge_commit_sha": "693ebc7a1b2c3d4e5f60718293a4b5c6d7e8f901",
            "merged_by": {"login": "ManpreetS2"},
            "head": {"ref": "feat/RP-005-ingest-hardening", "sha": "aaa"},
            "base": {
                "repo": {"id": FENCEPOST_REPO_ID, "full_name": "ManpreetS2/fencepost"}
            },
            "user": {"login": "ManpreetS2"},
        }
    ]
    mapping["repos/ManpreetS2/fencepost/pulls/5/reviews?per_page=100"] = []
    mapping["repos/ManpreetS2/fencepost/issues/5/comments?per_page=100"] = [
        {
            "id": 9001,
            "body": "squash-merged as 693ebc7\n\n~DevOps / Release 🚀",
            "html_url": "https://github.com/ManpreetS2/fencepost/pull/5#issuecomment-9001",
            "created_at": "2026-10-19T21:39:01-07:00",
            "user": {"login": "ManpreetS2"},
        }
    ]
    mapping["repos/ManpreetS2/fencepost/pulls/5/commits?per_page=100"] = [
        {
            "sha": "693ebc7a1b2c3d4e5f60718293a4b5c6d7e8f901",
            "author": {"login": "ManpreetS2"},
            "commit": {
                "message": "squash merge",
                "author": {"date": "2026-10-19T21:39:00-07:00"},
            },
        }
    ]
    mapping[
        "repos/ManpreetS2/fencepost/commits/693ebc7a1b2c3d4e5f60718293a4b5c6d7e8f901/check-runs"
    ] = _load("check_runs_empty.json")
    result = poll_github(
        cache_dir=cache_dir,
        runner=MockGh(mapping=mapping),
        repos=("ManpreetS2/fencepost",),
    )
    merged = [e for e in result.events if e["type"] == "merged" and e.get("pr") == 5]
    assert len(merged) == 1
    assert merged[0]["actor"] == "manpreet"
    assert merged[0]["attribution"]["method"] == "github_login"
    assert merged[0]["actor"] != "devops-release"


def test_merge_hint_alone_does_not_attribute_merger(cache_dir: Path) -> None:
    """SEC-MM020e-2: casual merge hint + ~Bot does not infer merger from body."""
    mapping = _single_pr_mapping()
    mapping["repos/ManpreetS2/fencepost/pulls?state=all&per_page=100"] = [
        {
            "number": 5,
            "title": "feat/RP-005-ingest-hardening",
            "body": "~DEV 1 ⚙️",
            "html_url": "https://github.com/ManpreetS2/fencepost/pull/5",
            "created_at": "2026-10-19T21:35:00-07:00",
            "merged_at": "2026-10-19T21:39:00-07:00",
            "merge_commit_sha": "693ebc7a1b2c3d4e5f60718293a4b5c6d7e8f901",
            "merged_by": {"login": "ManpreetS2"},
            "head": {"ref": "feat/RP-005-ingest-hardening", "sha": "aaa"},
            "base": {
                "repo": {"id": FENCEPOST_REPO_ID, "full_name": "ManpreetS2/fencepost"}
            },
            "user": {"login": "ManpreetS2"},
        }
    ]
    mapping["repos/ManpreetS2/fencepost/pulls/5/reviews?per_page=100"] = []
    mapping["repos/ManpreetS2/fencepost/issues/5/comments?per_page=100"] = [
        {
            "id": 9002,
            "body": "Looks merged to me — ship it.\n\n~DevOps / Release 🚀",
            "html_url": "https://github.com/ManpreetS2/fencepost/pull/5#issuecomment-9002",
            "created_at": "2026-10-19T21:39:01-07:00",
            "user": {"login": "ManpreetS2"},
        }
    ]
    mapping["repos/ManpreetS2/fencepost/pulls/5/commits?per_page=100"] = [
        {
            "sha": "693ebc7a1b2c3d4e5f60718293a4b5c6d7e8f901",
            "author": {"login": "ManpreetS2"},
            "commit": {
                "message": "squash merge",
                "author": {"date": "2026-10-19T21:39:00-07:00"},
            },
        }
    ]
    mapping[
        "repos/ManpreetS2/fencepost/commits/693ebc7a1b2c3d4e5f60718293a4b5c6d7e8f901/check-runs"
    ] = _load("check_runs_empty.json")
    result = poll_github(
        cache_dir=cache_dir,
        runner=MockGh(mapping=mapping),
        repos=("ManpreetS2/fencepost",),
    )
    merged = [e for e in result.events if e["type"] == "merged" and e.get("pr") == 5]
    assert len(merged) == 1
    assert merged[0]["actor"] == "manpreet"
    assert merged[0]["attribution"]["method"] == "github_login"
    assert merged[0]["actor"] != "devops-release"


def test_repositories_numeric_id_link_pagination(cache_dir: Path) -> None:
    """QA-MM003-9: follow realistic /repositories/<id>/ Link headers."""
    p1 = "repos/ManpreetS2/fencepost/pulls/5/reviews?per_page=100"
    p2 = f"repositories/{FENCEPOST_REPO_ID}/pulls/5/reviews?per_page=100&page=2"
    mapping = _single_pr_mapping()
    mapping[p1] = [
        {
            "id": 1,
            "body": "id-link page1",
            "html_url": "https://github.com/ManpreetS2/fencepost/pull/5#pullrequestreview-1",
            "submitted_at": "2026-10-19T21:00:00-07:00",
            "state": "COMMENTED",
            "user": {"login": "ManpreetS2"},
        }
    ]
    mapping[p2] = [
        {
            "id": 2,
            "body": "id-link page2",
            "html_url": "https://github.com/ManpreetS2/fencepost/pull/5#pullrequestreview-2",
            "submitted_at": "2026-10-19T21:01:00-07:00",
            "state": "COMMENTED",
            "user": {"login": "ManpreetS2"},
        }
    ]
    mock = MockGh(
        mapping=mapping,
        links={
            p1: (
                f'<https://api.github.com/repositories/{FENCEPOST_REPO_ID}/'
                'pulls/5/reviews?per_page=100&page=2>; rel="next"'
            )
        },
    )
    result = poll_github(
        cache_dir=cache_dir,
        runner=mock,
        repos=("ManpreetS2/fencepost",),
    )
    assert result.meta_github == "ok"
    assert p2 in mock.calls
    assert any(e.get("raw") == "id-link page1" for e in result.events)
    assert any(e.get("raw") == "id-link page2" for e in result.events)


def test_max_prs_cap_stops_pr_list_pagination(cache_dir: Path) -> None:
    """QA-MM003-10: collect at most MAX_PRS (50) PRs."""
    page1 = [
        {
            "number": n,
            "title": f"feat/RP-{n:03d}-x",
            "body": "~DEV 1 ⚙️",
            "html_url": f"https://github.com/ManpreetS2/fencepost/pull/{n}",
            "created_at": "2026-10-19T21:35:00-07:00",
            "merged_at": None,
            "merge_commit_sha": None,
            "head": {"ref": f"feat/RP-{n:03d}-x", "sha": "aaa"},
            "base": {
                "repo": {"id": FENCEPOST_REPO_ID, "full_name": "ManpreetS2/fencepost"}
            },
            "user": {"login": "ManpreetS2"},
        }
        for n in range(1, 41)
    ]
    page2 = [
        {
            "number": n,
            "title": f"feat/RP-{n:03d}-x",
            "body": "~DEV 1 ⚙️",
            "html_url": f"https://github.com/ManpreetS2/fencepost/pull/{n}",
            "created_at": "2026-10-19T21:35:00-07:00",
            "merged_at": None,
            "merge_commit_sha": None,
            "head": {"ref": f"feat/RP-{n:03d}-x", "sha": "aaa"},
            "base": {
                "repo": {"id": FENCEPOST_REPO_ID, "full_name": "ManpreetS2/fencepost"}
            },
            "user": {"login": "ManpreetS2"},
        }
        for n in range(41, 81)
    ]
    p1 = "repos/ManpreetS2/fencepost/pulls?state=all&per_page=100"
    p2 = f"repositories/{FENCEPOST_REPO_ID}/pulls?state=all&per_page=100&page=2"
    mapping: dict[str, Any] = {
        "repos/ManpreetS2/fencepost": {
            "id": FENCEPOST_REPO_ID,
            "full_name": "ManpreetS2/fencepost",
        },
        p1: page1,
        p2: page2,
    }
    # Empty sub-resources for every PR we might touch (only first 50 opened).
    for n in range(1, MAX_PRS + 1):
        mapping[f"repos/ManpreetS2/fencepost/pulls/{n}/reviews?per_page=100"] = []
        mapping[f"repos/ManpreetS2/fencepost/pulls/{n}/comments?per_page=100"] = []
        mapping[f"repos/ManpreetS2/fencepost/issues/{n}/comments?per_page=100"] = []
        mapping[f"repos/ManpreetS2/fencepost/pulls/{n}/commits?per_page=100"] = []

    mock = MockGh(
        mapping=mapping,
        links={
            p1: (
                f'<https://api.github.com/repositories/{FENCEPOST_REPO_ID}/'
                'pulls?state=all&per_page=100&page=2>; rel="next"'
            )
        },
    )
    result = poll_github(
        cache_dir=cache_dir,
        runner=mock,
        repos=("ManpreetS2/fencepost",),
    )
    opened = [e for e in result.events if e["type"] == "pr_opened"]
    assert len(opened) == MAX_PRS
    # Stopped after first page once 40+ items would continue — with 40 on page1
    # we follow next, then truncate at 50 (10 from page2). Page2 must be fetched.
    assert p2 in mock.calls
    assert max(e["pr"] for e in opened) == MAX_PRS
    assert not any(e.get("pr", 0) > MAX_PRS for e in result.events)


def test_pagination_page_cap(cache_dir: Path) -> None:
    """SEC-MM003-1: stop after MAX_PAGES (20) and set meta.github=error."""
    mapping = _single_pr_mapping()
    links: dict[str, str] = {}
    for page in range(1, MAX_PAGES + 2):
        if page == 1:
            path = "repos/ManpreetS2/fencepost/pulls/5/reviews?per_page=100"
        else:
            path = (
                f"repos/ManpreetS2/fencepost/pulls/5/reviews?per_page=100&page={page}"
            )
        mapping[path] = [
            {
                "id": page,
                "body": f"cap review {page}",
                "html_url": (
                    f"https://github.com/ManpreetS2/fencepost/pull/5#pullrequestreview-{page}"
                ),
                "submitted_at": "2026-10-19T21:00:00-07:00",
                "state": "COMMENTED",
                "user": {"login": "ManpreetS2"},
            }
        ]
        if page <= MAX_PAGES:
            nxt = (
                f"repos/ManpreetS2/fencepost/pulls/5/reviews?per_page=100&page={page + 1}"
            )
            links[path] = f'<https://api.github.com/{nxt}>; rel="next"'

    mock = MockGh(mapping=mapping, links=links)
    result = poll_github(
        cache_dir=cache_dir,
        runner=mock,
        repos=("ManpreetS2/fencepost",),
    )
    assert result.meta_github == "error"
    assert any("page cap" in e for e in result.errors)
    review_pages = [
        e for e in result.events if e.get("raw", "").startswith("cap review ")
    ]
    assert len(review_pages) == MAX_PAGES
    assert not any(c.endswith(f"page={MAX_PAGES + 1}") for c in mock.calls)
