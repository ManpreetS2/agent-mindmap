"""The /observability.json contract: schema, fixtures, and privacy invariants shared by backend and UI."""
import json
import re
from pathlib import Path

import pytest
from jsonschema import Draft7Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schema/observability.schema.json").read_text())
FIXTURES = sorted((ROOT / "fixtures/observability").glob("*.json"))
POOLS = ["claude-1", "claude-2", "cursor-premium", "devin-free", "codex"]
PRIVATE = re.compile(r"/Users/|/home/|\.t3|\.config|\.claude|@[A-Za-z0-9.-]+\.[a-z]{2,}|Bearer |sk-[A-Za-z0-9]|gh[pousr]_", re.I)


def test_schema_is_valid_draft7():
    Draft7Validator.check_schema(SCHEMA)


def test_fixture_matrix_covers_required_states():
    assert {f.stem for f in FIXTURES} >= {"demo", "live-mixed", "live-all-unknown", "live-collector-down", "reader-other-owner"}


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_fixture_validates_and_is_private(path):
    doc = json.loads(path.read_text())
    errors = list(Draft7Validator(SCHEMA).iter_errors(doc))
    assert not errors, errors[0].message
    assert [p["id"] for p in doc["quota"]["pools"]] == POOLS  # five separate pools, fixed order, never merged
    assert not PRIVATE.search(path.read_text())
    for pool in doc["quota"]["pools"]:
        if pool["status"] in {"UNKNOWN", "UNSUPPORTED", "ERROR"}:
            assert pool["windows"] == [] and pool["reason"], pool["id"]  # honest missing data: no fabricated numbers
        if pool["status"] == "VERIFIED":
            assert pool["source"]["supported_programmatically"] and pool["observed_at"] and pool["expires_at"]
        for w in pool["windows"]:
            assert w["used_pct"] is None or abs(w["used_pct"] + (w["remaining_pct"] or 0) - 100) < 0.11


def test_demo_fixture_is_labelled_synthetic():
    demo = json.loads((ROOT / "fixtures/observability/demo.json").read_text())
    assert demo["mode"] == "demo" and demo["machine"]["platform"] == "synthetic"
    assert any("synthetic" in n.lower() for n in demo["notes"])
    assert all(p["status"] != "VERIFIED" for p in demo["quota"]["pools"])  # a demo may never claim a verified reading


def test_claude_accounts_are_never_merged():
    for f in FIXTURES:
        pools = {p["id"]: p for p in json.loads(f.read_text())["quota"]["pools"]}
        assert pools["claude-1"]["account_alias"] != pools["claude-2"]["account_alias"]
