"""Generate synthetic, demo-mode T3 snapshots (1/2/12/30 agents) for visual QA.

Every snapshot is built with the real T3Projection in demo mode, so it is schema-valid, clearly
synthetic ("[SIMULATED]"-style demo labels via mode=demo) and never mistaken for live data.
Connections are deliberately sparse: only the listed parent/child pairs exist, so a mostly
disconnected network stays honestly disconnected.

Usage (from the repo root):  .venv/bin/python web/e2e/make_fixtures.py OUT_DIR
Writes OUT_DIR/{one,two,twelve,thirty}/activity.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from datetime import UTC, datetime

from ingest.t3 import T3Projection


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


NOW = 1792699200  # 2026-10-22T20:00:00Z, the documented frozen demo clock
STATUSES = ["running", "running", "waiting", "completed", "failed", "idle", "completed", "running"]
TITLES = [
    "Implement read-only adapter", "Review adapter tests", "Refactor graph renderer", "Fix flaky replay test",
    "Write migration notes", "Audit dependency licences", "Profile canvas frame time", "Draft release checklist",
    "Investigate SSE reconnect", "Tidy roster styles", "Verify keyboard navigation", "Summarise PR feedback",
]
MODELS = {"codex": ["demo-codex-model", "demo-codex-mini"], "claudeAgent": ["demo-claude-model", "demo-claude-fast"]}


def thread(i: int, parent: int | None) -> dict:
    driver = "codex" if i % 2 == 0 else "claudeAgent"
    created = NOW - 3600 + i * 40
    return {
        "projectId": "demo-project", "projectTitle": "DEMO · agent-mindmap",
        "title": f"{TITLES[i % len(TITLES)]}{'' if i < len(TITLES) else f' #{i // len(TITLES) + 1}'}",
        "status": STATUSES[i % len(STATUSES)],
        "updatedAt": _iso(NOW - (i % 5) * 20), "createdAt": _iso(created),
        "providerInstanceId": driver, "model": MODELS[driver][i % 2], "branch": f"demo/task-{i}",
        "parentThreadId": f"demo-{parent}" if parent is not None else None,
        "relationshipToParent": "subagent" if parent is not None else None,
        "linkedPullRequest": None, "threadId": f"demo-{i}",
    }


def snapshot(count: int, parents: dict[int, int]) -> dict:
    raw = {
        "environment": {"serverVersion": "DEMO"},
        "providers": [{"providerInstanceId": "codex", "driverKind": "codex"},
                      {"providerInstanceId": "claudeAgent", "driverKind": "claudeAgent"}],
        "threads": [thread(i, parents.get(i)) for i in range(count)],
    }
    return T3Projection("t3-demo-fixture", demo=True).snapshot(raw, NOW)


SETS = {
    "one": (1, {}),
    "two": (2, {1: 0}),
    # 12 agents, three small delegation trees and several isolated agents
    "twelve": (12, {1: 0, 2: 0, 4: 3, 6: 5, 7: 5}),
    # 30 agents: a few trees, many agents with no relationships at all
    "thirty": (30, {1: 0, 2: 0, 3: 0, 5: 4, 6: 4, 7: 6, 9: 8, 10: 8, 12: 11, 13: 11, 14: 13, 20: 19, 21: 19}),
}

if __name__ == "__main__":
    out = Path(sys.argv[1])
    for name, (count, parents) in SETS.items():
        target = out / name
        target.mkdir(parents=True, exist_ok=True)
        (target / "activity.json").write_text(json.dumps(snapshot(count, parents), indent=2) + "\n")
        print(f"{name}: {count} agents, {len(parents)} delegation edges -> {target}/activity.json")
