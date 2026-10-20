"""
Build activity.json from the ledger parser + GitHub poller (MM-004 / MM-010).

Validates against schema/activity.schema.json and writes atomically.
No network secrets; GitHub access is via the poller's `gh api` runner.
Ledger may be a local path or the allowlisted `data/ledger` mirror via gh.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .attribute import load_bots
from .edges import derive_edges
from .github_poller import GhRunner, GitHubPollResult, poll_github
from .ledger_fetch import LEDGER_SOURCE_URL, LedgerFetchResult, fetch_ledger_from_gh
from .ledger_parser import (
    LedgerParseResult,
    ledger_last_entry_at,
    parse_ledger,
    parse_ledger_file,
)
from .membership import membership_index
from .migrate import migrate_activity

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schema" / "activity.schema.json"
DEFAULT_OUT = ROOT / "web" / "public" / "activity.json"
DEFAULT_BOTS = ROOT / "config" / "bots.json"


def resolve_project_name(
    *,
    repo_root: Path | None = None,
    env: dict[str, str] | None = None,
) -> str:
    """
    MM-020k / QA-MM020g-7: app name from env or configured GitHub repo slug.

    Order: MINDMAP_PROJECT → LEDGER_REPO slug (agent-mindmap) → directory name.
    Never hardcodes the Fencepost brand.
    """
    environ = env if env is not None else os.environ
    override = (environ.get("MINDMAP_PROJECT") or "").strip()
    if override:
        return override
    try:
        from .ledger_fetch import LEDGER_REPO

        slug = LEDGER_REPO.rsplit("/", 1)[-1].strip()
        if slug:
            return slug
    except Exception:  # noqa: BLE001
        pass
    root = repo_root if repo_root is not None else ROOT
    name = root.resolve().name.strip()
    if name and name.lower() not in {"workspace", "repo", "src", "app", "."}:
        return name
    return "agent-mindmap"


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
    *,
    membership: dict[str, list[str]] | None = None,
) -> list[dict[str, Any]]:
    """Roster nodes at fixed layout positions with best-effort status/task.

    One node per bot identity. `group` remains the layout/home group;
    `groups` carries full membership from config/groups.json (MM-020a).
    """
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

    member_of = membership if membership is not None else membership_index()

    nodes: list[dict[str, Any]] = []
    for bot in bots:
        bot_id = bot["id"]
        groups = list(member_of.get(bot_id, []))
        node: dict[str, Any] = {
            "id": bot_id,
            "label": bot["display_name"],
            "group": bot["group"],
            "groups": groups,
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
    ledger_path: Path | None = None,
    ledger_text: str | None = None,
    ledger_source_url: str = "build/task-ledger.md",
    meta_ledger: str = "ok",
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

    if ledger_text is not None:
        ledger = parse_ledger(
            ledger_text, source_url=ledger_source_url, bots=bot_list
        )
    elif ledger_path is not None:
        ledger = parse_ledger_file(
            ledger_path, source_url=ledger_source_url, bots=bot_list
        )
    else:
        raise ValueError("ledger_path or ledger_text is required")

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

    meta: dict[str, Any] = {
        "github": gh.meta_github,
        "ledger": meta_ledger,
        "ledger_last_entry_at": ledger_last_entry_at(ledger),
    }

    activity = {
        "schema_version": "1.1.0",
        "generated_at": ts,
        "project": resolve_project_name(),
        "meta": meta,
        "nodes": nodes,
        "tasks": ledger.tasks,
        "events": events,
        "edges": edges,
        "unparsed": ledger.unparsed,
    }
    # Stamp required provenance on 1.1.0 events (Director / MM-020a migration rules).
    return migrate_activity(activity)


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


def resolve_ledger_path(
    cli_ledger: Path | None,
    env: dict[str, str] | None = None,
) -> Path | None:
    """Return --ledger PATH, else MINDMAP_LEDGER, else None (QA-MM004-3)."""
    if cli_ledger is not None:
        return cli_ledger
    environ = env if env is not None else os.environ
    raw = environ.get("MINDMAP_LEDGER")
    if raw:
        return Path(raw)
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build MINDMAP activity.json")
    parser.add_argument(
        "--ledger",
        type=Path,
        default=None,
        help="Path to task-ledger.md (or set MINDMAP_LEDGER)",
    )
    parser.add_argument(
        "--ledger-source",
        choices=("path", "gh"),
        default="path",
        help="path (default) or gh (data/ledger mirror via gh api)",
    )
    parser.add_argument(
        "--out",
        "--activity-out",
        type=Path,
        dest="out",
        default=DEFAULT_OUT,
        help="Output activity.json path",
    )
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument("--bots", type=Path, default=DEFAULT_BOTS)
    parser.add_argument("--skip-github", action="store_true")
    args = parser.parse_args(argv)

    with args.bots.open(encoding="utf-8") as f:
        bots = json.load(f)["bots"]

    ledger_text: str | None = None
    ledger_path: Path | None = None
    ledger_url = "build/task-ledger.md"
    meta_ledger = "ok"

    if args.ledger_source == "gh":
        fetched: LedgerFetchResult = fetch_ledger_from_gh(cache_dir=args.cache_dir)
        meta_ledger = fetched.meta_ledger
        ledger_url = LEDGER_SOURCE_URL
        if fetched.text is None:
            # Ledger error: still emit a snapshot if we can skip (empty ledger)
            # so the UI can show meta.ledger=error.
            activity = build_activity(
                ledger_text="",
                ledger_source_url=ledger_url,
                meta_ledger="error",
                bots=bots,
                cache_dir=args.cache_dir,
                skip_github=args.skip_github,
            )
            # Re-parse empty intentionally — meta already set
            activity["meta"]["ledger"] = "error"
            activity["meta"]["ledger_last_entry_at"] = None
            try:
                write_activity(activity, args.out)
            except Exception as exc:  # noqa: BLE001
                print(f"failed to write activity: {exc}", file=sys.stderr)
                return 1
            print(
                f"wrote {args.out} (github={activity['meta']['github']}, "
                f"ledger=error)",
                file=sys.stderr,
            )
            return 1
        ledger_text = fetched.text
    else:
        ledger_path = resolve_ledger_path(args.ledger)
        if ledger_path is None:
            print(
                "error: provide --ledger PATH or set the MINDMAP_LEDGER "
                "environment variable (or use --ledger-source gh)",
                file=sys.stderr,
            )
            return 2
        if not ledger_path.is_file():
            print(f"ledger not found: {ledger_path}", file=sys.stderr)
            return 1
        ledger_url = str(ledger_path).replace("\\", "/")

    activity = build_activity(
        ledger_path=ledger_path,
        ledger_text=ledger_text,
        ledger_source_url=ledger_url,
        meta_ledger=meta_ledger,
        bots=bots,
        cache_dir=args.cache_dir,
        skip_github=args.skip_github,
    )
    try:
        write_activity(activity, args.out)
    except Exception as exc:  # noqa: BLE001
        print(f"failed to write activity: {exc}", file=sys.stderr)
        return 1
    print(
        f"wrote {args.out} (github={activity['meta']['github']}, "
        f"ledger={activity['meta']['ledger']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
