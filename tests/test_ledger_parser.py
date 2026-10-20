"""Golden tests for ingest/ledger_parser.py (MM-002)."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from ingest.ledger_parser import (
    NOTE_RE,
    STRUCTURED_RE,
    parse_ledger,
    parse_ledger_file,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "ledger-sample.md"
SCHEMA_PATH = ROOT / "schema" / "activity.schema.json"


@pytest.fixture(scope="module")
def schema() -> dict:
    with SCHEMA_PATH.open(encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def parsed():
    return parse_ledger_file(FIXTURE, source_url="build/task-ledger.md")


@pytest.fixture(scope="module")
def fixture_text() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def test_every_table_row_becomes_a_task(parsed) -> None:
    ids = {t["id"] for t in parsed.tasks}
    assert ids == {"RP-004", "RP-005", "RP-005D", "MM-001"}
    assert len(parsed.tasks) == 4

    by_id = {t["id"]: t for t in parsed.tasks}
    assert by_id["RP-004"]["status"] == "IN_REVIEW"
    assert by_id["RP-004"]["prs"] == [6]
    assert by_id["RP-005"]["status"] == "DONE"
    assert by_id["RP-005"]["prs"] == [5]
    assert by_id["RP-005D"]["status"] == "BLOCKED"
    assert by_id["MM-001"]["status"] == "IDLE"
    assert by_id["MM-001"]["owner"] == "Architect"


def test_four_note_variants_parsed(fixture_text: str, parsed) -> None:
    """Each of the four free-text timestamp/actor shapes must match and become events."""
    variants = {
        "no_comma": "- 2026-10-19 8:45 PM PDT Director: GO for Architect on MM-001 schema work.",
        "comma": "- 2026-10-19 9:20 PM PDT, Architect: handed to DEV 1 for RP-004 workload generator.",
        "24h_no_actor": "- 2026-10-19 21:35 PDT: squash-merged as 693ebc7 for PR #5 on RP-005.",
        "correction": (
            "- 2026-10-19 9:21 PM PDT, Architect CORRECTION: "
            "RP-009 withdrawn/renamed RP-005D; keep RP-005D as the active id."
        ),
    }
    for label, line in variants.items():
        assert NOTE_RE.match(line), f"variant {label} must match NOTE_RE"
        assert any(e["raw"] == line for e in parsed.events), f"missing event for {label}"

    assigned = next(e for e in parsed.events if e["raw"] == variants["no_comma"])
    assert assigned["type"] == "assigned"
    assert assigned["actor"] == "director"
    assert assigned["target"] == "architect"
    assert assigned["attribution"]["method"] == "ledger_owner"
    assert assigned["task_id"] == "MM-001"
    assert assigned["source_time"].endswith("-07:00") or assigned["source_time"].endswith("-08:00")

    handoff = next(e for e in parsed.events if e["raw"] == variants["comma"])
    assert handoff["type"] == "handoff"
    assert handoff["actor"] == "architect"
    assert handoff["target"] == "dev-1"
    assert handoff["task_id"] == "RP-004"

    merged = next(e for e in parsed.events if e["raw"] == variants["24h_no_actor"])
    assert merged["type"] == "merged"
    assert merged["actor"] is None
    assert merged["attribution"]["method"] == "unknown"
    assert merged["sha"] == "693ebc7"
    assert merged["pr"] == 5
    assert merged["task_id"] == "RP-005"

    correction = next(e for e in parsed.events if e["raw"] == variants["correction"])
    assert correction["actor"] == "architect"
    assert correction["attribution"]["method"] == "ledger_owner"
    assert correction["task_id"] == "RP-009"


def test_structured_note_format(parsed) -> None:
    structured = (
        "- 2026-10-19T21:40:00-07:00 | QA / Verifier | verdict | RP-005 | "
        "PASS after recheck of etag cache tests."
    )
    assert STRUCTURED_RE.match(structured)
    evt = next(e for e in parsed.events if e["raw"] == structured)
    assert evt["type"] == "verdict"
    assert evt["actor"] == "qa-verifier"
    assert evt["task_id"] == "RP-005"
    assert evt["verdict"] == "PASS"
    assert evt["attribution"]["method"] == "ledger_owner"
    assert evt["source_time"] == "2026-10-19T21:40:00-07:00"


def test_undated_and_prose_go_to_unparsed(parsed) -> None:
    unparsed_raws = {e["raw"] for e in parsed.unparsed}
    assert "Active coding workers: 0 of 2 (DEV 1 idle after merge)." in unparsed_raws
    assert "- UI/UX Maker: approved backup coder for design-spec polish." in unparsed_raws
    for evt in parsed.unparsed:
        assert evt["type"] == "unparsed"
        assert evt["attribution"]["method"] == "unknown"
        assert "source_time" in evt


def test_no_line_lost(parsed) -> None:
    assert len(parsed.input_lines) > 0
    assert len(parsed.parsed_lines) + len(parsed.unparsed_lines) == len(parsed.input_lines)
    assert set(parsed.parsed_lines) | set(parsed.unparsed_lines) == set(parsed.input_lines)


def test_event_ids_stable_across_runs(fixture_text: str) -> None:
    a = parse_ledger(fixture_text, source_url="build/task-ledger.md")
    b = parse_ledger(fixture_text, source_url="build/task-ledger.md")
    assert [e["id"] for e in a.events] == [e["id"] for e in b.events]
    assert [e["id"] for e in a.unparsed] == [e["id"] for e in b.unparsed]
    # Exact duplicate note is de-duplicated by event id
    director_lines = [
        line
        for line in a.parsed_lines
        if "8:45 PM PDT Director" in line
    ]
    assert len(director_lines) == 2
    director_events = [e for e in a.events if "8:45 PM PDT Director" in e["raw"]]
    assert len(director_events) == 1


def test_tasks_and_events_conform_to_schema(schema: dict, parsed) -> None:
    """Validate ledger output shapes via the root schema (keeps $defs refs resolvable)."""
    activity = {
        "schema_version": "1.0.0",
        "generated_at": "2026-10-20T05:00:00-07:00",
        "project": "fencepost",
        "meta": {"github": "skipped"},
        "nodes": [],
        "tasks": parsed.tasks,
        "events": parsed.events,
        "edges": [],
        "unparsed": parsed.unparsed,
    }
    jsonschema.validate(instance=activity, schema=schema)
