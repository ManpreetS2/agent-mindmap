"""
MM-008: end-to-end pipeline — ledger + GitHub fixtures → activity.json → web shape.

No network. Uses mocked `gh` (MockGh) and the committed ledger fixture.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

from ingest.build import build_activity, write_activity
from ingest.edges import pr_key
from tests.test_github_poller import MockGh

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "tests" / "fixtures" / "ledger-sample.md"
SCHEMA_PATH = ROOT / "schema" / "activity.schema.json"
BOTS_PATH = ROOT / "config" / "bots.json"
SAMPLE = ROOT / "fixtures" / "sample-activity.json"


@pytest.fixture
def bots() -> list[dict]:
    with BOTS_PATH.open(encoding="utf-8") as f:
        return json.load(f)["bots"]


@pytest.fixture
def schema() -> dict:
    with SCHEMA_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def test_e2e_fixture_pipeline_writes_schema_valid_activity(
    tmp_path: Path, bots: list[dict], schema: dict
) -> None:
    """Ledger fixture + mocked gh → activity.json the web app can load."""
    out = tmp_path / "activity.json"
    activity = build_activity(
        ledger_path=LEDGER,
        bots=bots,
        github_runner=MockGh(),
        cache_dir=tmp_path / "cache",
        generated_at="2026-10-20T12:00:00-07:00",
    )
    write_activity(activity, out)

    loaded = json.loads(out.read_text(encoding="utf-8"))
    jsonschema.validate(instance=loaded, schema=schema)

    assert loaded["schema_version"] == "1.1.0"
    from ingest.build import resolve_project_name

    assert loaded["project"] == resolve_project_name()
    assert loaded["meta"]["github"] == "ok"
    assert len(loaded["nodes"]) == len(bots)
    assert loaded["tasks"]
    assert loaded["events"]
    assert isinstance(loaded["edges"], list)
    assert isinstance(loaded["unparsed"], list)

    # Web loadActivity expects this top-level shape (no crash on parse).
    for key in (
        "schema_version",
        "generated_at",
        "project",
        "meta",
        "nodes",
        "tasks",
        "events",
        "edges",
        "unparsed",
    ):
        assert key in loaded

    # Attribution / join invariants from MM-004 rulings
    assert all(e["source"] != e["target"] for e in loaded["edges"])
    assert not any(
        e["type"] == "merge" and e["source"] == "manpreet" for e in loaded["edges"]
    )
    # GitHub-sourced events carry repo for (repo, number) joins
    gh_events = [
        e
        for e in loaded["events"]
        if str(e.get("source_url", "")).startswith("https://github.com/")
    ]
    assert gh_events
    assert all(e.get("repo") for e in gh_events if e.get("pr"))


def test_e2e_github_down_still_serves_ledger_only(
    tmp_path: Path, bots: list[dict], schema: dict
) -> None:
    activity = build_activity(
        ledger_path=LEDGER,
        bots=bots,
        github_runner=MockGh(fail=True),
        cache_dir=tmp_path / "cache",
        generated_at="2026-10-20T12:00:00-07:00",
    )
    out = tmp_path / "activity.json"
    write_activity(activity, out)
    loaded = json.loads(out.read_text(encoding="utf-8"))
    jsonschema.validate(instance=loaded, schema=schema)
    assert loaded["meta"]["github"] == "error"
    assert loaded["tasks"]
    assert not any(
        str(e.get("source_url", "")).startswith("https://github.com/")
        for e in loaded["events"]
    )


def test_pr_keys_are_repo_and_number(tmp_path: Path, bots: list[dict]) -> None:
    activity = build_activity(
        ledger_path=LEDGER,
        bots=bots,
        github_runner=MockGh(),
        cache_dir=tmp_path / "cache",
    )
    fp5 = [
        e
        for e in activity["events"]
        if e.get("pr") == 5 and e.get("repo") == "ManpreetS2/fencepost"
    ]
    assert fp5
    for e in fp5:
        assert pr_key(e) == ("ManpreetS2/fencepost", 5)


def test_make_refresh_demo_writes_public_activity(tmp_path: Path, schema: dict) -> None:
    """Makefile refresh-demo path: fixture ledger, skip GitHub, schema-valid out."""
    out = tmp_path / "activity.json"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "ingest",
            "--ledger",
            str(LEDGER),
            "--out",
            str(out),
            "--skip-github",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert out.is_file()
    loaded = json.loads(out.read_text(encoding="utf-8"))
    jsonschema.validate(instance=loaded, schema=schema)
    assert loaded["meta"]["github"] == "skipped"
    assert "wrote" in proc.stdout.lower()


def test_sample_fixture_still_valid_for_ui(schema: dict) -> None:
    """Hand-written sample used by UI unit tests remains schema-valid."""
    with SAMPLE.open(encoding="utf-8") as f:
        sample = json.load(f)
    jsonschema.validate(instance=sample, schema=schema)
