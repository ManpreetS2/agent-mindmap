"""Export a minimal, read-only T3 activity feed for a SEPARATE PRIVATE repository.

This never publishes to GitHub, writes inside agent-mindmap, or exposes credentials.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from ingest.t3 import safe_ident, safe_text, timestamp

ROOT = Path(__file__).resolve().parents[1]
VALID_STATES = {"IDLE", "IN_PROGRESS", "IN_REVIEW", "BLOCKED", "DONE", "UNKNOWN", "FAILED", "STALE"}


def make_feed(activity: dict, *, now: datetime | None = None) -> tuple[dict, str]:
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
    age = max(0, (current - datetime.fromisoformat(generated)).total_seconds())
    connected = t3.get("connection") == "connected"
    freshness = "fresh" if connected and age <= 120 else "stale"

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
            "provider": safe_text(session.get("provider")) or "Unknown",
            "model": safe_text(session.get("model")) or "Unknown",
            "project": safe_text(session.get("project")) or "Unknown",
            "task": safe_text(node.get("current_task")) or "Unknown",
            "branch": safe_text(session.get("branch")),
            "status": node["status"] if node.get("status") in VALID_STATES else "UNKNOWN",
            "last_activity_at": timestamp(node.get("last_activity_ts")),
            "stale": bool(session.get("stale")) or not connected,
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
        "quota": {"status": "unsupported", "note": "T3 read-only MCP does not expose subscription usage"},
        "limitations": [
            "T3 thread updates are not proof of actual tool execution",
            "Unseen external Cursor/Devin sessions cannot be inferred as idle",
            "The provider label does not uniquely identify two memberships",
        ],
        "status_counts": counts,
        "sessions": sessions,
        "delegations": delegations,
    }
    def cell(value: str | None) -> str:
        return (value or "Unknown").replace("|", "\\|")
    lines = [
        "# Agent Mindmap — PRIVATE read-only snapshot",
        "",
        f"Source: T3 metadata | Observed: {generated} | Exported: {current.isoformat()}",
        f"Connection: {feed['connection']} | Freshness: **{freshness}** ({age:.0f}s at export)",
        f"Sessions: {len(sessions)} | Verified lineage edges: {len(delegations)}",
        "",
        "**Quota: UNSUPPORTED.** No current per-account percentages are available from the T3 MCP interface.",
        "**Limits:** Missing agents are not necessarily idle. Status updates are not proof that code ran.",
        "",
        "| Provider | Status | Task | Project | Last update |",
        "|---|---|---|---|---|",
    ]
    for s in sessions:
        lines.append(f"| {cell(s['provider'])} | {cell(s['status'])} | {cell(s['task'])} | {cell(s['project'])} | {cell(s['last_activity_at'])} |")
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
