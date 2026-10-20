"""MM-020k / QA-MM020g: network→activity, demo groups, message edges, sender resolve."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from ingest.attribute import load_bots
from ingest.build import resolve_project_name
from ingest.demo_mode import load_demo_activity_bytes, load_demo_network_events
from ingest.edges import derive_edges
from ingest.github_poller import GitHubPollResult
from ingest.ledger_parser import LedgerParseResult
from ingest.live import (
    LiveDaemon,
    assemble_activity,
    network_event_to_activity_event,
)
from ingest.membership import load_groups, membership_index
from ingest.sender_resolve import (
    UNATTRIBUTED,
    resolve_network_sender,
    room_member_bots,
    sender_label,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schema" / "activity.schema.json"
GROUPS_PATH = ROOT / "config" / "groups.json"
SAMPLE = ROOT / "fixtures" / "sample-activity.json"


@pytest.fixture(scope="module")
def schema() -> dict:
    with SCHEMA_PATH.open(encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def bots() -> list[dict]:
    return load_bots()


def test_g2_exactly_three_team_groups() -> None:
    cfg = load_groups(GROUPS_PATH)
    ids = [g["id"] for g in cfg["groups"]]
    assert ids == ["build", "qr", "radar"]
    assert "owner" not in ids
    idx = membership_index(cfg)
    assert "manpreet" not in idx
    assert idx["director"] == ["build", "qr", "radar"]


def test_g5_bug_fixer_home_build_not_in_radar() -> None:
    bots = load_bots()
    bf = next(b for b in bots if b["id"] == "bug-fixer")
    assert bf["group"] == "build"
    radar = next(g for g in load_groups()["groups"] if g["id"] == "radar")
    assert "bug-fixer" not in radar["members"]
    assert "bug-fixer" not in membership_index()


def test_g1_demo_activity_has_groups_and_unique_identities(schema: dict) -> None:
    body = load_demo_activity_bytes()
    doc = json.loads(body.decode())
    assert doc["schema_version"] == "1.1.0"
    assert doc["project"] == resolve_project_name()
    jsonschema.validate(instance=doc, schema=schema)
    director = [n for n in doc["nodes"] if n["id"] == "director"]
    architect = [n for n in doc["nodes"] if n["id"] == "architect"]
    assert len(director) == 1
    assert len(architect) == 1
    assert set(director[0]["groups"]) == {"build", "qr", "radar"}
    assert set(architect[0]["groups"]) == {"build", "qr", "radar"}
    manpreet = next(n for n in doc["nodes"] if n["id"] == "manpreet")
    assert manpreet["groups"] == []


def test_g1_sample_fixture_regenerated(schema: dict) -> None:
    with SAMPLE.open(encoding="utf-8") as f:
        doc = json.load(f)
    assert doc["schema_version"] == "1.1.0"
    jsonschema.validate(instance=doc, schema=schema)
    director = next(n for n in doc["nodes"] if n["id"] == "director")
    assert set(director["groups"]) == {"build", "qr", "radar"}


def test_g4_message_edges_from_network_events(bots: list[dict]) -> None:
    network = load_demo_network_events()
    assert network
    assert all(ne.get("recipients") for ne in network)
    mapped = [network_event_to_activity_event(ne, bots=bots) for ne in network]
    mapped = [m for m in mapped if m]
    assert all(m["type"] == "message" for m in mapped)
    edges = derive_edges(mapped)
    msg = [e for e in edges if e["type"] == "message"]
    assert len(msg) >= 3
    pairs = {(e["source"], e["target"]) for e in msg}
    assert ("director", "architect") in pairs
    assert ("architect", "qa-verifier") in pairs


def test_g4_demo_activity_includes_message_edges() -> None:
    doc = json.loads(load_demo_activity_bytes().decode())
    assert any(e["type"] == "message" for e in doc["events"])
    assert any(e["type"] == "message" for e in doc["edges"])


def test_g6_rebuild_without_ledger_merges_network_and_github(
    tmp_path: Path, bots: list[dict]
) -> None:
    activity_path = tmp_path / "activity.json"
    cache = tmp_path / "cache"
    cache.mkdir()
    daemon = LiveDaemon(
        ledger_path=tmp_path / "missing-ledger.md",
        activity_path=activity_path,
        static_dir=tmp_path,
        cache_dir=cache,
        bots=bots,
        ledger_source="path",
        events_source="off",
        github_runner=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no gh")),
    )
    # Simulate GitHub ok + network events while ledger unavailable.
    gh_evt = {
        "id": "gh-open-1",
        "type": "pr_opened",
        "actor": "dev-1",
        "target": None,
        "task_id": None,
        "pr": 99,
        "repo": "ManpreetS2/agent-mindmap",
        "attribution": {"method": "unknown"},
        "source_url": "https://github.com/ManpreetS2/agent-mindmap/pull/99",
        "source_time": "2026-10-20T12:00:00Z",
        "raw": "opened",
        "provenance": "github-verified",
    }
    daemon._gh = GitHubPollResult(events=[gh_evt], meta_github="ok")
    daemon._gh_fp = "gh-fp"
    daemon._health.github_status = "ok"
    daemon._meta_ledger = "unavailable"
    daemon._health.ledger_status = "unavailable"
    daemon.ingest_network_events(
        [
            {
                "id": "net-msg-1",
                "ts": "2026-10-20T12:01:00+00:00",
                "sender": "director",
                "recipients": ["architect"],
                "group": "build",
                "type": "message",
                "summary": "ping",
                "provenance": "agent-reported",
                "repo": "ManpreetS2/agent-mindmap",
            }
        ]
    )
    assert daemon.maybe_rebuild(force=True)
    doc = json.loads(activity_path.read_text(encoding="utf-8"))
    assert doc["meta"]["ledger"] == "unavailable"
    assert doc["meta"]["github"] == "ok"
    ids = {e["id"] for e in doc["events"]}
    assert "gh-open-1" in ids
    assert "net-msg-1" in ids
    assert any(e["type"] == "message" for e in doc["edges"])


def test_g6_assemble_empty_partial_errored_sources(bots: list[dict]) -> None:
    empty = assemble_activity(
        ledger=LedgerParseResult(source_url="x"),
        gh=GitHubPollResult(events=[], meta_github="never_run"),
        bots=bots,
        generated_at="2026-10-20T12:00:00Z",
        meta_ledger="unavailable",
        network_events=[],
        meta_github="never_run",
    )
    assert empty["events"] == []
    assert empty["meta"]["github"] == "never_run"
    assert empty["meta"]["ledger"] == "unavailable"

    partial = assemble_activity(
        ledger=LedgerParseResult(source_url="x"),
        gh=GitHubPollResult(events=[], meta_github="error"),
        bots=bots,
        generated_at="2026-10-20T12:00:00Z",
        meta_ledger="ok",
        network_events=[],
        meta_github="error",
    )
    assert partial["meta"]["github"] == "error"

    errored = assemble_activity(
        ledger=LedgerParseResult(source_url="x"),
        gh=GitHubPollResult(events=[], meta_github="skipped"),
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
        meta_github="skipped",
    )
    assert errored["meta"]["ledger"] == "error"
    assert any(e["id"] == "n1" for e in errored["events"])


def test_g7_project_name_is_agent_mindmap() -> None:
    assert resolve_project_name(env={}) == "agent-mindmap"
    assert resolve_project_name(env={"MINDMAP_PROJECT": "custom"}) == "custom"


def test_g7_events_carry_repo(bots: list[dict]) -> None:
    doc = json.loads(load_demo_activity_bytes().decode())
    msg = [e for e in doc["events"] if e["type"] == "message"]
    assert msg
    assert all(e.get("repo") == "ManpreetS2/agent-mindmap" for e in msg)


def test_g8_unknown_resolves_from_room_signature(bots: list[dict]) -> None:
    ne = {
        "id": "u1",
        "ts": "2026-10-20T12:00:00+00:00",
        "sender": "UNKNOWN",
        "group": "build",
        "type": "note",
        "summary": "~Architect 🛠️ build note on schema",
        "provenance": "agent-reported",
    }
    room = room_member_bots("build", bots)
    assert any(b["id"] == "architect" for b in room)
    assert resolve_network_sender(ne, bots=bots) == "architect"
    evt = network_event_to_activity_event(ne, bots=bots)
    assert evt is not None
    assert evt["actor"] == "architect"


def test_g8_unknown_without_signature_is_unattributed(bots: list[dict]) -> None:
    ne = {
        "id": "u2",
        "ts": "2026-10-20T12:00:00+00:00",
        "sender": "UNKNOWN",
        "group": "build",
        "type": "note",
        "summary": "anonymous build note with no signature",
        "provenance": "agent-reported",
    }
    assert resolve_network_sender(ne, bots=bots) is None
    assert sender_label(None) == UNATTRIBUTED
    evt = network_event_to_activity_event(ne, bots=bots)
    assert evt is not None
    assert evt["actor"] is None
    # No invented message/handoff edge from null actor
    assert derive_edges([evt]) == []
