"""The public Pages build may publish only the synthetic observability fixture.

The historical source patch is retained at docs/evidence/pages-observability-demo.patch.
The synthetic observability fixture is now integrated directly into the workflow.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github/workflows/pages-demo.yml").read_text()
PATCH = (ROOT / "docs/evidence/pages-observability-demo.patch").read_text()


def test_workflow_never_references_private_sources():
    for forbidden in ("latest.json", "agent-observability-private", ".local/share", ".config", "quota-snapshots", "state.json"):
        assert forbidden not in WORKFLOW and forbidden not in PATCH


def test_patch_publishes_only_the_synthetic_fixture_and_verifies_it():
    assert "fixtures/observability/demo.json" in PATCH and "web/dist/observability.json" in PATCH
    assert 'fixture.get("mode") != "demo"' in PATCH and 'q["status"] != "VERIFIED"' in PATCH
    assert 'o["mode"] == "demo"' in PATCH


def test_workflow_applies_the_observability_patch():
    assert "web/dist/observability.json" in WORKFLOW


def test_the_fixture_it_publishes_is_synthetic():
    doc = json.loads((ROOT / "fixtures/observability/demo.json").read_text())
    assert doc["mode"] == "demo" and doc["machine"]["platform"] == "synthetic"
    assert all(p["status"] != "VERIFIED" for p in doc["quota"]["pools"])
