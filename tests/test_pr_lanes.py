"""MM-020e / MM-013: GitHub PR-lane NetworkEvents + edges (github-verified)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import jsonschema
import pytest

from ingest.attribute import load_bots
from ingest.edges import derive_edges
from ingest.github_poller import (
    ALLOWED_REPOS,
    GitHubPoller,
    SUMMARY_MAX_CHARS,
    activity_event_to_network_event,
    build_pr_lane_events,
    event_id,
    poll_github,
    sanitize_pr_summary,
)
from ingest.migrate import migrate_activity
from tests.test_github_poller import MockGh

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schema" / "activity.schema.json"
FIXTURE_1_0 = ROOT / "fixtures" / "sample-activity.json"


def _schema() -> dict:
    with SCHEMA_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _activity_event(
    *,
    locator: str,
    etype: str,
    actor: str | None,
    pr: int,
    repo: str = "ManpreetS2/fencepost",
    raw: str = "hello",
    group_hint: str | None = None,
    attribution: str = "signature",
) -> dict:
    evt = {
        "id": event_id("github", locator),
        "type": etype,
        "actor": actor,
        "target": None,
        "task_id": "MM-013",
        "pr": pr,
        "repo": repo,
        "attribution": {"method": attribution},
        "source_url": f"https://github.com/{repo}/pull/{pr}",
        "source_time": "2026-10-20T12:00:00+00:00",
        "raw": raw,
        "provenance": "github-verified",
    }
    if group_hint:
        evt["_group_hint"] = group_hint
    return evt


def test_github_verified_provenance_on_network_events(tmp_path: Path) -> None:
    result = poll_github(cache_dir=tmp_path / "c", runner=MockGh())
    network, edges = build_pr_lane_events(result, load_bots())
    assert network
    assert all(e.get("provenance") == "github-verified" for e in network)
    assert all(isinstance(e.get("summary"), str) and e["summary"] for e in network)
    # Edges are activity Edge shape
    assert isinstance(edges, list)


def test_stable_id_and_dedupe_same_pr_event_twice() -> None:
    opened = _activity_event(
        locator="ManpreetS2/fencepost#pr9:opened",
        etype="pr_opened",
        actor="qa-verifier",
        pr=9,
        raw="Opened PR #9 ~QA / Verifier 🧪",
    )
    # Identical id when locator repeats
    twin = dict(opened)
    network, edges = build_pr_lane_events([opened, twin, opened], load_bots())
    assert len(network) == 1
    assert network[0]["id"] == event_id(
        "github", "ManpreetS2/fencepost#pr9:opened"
    )
    # Polling twice → still one edge bucket for the same PR open (no author→reviewer yet)
    n2, e2 = build_pr_lane_events([opened, twin], load_bots())
    assert len(n2) == 1
    assert e2 == edges


def test_unknown_author_no_false_edge() -> None:
    opened = _activity_event(
        locator="ManpreetS2/fencepost#pr10:opened",
        etype="pr_opened",
        actor=None,
        pr=10,
        raw="Opened without signature",
        attribution="unknown",
    )
    review = _activity_event(
        locator="ManpreetS2/fencepost#pr10:review:1",
        etype="verdict",
        actor="architect",
        pr=10,
        raw="~Architect 🛠️ PASS",
    )
    review["verdict"] = "PASS"
    network, edges = build_pr_lane_events([opened, review], load_bots())
    assert any(n["sender"] == "UNKNOWN" for n in network)
    # No pr/verdict edge without known PR author
    assert not any(e["type"] in {"pr", "verdict"} for e in edges)


def test_allowlist_enforced() -> None:
    assert "ManpreetS2/fencepost" in ALLOWED_REPOS
    assert "evil/other" not in ALLOWED_REPOS
    with pytest.raises(ValueError, match="not allowed"):
        GitHubPoller(repos=("evil/other",))


def test_cross_group_architect_build_reviews_qa_qr() -> None:
    """Architect (build) reviewing QA (qr) PR → correct groups + pr/verdict edges."""
    bots = load_bots()
    by_id = {b["id"]: b for b in bots}
    assert by_id["architect"]["group"] == "build"
    assert by_id["qa-verifier"]["group"] == "qr"

    opened = _activity_event(
        locator="ManpreetS2/fencepost#pr11:opened",
        etype="pr_opened",
        actor="qa-verifier",
        pr=11,
        raw="Opened ~QA / Verifier 🧪",
    )
    review = _activity_event(
        locator="ManpreetS2/fencepost#pr11:review:99",
        etype="verdict",
        actor="architect",
        pr=11,
        raw="~Architect 🛠️ CHANGES",
    )
    review["verdict"] = "CHANGES"

    network, edges = build_pr_lane_events([opened, review], bots)
    by_sender = {n["sender"]: n for n in network}
    assert by_sender["qa-verifier"]["group"] == "qr"
    assert by_sender["architect"]["group"] == "build"
    assert by_sender["architect"]["provenance"] == "github-verified"

    pr_edges = [e for e in edges if e["type"] == "pr"]
    verdict_edges = [e for e in edges if e["type"] == "verdict"]
    assert any(
        e["source"] == "qa-verifier" and e["target"] == "architect" for e in pr_edges
    )
    assert any(
        e["source"] == "architect" and e["target"] == "qa-verifier"
        for e in verdict_edges
    )


def test_summary_secret_refused_and_240_cap() -> None:
    assert sanitize_pr_summary("ok note") == "ok note"
    assert sanitize_pr_summary("x" * SUMMARY_MAX_CHARS)
    assert len(sanitize_pr_summary("x" * (SUMMARY_MAX_CHARS + 10)) or "") == SUMMARY_MAX_CHARS
    assert sanitize_pr_summary("leak sk-proj-abcdefghijklmnopqrstuvwxyz1234567890AB") is None

    dirty = _activity_event(
        locator="ManpreetS2/fencepost#pr12:opened",
        etype="pr_opened",
        actor="dev-1",
        pr=12,
        raw="token ghp_abcdefghijklmnopqrstuvwxyz1234567890AB",
    )
    network, _ = build_pr_lane_events([dirty], load_bots())
    assert network == []


def test_activity_event_to_network_unknown_sender() -> None:
    evt = _activity_event(
        locator="x#pr1:opened",
        etype="pr_opened",
        actor=None,
        pr=1,
        raw="unsigned open",
        attribution="unknown",
    )
    ne = activity_event_to_network_event(evt, load_bots())
    assert ne is not None
    assert ne["sender"] == "UNKNOWN"
    assert ne["provenance"] == "github-verified"


def test_legacy_1_0_0_fixture_still_validates() -> None:
    with FIXTURE_1_0.open(encoding="utf-8") as f:
        doc = json.load(f)
    assert doc["schema_version"] == "1.0.0"
    jsonschema.validate(instance=doc, schema=_schema())
    # Migration still fills provenance for 1.1.0 consumers
    bumped = migrate_activity(doc, bump_version=True)
    assert bumped["schema_version"] == "1.1.0"
    jsonschema.validate(instance=bumped, schema=_schema())


def test_poller_events_have_github_verified_and_stable_ids(tmp_path: Path) -> None:
    result = poll_github(cache_dir=tmp_path / "c", runner=MockGh())
    assert result.events
    assert all(e.get("provenance") == "github-verified" for e in result.events)
    sample = next(
        e
        for e in result.events
        if e["type"] == "pr_opened" and e.get("repo") == "ManpreetS2/fencepost"
    )
    expected = event_id("github", f"ManpreetS2/fencepost#pr{sample['pr']}:opened")
    assert sample["id"] == expected
    assert all(len(e["id"]) == 40 for e in result.events)


def test_qa_mm020e_secret_raw_dropped_on_all_paths() -> None:
    """QA-MM020e-1/2: secrets in title, review, comment, commit → drop; nowhere in output."""
    from ingest.github_poller import GitHubPoller, _event

    sk = "sk-proj-abcdefghijklmnopqrstuvwxyz1234567890ABCDEF"
    poller = GitHubPoller(bots=load_bots(), runner=MockGh(fail=True))
    html = "https://github.com/ManpreetS2/fencepost/pull/42"

    # --- PR title path (_events_for_pr → pr_opened) ---
    pr_with_secret_title = {
        "number": 42,
        "title": f"feat: ship {sk}",
        "body": "~Architect 🛠️",
        "html_url": html,
        "created_at": "2026-10-20T12:00:00Z",
        "head": {"ref": "feat/x"},
    }
    title_events = poller._events_for_pr(
        "ManpreetS2/fencepost", pr_with_secret_title, set()
    )
    # No network; commits/reviews will 404 via fail runner — still assert title path
    opened = [e for e in title_events if e.get("type") == "pr_opened"]
    assert opened == []
    blob_title = json.dumps(title_events)
    assert sk not in blob_title

    # Direct _event with title-shaped raw
    assert (
        _event(
            locator="t",
            etype="pr_opened",
            actor="architect",
            task_id=None,
            pr=1,
            source_url=html,
            source_time="2026-10-20T12:00:00Z",
            attribution="signature",
            raw=f"Opened pull request #1: feat {sk}",
            repo="ManpreetS2/fencepost",
        )
        is None
    )

    # --- Review body path ---
    rev_out = poller._review_events(
        "ManpreetS2/fencepost",
        42,
        html,
        "MM-020",
        {
            "id": 99,
            "body": f"~Architect 🛠️ PASS but token {sk}",
            "html_url": html,
            "submitted_at": "2026-10-20T12:01:00Z",
        },
        set(),
    )
    assert rev_out == []
    assert sk not in json.dumps(rev_out)

    # --- Comment body path ---
    cmt_out = poller._comment_events(
        "ManpreetS2/fencepost",
        42,
        "MM-020",
        {
            "id": 77,
            "body": f"note with {sk} ~DEV 2",
            "html_url": html,
            "created_at": "2026-10-20T12:02:00Z",
        },
        set(),
        kind="issue_comment",
    )
    assert cmt_out == []
    assert sk not in json.dumps(cmt_out)

    # Email in comment also dropped
    email = "alice@example.com"
    cmt_email = poller._comment_events(
        "ManpreetS2/fencepost",
        42,
        None,
        {
            "id": 78,
            "body": f"ping {email}",
            "html_url": html,
            "created_at": "2026-10-20T12:03:00Z",
        },
        set(),
        kind="review_comment",
    )
    assert cmt_email == []
    assert email not in json.dumps(cmt_email)

    # --- Commit subject path ---
    push_out = poller._push_events(
        "ManpreetS2/fencepost",
        42,
        html,
        "MM-020",
        {
            "sha": "abcdef1234567890abcdef1234567890abcdef12",
            "commit": {
                "message": f"fix: rotate {sk}\n\nbody",
                "author": {"date": "2026-10-20T12:04:00Z"},
            },
        },
        set(),
    )
    assert push_out == []
    assert sk not in json.dumps(push_out)

    # Clean paths still emit (sanitized raw only)
    clean_push = poller._push_events(
        "ManpreetS2/fencepost",
        42,
        html,
        "MM-020",
        {
            "sha": "cccccc1234567890abcdef1234567890abcdef12",
            "commit": {
                "message": "feat: wire PR lanes ~DEV 2\n\nmore",
                "author": {"date": "2026-10-20T12:05:00Z"},
            },
        },
        set(),
    )
    assert len(clean_push) == 1
    assert clean_push[0]["raw"] == "feat: wire PR lanes ~DEV 2"
    assert clean_push[0]["type"] == "pr_updated"


def test_derive_edges_idempotent_with_duplicate_lane_events() -> None:
    opened = _activity_event(
        locator="ManpreetS2/fencepost#pr13:opened",
        etype="pr_opened",
        actor="dev-2",
        pr=13,
        raw="~DEV 2 open",
    )
    review = _activity_event(
        locator="ManpreetS2/fencepost#pr13:review:1",
        etype="verdict",
        actor="qa-verifier",
        pr=13,
        raw="~QA / Verifier 🧪 PASS",
    )
    review["verdict"] = "PASS"
    e1 = derive_edges([opened, review])
    e2 = derive_edges([opened, review, opened, review])
    # Same edge identity set (counts may grow on duplicates — dedupe is in build_pr_lane_events)
    ids1 = {e["id"] for e in e1}
    ids2 = {e["id"] for e in e2}
    assert ids1 == ids2
