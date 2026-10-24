"""Export a minimal, read-only T3 activity feed for a SEPARATE PRIVATE repository.

This never publishes to GitHub, writes inside agent-mindmap, or exposes credentials.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ingest.t3 import safe_ident, safe_text, timestamp

ROOT = Path(__file__).resolve().parents[1]
# Each subscription is its own resource pool. They are never merged, and nothing is guessed.
QUOTA_POOLS = ("claude-1", "claude-2", "cursor-premium", "devin-free", "codex")
QUOTA_FILE = Path.home() / ".config" / "agent-mindmap" / "quota-snapshots.json"
QUOTA_MAX_AGE_SEC = 24 * 3600
TRUST_WINDOW_SEC = 15 * 60  # a reader must treat the feed as stale this long after the OBSERVATION (not the export)
VALID_STATES = {"IDLE", "IN_PROGRESS", "IN_REVIEW", "BLOCKED", "DONE", "UNKNOWN", "FAILED", "STALE"}


def load_quota_pools(path: Path | None = QUOTA_FILE, *, now: datetime | None = None) -> dict:
    """Manually entered, explicitly sourced and timestamped quota snapshots. No file or a bad entry = UNKNOWN.

    Expected file: {"pools": {"claude-1": {"source": "...", "observed_at": "<ISO>",
    "five_hour_used_pct": 0-100, "weekly_used_pct": 0-100}}}. Never read from credential stores.
    """
    current = now or datetime.now(UTC)
    pools = {name: {"status": "UNKNOWN", "note": "No sourced, timestamped snapshot available"} for name in QUOTA_POOLS}
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8")) if path else {}
        entries = raw.get("pools") if isinstance(raw, dict) else None
    except (OSError, ValueError, RecursionError):
        return pools
    if not isinstance(entries, dict):
        return pools
    for name in QUOTA_POOLS:
        entry = entries.get(name)
        if not isinstance(entry, dict):
            continue
        source = safe_text(entry.get("source"), 80)
        observed = timestamp(entry.get("observed_at"))
        if not source or source.startswith("[") or observed is None:
            continue
        age = (current - datetime.fromisoformat(observed)).total_seconds()
        if age < -60:
            continue  # a timestamp from the future is not evidence
        values = {}
        for key in ("five_hour_used_pct", "weekly_used_pct"):
            v = entry.get(key)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 100:
                values[key] = float(v)
        if not values:
            continue
        pools[name] = {
            "status": "MANUAL" if age <= QUOTA_MAX_AGE_SEC else "STALE_MANUAL",
            "source": source, "observed_at": observed, **values,
            "note": "Manually entered; not a live provider reading",
        }
    return pools


def make_feed(activity: dict, *, now: datetime | None = None, quota_pools: dict | None = None) -> tuple[dict, str]:
    """Allowlist fields, validate source, and label incomplete or stale observations."""
    from jsonschema import validate

    validate(activity, json.loads((ROOT / "schema/activity.schema.json").read_text()))
    t3 = activity.get("meta", {}).get("t3")
    if not isinstance(t3, dict) or t3.get("mode") != "live":
        raise ValueError("Only real T3 snapshots may be exported to the private feed")
    generated = timestamp(activity.get("generated_at"))
    if generated is None:
        raise ValueError("Invalid observation timestamp")
    current = now or datetime.now(UTC)
    age = (current - datetime.fromisoformat(generated)).total_seconds()
    if age < -60:
        raise ValueError("Observation timestamp is in the future; refusing to call it fresh")
    age = max(0, age)
    connected = t3.get("connection") == "connected"
    freshness = "fresh" if connected and age <= 120 else "stale"
    observed_dt = datetime.fromisoformat(generated)
    trusted_until = observed_dt + timedelta(seconds=TRUST_WINDOW_SEC) if freshness == "fresh" else current

    sessions = []
    for node in activity.get("nodes", [])[:500]:
        session = node.get("session")
        if not isinstance(session, dict):
            continue
        ident = safe_ident(node.get("id"))
        if not ident:
            continue
        sessions.append({
            "id": ident,
            "provider": safe_text(session.get("provider")) or "UNKNOWN",
            "model": safe_text(session.get("model")) or "UNKNOWN",
            "project": safe_text(session.get("project")) or "UNKNOWN",
            "task": safe_text(node.get("current_task")) or "UNKNOWN",
            "branch": safe_text(session.get("branch")) or "UNKNOWN",
            "pull_request": "UNKNOWN",
            "status": node["status"] if node.get("status") in VALID_STATES else "UNKNOWN",
            "last_activity_at": timestamp(node.get("last_activity_ts")),
            "stale": bool(session.get("stale")) or freshness == "stale",
        })
    sessions.sort(key=lambda s: s["id"])
    known = {s["id"] for s in sessions}
    delegations = []
    for edge in activity.get("edges", []):
        if edge.get("type") == "delegation" and edge.get("source") in known and edge.get("target") in known:
            delegations.append({"from": edge["source"], "to": edge["target"]})
    counts = dict(sorted(Counter(s["status"] for s in sessions).items()))
    feed = {
        "format": "agent-mindmap-private-feed/v1",
        "source": "T3 read-only metadata",
        "observed_at": generated,
        "exported_at": current.isoformat(),
        "freshness": freshness,
        "connection": "connected" if connected else "unavailable",
        "trusted_until": trusted_until.isoformat(),
        "reader_guidance": "Compare the current time with exported_at: past trusted_until, treat every session as "
                           "UNVERIFIED. Absence of a session is not evidence of idleness.",
        "quota": {
            "status": "unsupported",
            "note": "T3 read-only MCP does not expose subscription usage; pools below are manual snapshots or UNKNOWN",
            "pools": quota_pools if quota_pools is not None else load_quota_pools(now=current),
        },
        "limitations": [
            "T3 thread updates are not proof of actual tool execution",
            "Unseen external Cursor/Devin sessions cannot be inferred as idle",
            "The provider label does not uniquely identify two memberships",
            "Pull-request links are not exposed by T3 metadata (UNKNOWN)",
            "Each quota pool is separate; one account's quota is never the combined allowance",
        ],
        "status_counts": counts,
        "sessions": sessions,
        "delegations": delegations,
    }
    def cell(value: str | None) -> str:
        return (value or "UNKNOWN").replace("|", "\\|")
    lines = [
        "# Agent Mindmap — PRIVATE read-only snapshot",
        "",
        f"Source: T3 metadata | Observed: {generated} | Exported: {current.isoformat()}",
        f"Connection: {feed['connection']} | Freshness: **{freshness}** ({age:.0f}s at export)",
        f"Sessions: {len(sessions)} | Verified lineage edges: {len(delegations)}",
        "",
        f"Trusted until: {feed['trusted_until']} (older than this = treat as stale)",
        "",
        "**Quota:** T3 exposes no usage. Per-pool state (manual snapshots only, never combined):",
        *[
            f"- {name}: {pool['status']}"
            + (f" — {pool.get('five_hour_used_pct', '?')}% 5h / {pool.get('weekly_used_pct', '?')}% weekly used,"
               f" source {pool['source']}, observed {pool['observed_at']}" if pool["status"] != "UNKNOWN" else "")
            for name, pool in feed["quota"]["pools"].items()
        ],
        "**Limits:** Missing agents are not necessarily idle. Status updates are not proof that code ran.",
        "",
        "| Provider | Model | Status | Task | Project | Branch | Last update |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in sessions:
        lines.append(f"| {cell(s['provider'])} | {cell(s['model'])} | {cell(s['status'])} | {cell(s['task'])} | "
                     f"{cell(s['project'])} | {cell(s['branch'])} | {cell(s['last_activity_at'])} |")
    if delegations:
        lines += ["", "Verified delegations (parent → child, by session id):"]
        lines += [f"- {cell(d['from'])} → {cell(d['to'])}" for d in delegations]
    return feed, "\n".join(lines) + "\n"


def write_private(directory: Path, filename: str, data: str):
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if ROOT == directory or ROOT in directory.parents:
        raise ValueError("Refusing to write private snapshots inside the PUBLIC mind-map repository")
    os.chmod(directory, 0o700)
    fd, temp = tempfile.mkstemp(prefix=".mindmap-", dir=directory)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp, directory / filename)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="T3 daemon's local activity.json")
    parser.add_argument("--out-dir", type=Path, default=Path.home() / ".local/share/agent-mindmap-private-feed")
    args = parser.parse_args()
    directory = args.out_dir.resolve()
    if directory == ROOT or ROOT in directory.parents:
        parser.error("private snapshots may not be saved in the public repo")
    source = json.loads(args.input.read_text(encoding="utf-8"))
    feed, summary = make_feed(source)
    write_private(directory, "latest.json", json.dumps(feed, indent=2, ensure_ascii=False) + "\n")
    write_private(directory, "summary.md", summary)
    print(f"Private feed exported: {len(feed['sessions'])} sessions, freshness={feed['freshness']}")
    print("Nothing was uploaded or published.")


if __name__ == "__main__":
    main()
