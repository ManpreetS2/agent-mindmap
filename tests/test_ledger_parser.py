"""Golden tests for ingest/ledger_parser.py (MM-002)."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import jsonschema
import pytest

from ingest.ledger_parser import (
    NOTE_RE,
    STRUCTURED_ISO_RE,
    STRUCTURED_PDT_RE,
    is_valid_task_id,
    parse_ledger,
    parse_ledger_file,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "ledger-sample.md"
SCHEMA_PATH = ROOT / "schema" / "activity.schema.json"

# Per-type counts for the sanitized golden fixture (events[] only).
# unparsed lines also produce a timeline `note` with a [reason] prefix.
EXPECTED_EVENT_TYPE_COUNTS = {
    "assigned": 1,  # GO for Architect (deduped)
    "handoff": 2,  # free-text handed to DEV 1 + structured PDT handoff
    "merged": 1,  # squash-merged 693ebc7
    "note": 3,  # Architect CORRECTION + 2 unparsed mirrors (malformed_time, undated)
    "verdict": 1,  # structured ISO QA verdict
    # prose "Active coding workers" also → note mirror
    # Wait: undated UI/UX + malformed + prose = 3 unparsed → 3 note mirrors
    # CORRECTION is type note from classifier → +1
    # So note = 1 (correction) + 3 (mirrors) = 4 if prose is included
}


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
    assert ids == {"RP-004", "RP-005", "RP-005D", "MM-001", "QA-RP004-1"}
    assert len(parsed.tasks) == 5
    for task in parsed.tasks:
        assert is_valid_task_id(task["id"])

    by_id = {t["id"]: t for t in parsed.tasks}
    assert by_id["RP-004"]["status"] == "IN_REVIEW"
    assert by_id["RP-004"]["prs"] == [6]
    assert by_id["RP-005"]["status"] == "DONE"
    assert by_id["RP-005"]["prs"] == [5]
    assert by_id["RP-005D"]["status"] == "BLOCKED"
    assert by_id["MM-001"]["status"] == "IDLE"
    assert by_id["QA-RP004-1"]["status"] == "IN_PROGRESS"


def test_task_ids_match_schema_patterns() -> None:
    assert is_valid_task_id("RP-005D")
    assert is_valid_task_id("MM-001")
    assert is_valid_task_id("QA-RP004-1")
    assert not is_valid_task_id("FOO-BAR")
    assert not is_valid_task_id("rp-004")


def test_four_note_variants_parsed(fixture_text: str, parsed) -> None:
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

    handoff = next(e for e in parsed.events if e["raw"] == variants["comma"])
    assert handoff["type"] == "handoff"
    assert handoff["actor"] == "architect"
    assert handoff["target"] == "dev-1"

    merged = next(e for e in parsed.events if e["raw"] == variants["24h_no_actor"])
    assert merged["type"] == "merged"
    assert merged["sha"] == "693ebc7"
    assert merged["attribution"]["method"] == "unknown"

    correction = next(e for e in parsed.events if e["raw"] == variants["correction"])
    assert correction["type"] == "note"
    assert correction["actor"] == "architect"


def test_structured_pdt_and_iso_handoff_and_verdict(parsed) -> None:
    pdt_handoff = (
        "- 2026-10-19 21:58 PDT | Director | handoff | MM-001 | "
        "to Architect for schema + bot roster (MM-001)."
    )
    iso_verdict = (
        "- 2026-10-19T21:40:00-07:00 | QA / Verifier | verdict | RP-005 | "
        "PASS after recheck of etag cache tests."
    )
    assert STRUCTURED_PDT_RE.match(pdt_handoff)
    assert STRUCTURED_ISO_RE.match(iso_verdict)

    ho = next(e for e in parsed.events if e["raw"] == pdt_handoff)
    assert ho["type"] == "handoff"
    assert ho["actor"] == "director"
    assert ho["target"] == "architect"
    assert ho["task_id"] == "MM-001"
    assert ho["attribution"]["method"] == "ledger_owner"

    verd = next(e for e in parsed.events if e["raw"] == iso_verdict)
    assert verd["type"] == "verdict"
    assert verd["actor"] == "qa-verifier"
    assert verd["verdict"] == "PASS"
    assert verd["task_id"] == "RP-005"


def test_malformed_time_becomes_unparsed_without_abort(parsed) -> None:
    bad = "- 2026-10-19 13:00 PM PDT Director: bad clock should not abort the parse."
    assert any(e["raw"] == bad for e in parsed.unparsed)
    assert "malformed_time" in parsed.unparsed_reasons
    # Parse of the rest still produced tasks + other events
    assert len(parsed.tasks) >= 4
    assert any(e["type"] == "merged" for e in parsed.events)


def test_malformed_time_isolated_snippet_does_not_raise() -> None:
    text = (
        "# t\n\n"
        "| ID | Title | Owner | Mode | Model | Status | Evidence |\n"
        "|----|-------|-------|------|-------|--------|----------|\n"
        "| MM-002 | x | Architect | a | m | PLANNED | — |\n\n"
        "- 2026-10-19 13:00 PM PDT Director: boom\n"
        "- 2026-10-19 9:00 PM PDT Director: GO for Architect on MM-002 ok.\n"
    )
    result = parse_ledger(text)
    assert len(result.tasks) == 1
    assert any(e["type"] == "assigned" for e in result.events)
    assert any(r == "malformed_time" for r in result.unparsed_reasons)


def test_undated_and_prose_go_to_unparsed(parsed) -> None:
    unparsed_raws = {e["raw"] for e in parsed.unparsed}
    assert "Active coding workers: 0 of 2 (DEV 1 idle after merge)." in unparsed_raws
    assert "- UI/UX Maker: approved backup coder for design-spec polish." in unparsed_raws
    for evt in parsed.unparsed:
        assert evt["type"] == "unparsed"
        assert evt["attribution"]["method"] == "unknown"


def test_no_line_lost(parsed) -> None:
    assert len(parsed.input_lines) > 0
    assert len(parsed.parsed_lines) + len(parsed.unparsed_lines) == len(parsed.input_lines)


def test_event_ids_stable_across_runs(fixture_text: str) -> None:
    a = parse_ledger(fixture_text, source_url="build/task-ledger.md")
    b = parse_ledger(fixture_text, source_url="build/task-ledger.md")
    assert [e["id"] for e in a.events] == [e["id"] for e in b.events]
    assert [e["id"] for e in a.unparsed] == [e["id"] for e in b.unparsed]
    director_lines = [line for line in a.parsed_lines if "8:45 PM PDT Director" in line]
    assert len(director_lines) == 2
    director_events = [e for e in a.events if e["raw"].endswith(
        "GO for Architect on MM-001 schema work."
    ) and "8:45" in e["raw"]]
    assert len(director_events) == 1


def test_parser_output_validates_against_mm001_schema(schema: dict, parsed) -> None:
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


def test_per_type_event_counts(parsed) -> None:
    counts = Counter(e["type"] for e in parsed.events)
    # Core classified types from the golden fixture
    assert counts["assigned"] == 1
    assert counts["handoff"] == 2
    assert counts["merged"] == 1
    assert counts["verdict"] == 1
    # Architect CORRECTION (note) + one timeline note per unparsed line
    unparsed_n = len(parsed.unparsed)
    assert counts["note"] == 1 + unparsed_n
    assert unparsed_n == 3  # prose, undated UI/UX, malformed_time
    assert dict(counts) == {
        "assigned": 1,
        "handoff": 2,
        "merged": 1,
        "verdict": 1,
        "note": 4,
    }
