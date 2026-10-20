"""
Build activity.json from the ledger parser + GitHub poller (MM-004).

Validates against schema/activity.schema.json and writes atomically.
No network secrets; GitHub access is via the poller's `gh api` runner.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .attribute import load_bots
from .edges import derive_edges
from .github_poller import GhRunner, GitHubPollResult, poll_github
from .ledger_parser import LedgerParseResult, parse_ledger_file

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schema" / "activity.schema.json"
DEFAULT_LEDGER = ROOT / "tests" / "fixtures" / "ledger-sample.md"
DEFAULT_OUT = ROOT / "web" / "public" / "activity.json"
DEFAULT_BOTS = ROOT / "config" / "bots.json"


def _load_schema() -> dict[str, Any]:
    with SCHEMA_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def validate_activity(activity: dict[str, Any], schema: dict[str, Any] | None = None) -> None:
    import jsonschema

    jsonschema.validate(instance=activity, schema=schema or _load_schema())


def _owner_to_bot_id(owner: str, bots: list[dict[str, Any]]) -> str | None:
    key = owner.strip().lower()
    for bot in bots:
        names = {bot["display_name"].lower(), bot["id"].lower(), *(a.lstrip("~").lower() for a in bot.get("aliases", []))}
        if key in names or any(key.startswith(n + ",") or key.startswith(n + " ") for n in names):
            return bot["id"]
    # Multi-owner cells like "QA, Security, DevOps" — no single node
    return None


def build_nodes(
    bots: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Roster nodes at fixed layout positions with best-effort status/task."""
    tasks_by_owner: dict[str, list[dict[str, Any]]] = {}
    for task in tasks:
        bot_id = _owner_to_bot_id(str(task.get("owner", "")), bots)
        if bot_id:
            tasks_by_owner.setdefault(bot_id, []).append(task)

    latest_by_actor: dict[str, str] = {}
    agent_links: dict[str, list[str]] = {}
    for evt in events:
        actor = evt.get("actor")
        ts = evt.get("source_time")
        if actor and ts:
            prev = latest_by_actor.get(actor)
            if prev is None or ts > prev:
                latest_by_actor[actor] = ts
        raw = evt.get("raw") or ""
        if actor and "bc-" in raw:
            import re

            for m in re.finditer(r"\bbc-[0-9a-f]+\b", raw, re.I):
                agent_links.setdefault(str(actor), [])
                if m.group(0) not in agent_links[str(actor)]:
                    agent_links[str(actor)].append(m.group(0))

    nodes: list[dict[str, Any]] = []
    for bot in bots:
        bot_id = bot["id"]
        node: dict[str, Any] = {
            "id": bot_id,
            "label": bot["display_name"],
            "group": bot["group"],
            "status": "IDLE",
            "agent_links": agent_links.get(bot_id, []),
            "layout": dict(bot["layout"]),
        }
        owned = tasks_by_owner.get(bot_id) or []
        if owned:
            # Prefer non-DONE, else last listed
            active = next((t for t in owned if t.get("status") not in {"DONE", "IDLE"}), owned[-1])
            node["current_task"] = active["id"]
            node["status"] = active.get("status") or "UNKNOWN"
        if bot_id in latest_by_actor:
            node["last_activity_ts"] = latest_by_actor[bot_id]
        nodes.append(node)
    return nodes


def merge_events(
    ledger: LedgerParseResult,
    github: GitHubPollResult,
) -> list[dict[str, Any]]:
    """Stable merge: ledger then github, de-duplicated by event id."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for evt in [*ledger.events, *github.events]:
        eid = evt["id"]
        if eid in seen:
            continue
        seen.add(eid)
        out.append(evt)
    return out


def build_activity(
    *,
    ledger_path: Path,
    bots: list[dict[str, Any]] | None = None,
    github_runner: GhRunner | None = None,
    cache_dir: Path | None = None,
    skip_github: bool = False,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """
    Combine ledger + GitHub into a schema-conformant activity snapshot.

    If GitHub fails or skip_github is True, still emit ledger-only data with
    meta.github set to 'error' or 'skipped'.
    """
    bot_list = bots if bots is not None else load_bots()
    ledger = parse_ledger_file(ledger_path, source_url="build/task-ledger.md", bots=bot_list)

    if skip_github:
        gh = GitHubPollResult(events=[], meta_github="skipped")
    else:
        try:
            gh = poll_github(cache_dir=cache_dir, bots=bot_list, runner=github_runner)
        except Exception as exc:  # noqa: BLE001
            gh = GitHubPollResult(
                events=[],
                meta_github="error",
                errors=[f"poll raised {type(exc).__name__}"],
            )

    events = merge_events(ledger, gh)
    edges = derive_edges(events)
    nodes = build_nodes(bot_list, ledger.tasks, events)
    ts = generated_at or datetime.now(timezone.utc).isoformat()

    return {
        "schema_version": "1.0.0",
        "generated_at": ts,
        "project": "fencepost",
        "meta": {"github": gh.meta_github},
        "nodes": nodes,
        "tasks": ledger.tasks,
        "events": events,
        "edges": edges,
        "unparsed": ledger.unparsed,
    }


def write_activity(activity: dict[str, Any], out_path: Path) -> None:
    """Validate then atomically write activity.json."""
    validate_activity(activity)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(activity, indent=2, sort_keys=False) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(out_path.parent),
        delete=False,
        prefix=".activity.",
        suffix=".tmp",
    ) as tmp:
        tmp.write(payload)
        tmp_name = tmp.name
    Path(tmp_name).replace(out_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build MINDMAP activity.json")
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument("--bots", type=Path, default=DEFAULT_BOTS)
    parser.add_argument("--skip-github", action="store_true")
    args = parser.parse_args(argv)

    if not args.ledger.is_file():
        print(f"ledger not found: {args.ledger}", file=sys.stderr)
        return 1

    with args.bots.open(encoding="utf-8") as f:
        bots = json.load(f)["bots"]

    activity = build_activity(
        ledger_path=args.ledger,
        bots=bots,
        cache_dir=args.cache_dir,
        skip_github=args.skip_github,
    )
    try:
        write_activity(activity, args.out)
    except Exception as exc:  # noqa: BLE001
        print(f"failed to write activity: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {args.out} (github={activity['meta']['github']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
