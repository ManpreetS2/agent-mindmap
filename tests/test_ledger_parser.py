"""Golden tests for ingest/ledger_parser.py (MM-002) against the real ledger snapshot."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import jsonschema
import pytest

from ingest.ledger_parser import (
    NOTE_RE,
    STRUCTURED_PDT_RE,
    extract_task_id,
    is_valid_task_id,
    parse_ledger,
    parse_ledger_file,
    task_id_from_column,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "ledger-sample.md"
SCHEMA_PATH = ROOT / "schema" / "activity.schema.json"

# Per-type counts for events[] on the sanitized real-ledger fixture.
EXPECTED_EVENT_TYPE_COUNTS = {
    "assigned": 2,
    "handoff": 2,
    "merged": 5,
    "blocker": 3,
    "verdict": 8,  # includes CONDITIONAL (QA-MM004-2 verdict tokens)
    "note": 25,
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


def test_fixture_uses_real_ledger_header(fixture_text: str) -> None:
    assert "| Task ID | Project | Owner | Mode | Model | Status | Evidence |" in fixture_text
    assert "| ID | Title |" not in fixture_text


def test_every_table_row_becomes_a_task(parsed) -> None:
    ids = {t["id"] for t in parsed.tasks}
    assert ids == {
        "BD-000",
        "QR-000",
        "RP-001",
        "RP-002",
        "RP-003",
        "RP-004",
        "RP-005",
        "RP-006",
        "RP-007",
        "RP-008",
    }
    assert len(parsed.tasks) == 10
    for task in parsed.tasks:
        assert is_valid_task_id(task["id"])
    by_id = {t["id"]: t for t in parsed.tasks}
    assert by_id["RP-001"]["status"] == "DONE"
    assert by_id["RP-003"]["status"] == "IN_REVIEW"
    assert by_id["RP-004"]["status"] == "IDLE"  # PLANNED
    assert by_id["RP-004"]["title"].startswith("FENCEPOST:")


def test_four_note_variants_from_real_ledger(parsed) -> None:
    variants = {
        "no_comma": (
            "- 2026-10-19 8:45 PM PDT Director: one-time exception approved. "
            "DEV 2 may push a single bootstrap commit to main in ManpreetS2/fencepost "
            '(README.md "# fencepost" only), because the repo is empty and PRs need a base branch. '
            "All later work goes through PRs, with no pushes to main."
        ),
        "comma": (
            "- 2026-10-19 8:58 PM PDT, Architect: AUTHORIZED in writing to run RP-003 on "
            "`cursor-grok-4.5-high` (non-fast). This replaces Composer 2.5 for RP-003 because "
            "it's a complex Docker and Compose task. If the CLI doesn't have that exact ID, "
            "fall back to `composer-2.5`. Never use -fast or auto."
        ),
        "24h_no_actor": (
            "- 2026-10-19 21:35 PDT: CLOUD SWITCH executed early per Manpreet directive. "
            "All bots on Cursor Cloud, one cloud chat per bot, composer-2.5 / cursor-grok-4.5-high "
            "only (no Fast/Auto). All prior limits retained. 9:50 routine deleted. Verification pending."
        ),
        "correction": (
            "- 2026-10-19 9:21 PM PDT, Architect CORRECTION: the canonical array name is `txns` "
            "(as in the merged schema and the plan), not `transactions`. RP-004 and RP-005 build "
            "against `txns`. QA-RP002-1 is being fixed in RP-002a (UUID pattern), and the contracts "
            "lock waits on RP-002a merging."
        ),
    }
    for label, line in variants.items():
        assert NOTE_RE.match(line), label
        assert any(e["raw"] == line for e in parsed.events), label

    assert next(e for e in parsed.events if e["raw"] == variants["no_comma"])["actor"] == "director"
    assert next(e for e in parsed.events if e["raw"] == variants["comma"])["actor"] == "architect"
    assert next(e for e in parsed.events if e["raw"] == variants["24h_no_actor"])["actor"] is None
    corr = next(e for e in parsed.events if e["raw"] == variants["correction"])
    assert corr["actor"] == "architect"
    assert corr["type"] == "note"


def test_structured_pdt_handoff_from_real_ledger(parsed) -> None:
    line = (
        "- 2026-10-19 22:52 PDT | Architect | handoff | MM-002 | "
        "IN_REVIEW PR #4 14b5831 -> QA. MM-003 started in bc-6c5db6e1."
    )
    assert STRUCTURED_PDT_RE.match(line)
    evt = next(e for e in parsed.events if e["raw"] == line)
    assert evt["type"] == "handoff"
    assert evt["actor"] == "architect"
    assert evt["task_id"] == "MM-002"
    assert evt["target"] == "qa-verifier"
    assert evt["attribution"]["method"] == "ledger_owner"


def test_structured_task_id_from_column_not_body() -> None:
    """QA-MM002-11: body IDs must not override the task column."""
    text = (
        "| Task ID | Project | Owner | Mode | Model | Status | Evidence |\n"
        "|---|---|---|---|---|---|---|\n"
        "| MM-001 | MINDMAP: schema | Architect | a | m | PLANNED | — |\n\n"
        "- 2026-10-19 22:52 PDT | Architect | handoff | MM-002 | "
        "mentions RP-004 and MM-001 in the body -> QA.\n"
        "- 2026-10-19T22:00:00-07:00 | Architect | note | MM-003 | "
        "body cites RP-005 and QA-RP004-1 only.\n"
    )
    result = parse_ledger(text)
    handoff = next(e for e in result.events if e["type"] == "handoff")
    assert handoff["task_id"] == "MM-002"
    assert handoff["target"] == "qa-verifier"
    note = next(e for e in result.events if e["type"] == "note" and "QA-RP004-1" in e["raw"])
    assert note["task_id"] == "MM-003"
    assert note["target"] is None


def test_structured_target_at_mention_and_null() -> None:
    text = (
        "- 2026-10-19 22:00 PDT | Director | handoff | MM-001 | ping @Architect for review.\n"
        "- 2026-10-19 22:01 PDT | Director | handoff | MM-001 | no target mentioned at all.\n"
    )
    result = parse_ledger(text)
    events = [e for e in result.events if e["type"] == "handoff"]
    assert events[0]["target"] == "architect"
    assert events[1]["target"] is None


def test_task_id_word_boundaries() -> None:
    """QA-MM002-12: 'xRP-004' must not match."""
    assert extract_task_id("see RP-004 please") == "RP-004"
    assert extract_task_id("xRP-004") is None
    assert extract_task_id("foo xRP-004 bar") is None
    assert task_id_from_column("xRP-004") is None
    assert task_id_from_column("MM-002/MM-003") == "MM-002"


def test_undated_and_prose_go_to_unparsed(parsed) -> None:
    unparsed_raws = {e["raw"] for e in parsed.unparsed}
    assert any(r.startswith("Active coding workers:") for r in unparsed_raws)
    assert any(r.startswith("- UI/UX Maker:") for r in unparsed_raws)
    for evt in parsed.unparsed:
        assert evt["type"] == "unparsed"


def test_no_line_lost(parsed) -> None:
    assert len(parsed.parsed_lines) + len(parsed.unparsed_lines) == len(parsed.input_lines)


def test_event_ids_stable_across_runs(fixture_text: str) -> None:
    a = parse_ledger(fixture_text, source_url="build/task-ledger.md")
    b = parse_ledger(fixture_text, source_url="build/task-ledger.md")
    assert [e["id"] for e in a.events] == [e["id"] for e in b.events]
    assert [e["id"] for e in a.unparsed] == [e["id"] for e in b.unparsed]


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
    assert dict(counts) == EXPECTED_EVENT_TYPE_COUNTS


def test_malformed_time_isolated_snippet_does_not_raise() -> None:
    text = (
        "| Task ID | Project | Owner | Mode | Model | Status | Evidence |\n"
        "|---|---|---|---|---|---|---|\n"
        "| MM-002 | x | Architect | a | m | PLANNED | — |\n\n"
        "- 2026-10-19 13:00 PM PDT Director: boom\n"
        "- 2026-10-19 9:00 PM PDT Director: GO for Architect on MM-002 ok.\n"
    )
    result = parse_ledger(text)
    assert len(result.tasks) == 1
    assert any(e["type"] == "assigned" for e in result.events)
    assert "malformed_time" in result.unparsed_reasons
