"""MM-020a: multi-membership, message edges, provenance, schema migration."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from ingest.edges import derive_edges
from ingest.membership import (
    group_target_id,
    groups_for_bot,
    load_groups,
    membership_index,
)
from ingest.migrate import migrate_activity

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schema" / "activity.schema.json"
BOTS_PATH = ROOT / "config" / "bots.json"
GROUPS_PATH = ROOT / "config" / "groups.json"
SAMPLE = ROOT / "fixtures" / "sample-activity.json"
WEB_FIXTURES = ROOT / "web" / "src" / "fixtures"
PUBLIC_ACTIVITY = ROOT / "web" / "public" / "activity.json"

RESEARCH_MEMBERS = {"director", "architect", "scout", "skeptic", "nomen"}
BUILD_MEMBERS = {
    "director",
    "architect",
    "dev-1",
    "dev-2",
    "ui-ux-maker",
    "documentation",
}
QR_MEMBERS = {
    "director",
    "architect",
    "qa-verifier",
    "security-engineer",
    "devops-release",
}


@pytest.fixture(scope="module")
def schema() -> dict:
    with SCHEMA_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def test_groups_json_membership() -> None:
    cfg = load_groups(GROUPS_PATH)
    by_id = {g["id"]: set(g["members"]) for g in cfg["groups"]}
    assert by_id["build"] == BUILD_MEMBERS
    assert by_id["qr"] == QR_MEMBERS
    assert by_id["radar"] == RESEARCH_MEMBERS
    # Bug fixer stays out of Research; add via config alone later.
    assert "bug-fixer" not in by_id["radar"]
    assert "bug-fixer" not in by_id["build"]
    assert "bug-fixer" not in by_id["qr"]


def test_director_architect_multi_membership() -> None:
    idx = membership_index(load_groups(GROUPS_PATH))
    assert set(idx["director"]) == {"build", "qr", "radar"}
    assert set(idx["architect"]) == {"build", "qr", "radar"}
    assert groups_for_bot("bug-fixer") == []
    # One identity: single bot id, many groups — not duplicated ids in roster.
    with BOTS_PATH.open(encoding="utf-8") as f:
        bots = json.load(f)["bots"]
    ids = [b["id"] for b in bots]
    assert len(ids) == len(set(ids))
    assert ids.count("director") == 1
    assert ids.count("architect") == 1


def test_message_edge_untargeted_is_sender_to_group() -> None:
    events = [
        {
            "id": "msg-1",
            "type": "message",
            "actor": "director",
            "target": None,
            "task_id": None,
            "attribution": {"method": "unknown"},
            "source_url": "agent://emit",
            "source_time": "2026-10-20T12:00:00-07:00",
            "raw": "hello build",
            "group": "build",
            "provenance": "agent-reported",
        }
    ]
    edges = derive_edges(events)
    assert len(edges) == 1
    assert edges[0]["type"] == "message"
    assert edges[0]["source"] == "director"
    assert edges[0]["target"] == group_target_id("build")


def test_message_edge_explicit_recipients_only() -> None:
    events = [
        {
            "id": "msg-2",
            "type": "message",
            "actor": "architect",
            "target": None,
            "recipients": ["dev-1", "dev-2"],
            "task_id": "MM-020",
            "attribution": {"method": "unknown"},
            "source_url": "agent://emit",
            "source_time": "2026-10-20T12:01:00-07:00",
            "raw": "please pick up",
            "group": "build",
            "provenance": "agent-reported",
        }
    ]
    edges = derive_edges(events)
    pairs = {(e["source"], e["target"], e["type"]) for e in edges}
    assert pairs == {
        ("architect", "dev-1", "message"),
        ("architect", "dev-2", "message"),
    }


def test_message_never_invents_recipients() -> None:
    """No recipients and no group → no message edge (do not invent targets)."""
    events = [
        {
            "id": "msg-3",
            "type": "message",
            "actor": "scout",
            "target": None,
            "task_id": None,
            "attribution": {"method": "unknown"},
            "source_url": "agent://emit",
            "source_time": "2026-10-20T12:02:00-07:00",
            "raw": "orphan",
            "provenance": "observed",
        }
    ]
    assert derive_edges(events) == []


def test_message_event_validates_with_provenance(schema: dict) -> None:
    activity = {
        "schema_version": "1.1.0",
        "generated_at": "2026-10-20T12:00:00-07:00",
        "project": "fencepost",
        "meta": {"github": "skipped"},
        "nodes": [
            {
                "id": "director",
                "label": "Director",
                "group": "build",
                "groups": ["build", "qr", "radar"],
                "status": "IDLE",
                "agent_links": [],
                "layout": {"x": 0, "y": 0},
            }
        ],
        "tasks": [],
        "events": [
            {
                "id": "e1",
                "type": "message",
                "actor": "director",
                "target": None,
                "task_id": None,
                "attribution": {"method": "unknown"},
                "source_url": "agent://emit",
                "source_time": "2026-10-20T12:00:00-07:00",
                "raw": "hi",
                "group": "build",
                "provenance": "agent-reported",
            }
        ],
        "edges": [
            {
                "id": "edge1",
                "source": "director",
                "target": "group:build",
                "type": "message",
                "count": 1,
                "event_ids": ["e1"],
            }
        ],
        "unparsed": [],
    }
    jsonschema.validate(instance=activity, schema=schema)


def _activity_fixture_paths() -> list[Path]:
    paths = [SAMPLE]
    if PUBLIC_ACTIVITY.is_file():
        paths.append(PUBLIC_ACTIVITY)
    if WEB_FIXTURES.is_dir():
        paths.extend(sorted(WEB_FIXTURES.glob("*.json")))
    return paths


@pytest.mark.parametrize("path", _activity_fixture_paths(), ids=lambda p: p.name)
def test_legacy_activity_fixtures_load_unchanged(path: Path, schema: dict) -> None:
    """Migration: every old activity.json fixture loads as-is (no rewrite)."""
    raw = path.read_text(encoding="utf-8")
    doc = json.loads(raw)
    assert doc["schema_version"] == "1.0.0"
    jsonschema.validate(instance=doc, schema=schema)
    migrated = migrate_activity(doc)
    # Unchanged content aside from optional in-memory deepcopy equality of data.
    assert migrated["schema_version"] == "1.0.0"
    assert migrated["nodes"] == doc["nodes"]
    assert migrated["events"] == doc["events"]
    assert migrated["edges"] == doc["edges"]
    # Disk file untouched
    assert path.read_text(encoding="utf-8") == raw


def test_migrate_can_bump_version_in_memory_only(schema: dict) -> None:
    with SAMPLE.open(encoding="utf-8") as f:
        doc = json.load(f)
    bumped = migrate_activity(doc, bump_version=True)
    assert bumped["schema_version"] == "1.1.0"
    jsonschema.validate(instance=bumped, schema=schema)
    # Fixture on disk still 1.0.0
    with SAMPLE.open(encoding="utf-8") as f:
        assert json.load(f)["schema_version"] == "1.0.0"
