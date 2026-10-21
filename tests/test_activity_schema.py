"""Validate fixtures/sample-activity.json against schema/activity.schema.json."""

from __future__ import annotations

import json
import re
from pathlib import Path

import jsonschema
import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schema" / "activity.schema.json"
FIXTURE_PATH = ROOT / "fixtures" / "sample-activity.json"
BOTS_PATH = ROOT / "config" / "bots.json"

TASK_ID_PATTERN_STANDARD = re.compile(r"^[A-Z]{2,}-[0-9]{3}[A-Za-z0-9]*(-[0-9]+)?$")
TASK_ID_PATTERN_BACKLOG = re.compile(r"^[A-Z]{2,}-[A-Z]{2}[0-9]{3}(-[0-9]+)?$")


def task_id_matches_pattern(task_id: str) -> bool:
    return bool(
        TASK_ID_PATTERN_STANDARD.fullmatch(task_id)
        or TASK_ID_PATTERN_BACKLOG.fullmatch(task_id)
    )

REQUIRED_BOT_IDS = {
    "director",
    "architect",
    "dev-1",
    "dev-2",
    "ui-ux-maker",
    "documentation",
    "qa-verifier",
    "security-engineer",
    "devops-release",
    "scout",
    "skeptic",
    "nomen",
    "bug-fixer",
}


@pytest.fixture(scope="module")
def activity_schema() -> dict:
    with SCHEMA_PATH.open(encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def sample_activity() -> dict:
    with FIXTURE_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def test_sample_activity_validates(activity_schema: dict, sample_activity: dict) -> None:
    jsonschema.validate(instance=sample_activity, schema=activity_schema)


def test_fixture_includes_pr5_merge_sha(sample_activity: dict) -> None:
    merged = [e for e in sample_activity["events"] if e.get("type") == "merged" and e.get("pr") == 5]
    assert len(merged) == 1
    assert merged[0]["sha"] == "693ebc7"


def test_bots_config_keeps_historical_ids_and_current_roster() -> None:
    with BOTS_PATH.open(encoding="utf-8") as f:
        bots_cfg = json.load(f)
    bots = bots_cfg["bots"]
    ids = {b["id"] for b in bots}
    assert "manpreet" in ids
    assert REQUIRED_BOT_IDS <= ids
    active = {
        b["id"]
        for b in bots
        if b.get("roster") != "historical" and b["id"] != "manpreet"
    }
    assert active == {
        "project-manager",
        "scout",
        "advocate",
        "skeptic",
        "bug-hunter",
        "engineering-researcher",
        "experiment-designer",
        "technical-tutor",
    }
    assert len(bots) == 20
    assert bots_cfg["schema_version"] in {"1.0.0", "1.1.0"}


def test_each_bot_has_signature_alias() -> None:
    with BOTS_PATH.open(encoding="utf-8") as f:
        bots_cfg = json.load(f)
    for bot in bots_cfg["bots"]:
        if bot["id"] == "manpreet":
            continue
        assert any(a.startswith("~") for a in bot["aliases"]), bot["id"]


def test_schema_accepts_both_activity_versions(activity_schema: dict) -> None:
    assert set(activity_schema["properties"]["schema_version"]["enum"]) == {
        "1.0.0",
        "1.1.0",
    }
    assert "message" in activity_schema["$defs"]["edgeType"]["enum"]
    assert "provenance" in activity_schema["$defs"]


@pytest.fixture(scope="module")
def task_id_schema(activity_schema: dict) -> dict:
    return activity_schema["$defs"]["taskId"]


@pytest.mark.parametrize(
    "task_id",
    [
        "RP-005D",
        "MM-001",
        "QA-RP004-1",
    ],
)
def test_task_id_accepts_valid_examples(task_id_schema: dict, task_id: str) -> None:
    Draft202012Validator(task_id_schema).validate(task_id)
    assert task_id_matches_pattern(task_id)


def test_task_id_rejects_invalid_example(task_id_schema: dict) -> None:
    invalid = "rp-004"
    with pytest.raises(jsonschema.ValidationError):
        Draft202012Validator(task_id_schema).validate(invalid)
    assert not task_id_matches_pattern(invalid)
