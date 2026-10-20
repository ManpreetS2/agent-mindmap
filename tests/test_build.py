"""MM-004: build.py combines ledger + GitHub into schema-valid activity.json."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from ingest.build import build_activity, main, resolve_ledger_path, write_activity
from ingest.edges import derive_edges
from tests.test_github_poller import MockGh

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
    assert edge_types <= {"handoff", "verdict", "pr", "merge", "message"}
    assert activity["schema_version"] == "1.1.0"
    # MM-020a: one identity; Director/Architect carry multi-membership
    by_id = {n["id"]: n for n in activity["nodes"]}
    assert set(by_id["director"]["groups"]) == {"build", "qr", "radar"}
    assert set(by_id["architect"]["groups"]) == {"build", "qr", "radar"}
    assert by_id["bug-fixer"]["groups"] == []
    # No self-loops anywhere
    assert all(e["source"] != e["target"] for e in activity["edges"])


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
    a = build_activity(
        ledger_path=LEDGER,
        bots=bots,
        github_runner=MockGh(),
        cache_dir=tmp_path / "cache-a",
        generated_at="2026-10-20T06:00:00-07:00",
    )
    b = build_activity(
        ledger_path=LEDGER,
        bots=bots,
        github_runner=MockGh(),
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
            "repo": "ManpreetS2/fencepost",
            "attribution": {"method": "signature"},
        },
        {
            "id": "2",
            "type": "merged",
            "actor": "devops-release",
            "target": None,
            "pr": 5,
            "repo": "ManpreetS2/fencepost",
            "attribution": {"method": "ledger_owner"},
            "source_url": "build/task-ledger.md",
        },
        {
            "id": "3",
            "type": "handoff",
            "actor": "director",
            "target": "architect",
            "attribution": {"method": "ledger_owner"},
        },
    ]
    edges = derive_edges(events)
    merge = next(e for e in edges if e["type"] == "merge")
    assert merge["source"] == "devops-release"
    assert merge["target"] == "dev-1"
    handoff = next(e for e in edges if e["type"] == "handoff")
    assert handoff["count"] == 1


def test_merge_edge_never_self_loop() -> None:
    """QA-MM004-1: when merger == PR author, keep merged event but emit no merge edge."""
    events = [
        {
            "id": "open",
            "type": "pr_opened",
            "actor": "dev-1",
            "pr": 5,
            "repo": "ManpreetS2/fencepost",
            "attribution": {"method": "signature"},
        },
        {
            "id": "merge",
            "type": "merged",
            "actor": "dev-1",
            "pr": 5,
            "repo": "ManpreetS2/fencepost",
            "attribution": {"method": "signature"},
            "source_url": "https://github.com/ManpreetS2/fencepost/pull/5",
        },
    ]
    edges = derive_edges(events)
    assert not any(e["type"] == "merge" for e in edges)
    assert all(e["source"] != e["target"] for e in edges)


def test_merge_unknown_merger_emits_no_edge() -> None:
    events = [
        {
            "id": "open",
            "type": "pr_opened",
            "actor": "dev-1",
            "pr": 5,
            "repo": "ManpreetS2/fencepost",
            "attribution": {"method": "signature"},
        },
        {
            "id": "merge",
            "type": "merged",
            "actor": None,
            "pr": 5,
            "repo": "ManpreetS2/fencepost",
            "attribution": {"method": "unknown"},
            "source_url": "https://github.com/ManpreetS2/fencepost/pull/5",
        },
    ]
    edges = derive_edges(events)
    assert not any(e["type"] == "merge" for e in edges)


def test_merged_by_owner_never_makes_merge_edge() -> None:
    """QA-MM004-7: ignore merged_by / manpreet — no manpreet→author merge edge."""
    events = [
        {
            "id": "open",
            "type": "pr_opened",
            "actor": "dev-1",
            "pr": 5,
            "repo": "ManpreetS2/fencepost",
            "attribution": {"method": "signature"},
        },
        {
            "id": "gh-merge",
            "type": "merged",
            "actor": "manpreet",
            "pr": 5,
            "repo": "ManpreetS2/fencepost",
            "attribution": {"method": "unknown"},
            "source_url": "https://github.com/ManpreetS2/fencepost/pull/5",
        },
    ]
    edges = derive_edges(events)
    assert not any(e["type"] == "merge" for e in edges)


def test_ledger_merged_provides_merger() -> None:
    """Ledger merged actor + github opened author → merge edge."""
    events = [
        {
            "id": "open",
            "type": "pr_opened",
            "actor": "dev-1",
            "pr": 5,
            "repo": "ManpreetS2/fencepost",
            "attribution": {"method": "signature"},
        },
        {
            "id": "gh-merge",
            "type": "merged",
            "actor": None,
            "pr": 5,
            "repo": "ManpreetS2/fencepost",
            "attribution": {"method": "unknown"},
            "source_url": "https://github.com/ManpreetS2/fencepost/pull/5",
        },
        {
            "id": "ledger-merge",
            "type": "merged",
            "actor": "architect",
            "pr": 5,
            "repo": "ManpreetS2/fencepost",
            "attribution": {"method": "ledger_owner"},
            "source_url": "build/task-ledger.md",
        },
    ]
    edges = derive_edges(events)
    merges = [e for e in edges if e["type"] == "merge"]
    assert len(merges) == 1
    assert merges[0]["source"] == "architect"
    assert merges[0]["target"] == "dev-1"


def test_cross_repo_pr_number_not_joined() -> None:
    """QA-MM004-8: fencepost #5 and agent-mindmap #5 must not share edges."""
    events = [
        {
            "id": "fp-open",
            "type": "pr_opened",
            "actor": "dev-1",
            "pr": 5,
            "repo": "ManpreetS2/fencepost",
            "attribution": {"method": "signature"},
        },
        {
            "id": "fp-merge",
            "type": "merged",
            "actor": "architect",
            "pr": 5,
            "repo": "ManpreetS2/fencepost",
            "attribution": {"method": "ledger_owner"},
            "source_url": "build/task-ledger.md",
        },
        {
            "id": "mm-open",
            "type": "pr_opened",
            "actor": "ui-ux-maker",
            "pr": 5,
            "repo": "ManpreetS2/agent-mindmap",
            "attribution": {"method": "signature"},
        },
        {
            "id": "mm-rev",
            "type": "verdict",
            "actor": "qa-verifier",
            "pr": 5,
            "repo": "ManpreetS2/agent-mindmap",
            "verdict": "PASS",
            "attribution": {"method": "signature"},
            "source_url": "https://github.com/ManpreetS2/agent-mindmap/pull/5",
        },
    ]
    edges = derive_edges(events)
    merge = next(e for e in edges if e["type"] == "merge")
    assert merge["source"] == "architect"
    assert merge["target"] == "dev-1"
    # Must not create architect→ui-ux-maker or qa→dev-1 cross-repo joins
    assert not any(
        e["type"] == "merge" and e["target"] == "ui-ux-maker" for e in edges
    )
    verdict = next(e for e in edges if e["type"] == "verdict")
    assert verdict["source"] == "qa-verifier"
    assert verdict["target"] == "ui-ux-maker"
    assert not any(
        e["type"] == "verdict" and e["target"] == "dev-1" for e in edges
    )


