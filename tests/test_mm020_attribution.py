"""MM-020-P0: strict attribution + QA Mac (bbbf47) behaviors."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ingest.actor_resolve import (
    resolve_pr_lane_actor,
    signature_at_start,
)
from ingest.build import build_nodes
from ingest.edges import derive_edges
from ingest.github_poller import GitHubPollResult, build_pr_lane_events
from ingest.live import assemble_activity
from ingest.ledger_parser import LedgerParseResult
from ingest.github_poller import poll_github
from tests.test_github_poller import MockGh

ROOT = Path(__file__).resolve().parents[1]
BOTS_PATH = ROOT / "config" / "bots.json"
LEDGER_FIXTURE = ROOT / "tests" / "fixtures" / "ledger-sample.md"


@pytest.fixture
def bots() -> list[dict]:
    with BOTS_PATH.open(encoding="utf-8") as f:
        return json.load(f)["bots"]


def test_signature_at_start_only_not_mid_body(bots: list[dict]) -> None:
    assert signature_at_start("~Architect review", bots)[0] == "architect"
    assert signature_at_start("hello ~Architect", bots)[0] is None
    assert signature_at_start("~Nobody", bots)[0] is None


def test_precedence_network_from_over_signature(bots: list[dict]) -> None:
    actor, method = resolve_pr_lane_actor(
        body="~Architect note",
        sender_field="dev-1",
        bots=bots,
    )
    assert actor == "dev-1"
    assert method == "network_from"


def test_ledger_owner_when_ledger_present(bots: list[dict]) -> None:
    tasks = [{"id": "MM-020", "owner": "Architect", "status": "IN_PROGRESS"}]
    actor, method = resolve_pr_lane_actor(
        body="plain text",
        task_id="MM-020",
        ledger_tasks=tasks,
        bots=bots,
    )
    assert actor == "architect"
    assert method == "ledger_owner"


def test_ledger_owner_skipped_when_no_ledger(bots: list[dict]) -> None:
    actor, method = resolve_pr_lane_actor(
        body="plain",
        task_id="MM-020",
        ledger_tasks=[],
        bots=bots,
    )
    assert actor is None
    assert method == "unknown"


def test_nodes_unknown_when_ledger_unavailable(bots: list[dict]) -> None:
    nodes = build_nodes(bots, [], [], meta_ledger="unavailable")
    assert all(n["status"] == "UNKNOWN" for n in nodes)


def test_mac_style_pr_lane_yields_edges(bots: list[dict], tmp_path: Path) -> None:
    """Authors are shared GitHub logins; bodies carry ~Bot signatures."""
    ledger_tasks = [{"id": "RP-005", "owner": "DEV 1", "status": "IN_PROGRESS"}]
    result = poll_github(
        cache_dir=tmp_path / "c",
        runner=MockGh(),
        ledger_tasks=ledger_tasks,
    )
    assert result.meta_github == "ok"
    assert all(e.get("repo") for e in result.events if e.get("pr"))
    network, edges = build_pr_lane_events(result, roster=bots)
    assert network
    assert any(e.get("actor") for e in result.events)
    assert len(edges) > 0
    nodes = build_nodes(bots, [], result.events, meta_ledger="unavailable")
    evidenced = [n for n in nodes if n.get("last_activity_ts")]
    assert evidenced
    assert all(n["status"] != "IDLE" for n in nodes)


def test_assemble_includes_groups_and_repo_on_events(
    bots: list[dict], tmp_path: Path
) -> None:
    gh = poll_github(cache_dir=tmp_path / "c", runner=MockGh())
    doc = assemble_activity(
        ledger=LedgerParseResult(source_url="x"),
        gh=gh,
        bots=bots,
        generated_at="2026-10-20T12:00:00Z",
        meta_ledger="unavailable",
    )
    assert isinstance(doc.get("groups"), list)
    assert len(doc["groups"]) >= 3
    assert "groups_reason" not in doc
    assert doc["meta"].get("unattributed_event_count", 0) >= 0
    pr_events = [e for e in doc["events"] if e.get("pr")]
    assert pr_events and all(e.get("repo") for e in pr_events)

