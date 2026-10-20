"""Validate fixtures/sample-activity.json against schema/activity.schema.json."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schema" / "activity.schema.json"
FIXTURE_PATH = ROOT / "fixtures" / "sample-activity.json"
BOTS_PATH = ROOT / "config" / "bots.json"

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


def test_bots_config_has_thirteen_bots_plus_owner() -> None:
    with BOTS_PATH.open(encoding="utf-8") as f:
        bots_cfg = json.load(f)
    ids = {b["id"] for b in bots_cfg["bots"]}
    assert "manpreet" in ids
    assert REQUIRED_BOT_IDS <= ids
    assert len(bots_cfg["bots"]) == 14


def test_each_bot_has_signature_alias() -> None:
    with BOTS_PATH.open(encoding="utf-8") as f:
        bots_cfg = json.load(f)
    for bot in bots_cfg["bots"]:
        if bot["id"] == "manpreet":
            continue
        assert any(a.startswith("~") for a in bot["aliases"]), bot["id"]