def test_signed_review_verdict_and_pr_edges() -> None:
    """QA-MM004-2: signed review → verdict reviewer→author and pr author→reviewer."""
    events = [
        {
            "id": "open",
            "type": "pr_opened",
            "actor": "dev-1",
            "pr": 6,
            "repo": "ManpreetS2/fencepost",
            "attribution": {"method": "signature"},
        },
        {
            "id": "rev",
            "type": "verdict",
            "actor": "security-engineer",
            "pr": 6,
            "repo": "ManpreetS2/fencepost",
            "verdict": "PASS",
            "attribution": {"method": "signature"},
            "source_url": "https://github.com/ManpreetS2/fencepost/pull/6",
        },
        {
            "id": "unsigned",
            "type": "note",
            "actor": None,
            "pr": 6,
            "repo": "ManpreetS2/fencepost",
            "attribution": {"method": "unknown"},
            "source_url": "https://github.com/ManpreetS2/fencepost/pull/6",
        },
    ]
    edges = derive_edges(events)
    verdict = next(e for e in edges if e["type"] == "verdict")
    assert verdict["source"] == "security-engineer"
    assert verdict["target"] == "dev-1"
    pr_edge = next(e for e in edges if e["type"] == "pr")
    assert pr_edge["source"] == "dev-1"
    assert pr_edge["target"] == "security-engineer"
    # Unknown attribution produces no edge
    assert all(e["source"] != "unknown" for e in edges)


