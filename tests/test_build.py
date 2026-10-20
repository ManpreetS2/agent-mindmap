"""MM-004: build.py combines ledger + GitHub into schema-valid activity.json."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from ingest.build import build_activity, write_activity
from ingest.edges import derive_edges
from ingest.github_poller import GhResponse
from tests.test_github_poller import MockGh, _fixture_map

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "tests" / "fixtures" / "ledger-sample.md"
SCHEMA_PATH = ROOT / "schema" / "activity.schema.json"
BOTS_PATH = ROOT / "config" / "bots.json"


@pytest.fixture
def bots() -> list[dict]:
    with BOTS_PATH.open(encoding="utf-8") as f:
        return json.load(f)["bots"]


@pytest.fixture
def schema() -> dict:
    with SCHEMA_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def test_build_activity_validates(tmp_path: Path, bots: list[dict], schema: dict) -> None:
    activity = build_activity(
        ledger_path=LEDGER,
        bots=bots,
        github_runner=MockGh(),
        cache_dir=tmp_path / "cache",
        generated_at="2026-10-20T06:00:00-07:00",
    )
    jsonschema.validate(instance=activity, schema=schema)
    assert activity["meta"]["github"] == "ok"
    assert activity["tasks"]
    assert activity["events"]
    assert activity["nodes"]
    assert len(activity["nodes"]) == len(bots)
    edge_types = {e["type"] for e in activity["edges"]}
    assert edge_types <= {"handoff", "verdict", "pr", "merge"}
    assert "handoff" in edge_types or "verdict" in edge_types


def test_github_down_ledger_only_meta_error(
    tmp_path: Path, bots: list[dict], schema: dict
) -> None:
    activity = build_activity(
        ledger_path=LEDGER,
        bots=bots,
        github_runner=MockGh(fail=True),
        cache_dir=tmp_path / "cache",
        generated_at="2026-10-20T06:00:00-07:00",
    )
    assert activity["meta"]["github"] == "error"
    assert activity["tasks"]  # ledger still present
    # Poller contributed no GitHub-sourced events (ledger-only snapshot)
    assert not any(
        str(e.get("source_url", "")).startswith("https://github.com/")
        for e in activity["events"]
    )
    jsonschema.validate(instance=activity, schema=schema)

    out = tmp_path / "activity.json"
    write_activity(activity, out)
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["meta"]["github"] == "error"


def test_event_ids_stable_across_runs(tmp_path: Path, bots: list[dict]) -> None:
    runner = MockGh()
    a = build_activity(
        ledger_path=LEDGER,
        bots=bots,
        github_runner=runner,
        cache_dir=tmp_path / "cache-a",
        generated_at="2026-10-20T06:00:00-07:00",
    )
    b = build_activity(
        ledger_path=LEDGER,
        bots=bots,
        github_runner=MockGh(),  # fresh etag state; fixtures identical
        cache_dir=tmp_path / "cache-b",
        generated_at="2026-10-20T07:00:00-07:00",
    )
    assert [e["id"] for e in a["events"]] == [e["id"] for e in b["events"]]
    assert [e["id"] for e in a["unparsed"]] == [e["id"] for e in b["unparsed"]]
    assert [e["id"] for e in a["edges"]] == [e["id"] for e in b["edges"]]


def test_derive_edges_merge_uses_pr_author() -> None:
    events = [
        {
            "id": "1",
            "type": "pr_opened",
            "actor": "dev-1",
            "target": None,
            "pr": 5,
        },
        {
            "id": "2",
            "type": "merged",
            "actor": "devops-release",
            "target": None,
            "pr": 5,
        },
        {
            "id": "3",
            "type": "handoff",
            "actor": "director",
            "target": "architect",
        },
    ]
    edges = derive_edges(events)
    merge = next(e for e in edges if e["type"] == "merge")
    assert merge["source"] == "devops-release"
    assert merge["target"] == "dev-1"
    handoff = next(e for e in edges if e["type"] == "handoff")
    assert handoff["count"] == 1