def test_pr_edges_deduped_per_pair_per_pr() -> None:
    events = [
        {
            "id": "open",
            "type": "pr_opened",
            "actor": "dev-1",
            "pr": 6,
            "repo": "ManpreetS2/fencepost",
            "attribution": {"method": "signature"},
        },
        {
            "id": "r1",
            "type": "verdict",
            "actor": "qa-verifier",
            "pr": 6,
            "repo": "ManpreetS2/fencepost",
            "verdict": "CHANGES",
            "attribution": {"method": "signature"},
        },
        {
            "id": "r2",
            "type": "note",
            "actor": "qa-verifier",
            "pr": 6,
            "repo": "ManpreetS2/fencepost",
            "attribution": {"method": "signature"},
        },
    ]
    edges = derive_edges(events)
    pr_edges = [e for e in edges if e["type"] == "pr"]
    assert len(pr_edges) == 1
    assert pr_edges[0]["count"] == 1
    assert pr_edges[0]["source"] == "dev-1"
    assert pr_edges[0]["target"] == "qa-verifier"


def test_conditional_verdict_token_makes_verdict_edge() -> None:
    events = [
        {
            "id": "open",
            "type": "pr_opened",
            "actor": "dev-2",
            "pr": 3,
            "repo": "ManpreetS2/fencepost",
            "attribution": {"method": "signature"},
        },
        {
            "id": "rev",
            "type": "verdict",
            "actor": "architect",
            "pr": 3,
            "repo": "ManpreetS2/fencepost",
            "verdict": "CONDITIONAL",
            "attribution": {"method": "signature"},
        },
    ]
    edges = derive_edges(events)
    assert any(
        e["type"] == "verdict"
        and e["source"] == "architect"
        and e["target"] == "dev-2"
        for e in edges
    )


def test_build_requires_ledger_arg_or_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """QA-MM004-3: no fixture default; --ledger or MINDMAP_LEDGER required."""
    monkeypatch.delenv("MINDMAP_LEDGER", raising=False)
    assert resolve_ledger_path(None) is None
    assert resolve_ledger_path(None, env={}) is None
    assert resolve_ledger_path(Path("/tmp/x"), env={}) == Path("/tmp/x")
    assert resolve_ledger_path(None, env={"MINDMAP_LEDGER": "/tmp/y"}) == Path("/tmp/y")

    rc = main(["--out", str(tmp_path / "out.json"), "--skip-github"])
    assert rc == 2

    rc = main(
        [
            "--ledger",
            str(LEDGER),
            "--out",
            str(tmp_path / "out.json"),
            "--skip-github",
        ]
    )
    assert rc == 0
    assert (tmp_path / "out.json").is_file()


def test_build_uses_mindmap_ledger_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MINDMAP_LEDGER", str(LEDGER))
    out = tmp_path / "activity.json"
    rc = main(["--out", str(out), "--skip-github"])
    assert rc == 0
    assert out.is_file()
