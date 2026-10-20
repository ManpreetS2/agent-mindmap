"""Derive graph edges from activity events (handoff / verdict / pr / merge)."""

from __future__ import annotations

import hashlib
from typing import Any

# Event type → edge type (architecture §3).
_EVENT_TO_EDGE = {
    "handoff": "handoff",
    "assigned": "handoff",
    "verdict": "verdict",
    "pr_opened": "pr",
    "merged": "merge",
}


def _edge_id(source: str, target: str, etype: str) -> str:
    return hashlib.sha1(f"edge:{etype}:{source}->{target}".encode("utf-8")).hexdigest()


def derive_edges(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Build aggregated edges from events that have both actor and target.

    For `merged` events missing `target`, use the `pr_opened` actor for that PR
    as the PR author (merge edges go merger → author).
    """
    pr_authors: dict[int, str] = {}
    for evt in events:
        if evt.get("type") == "pr_opened" and evt.get("pr") and evt.get("actor"):
            pr_authors[int(evt["pr"])] = str(evt["actor"])

    buckets: dict[tuple[str, str, str], dict[str, Any]] = {}
    for evt in events:
        edge_type = _EVENT_TO_EDGE.get(evt.get("type", ""))
        if not edge_type:
            continue
        source = evt.get("actor")
        target = evt.get("target")
        if edge_type == "merge" and source and not target and evt.get("pr"):
            target = pr_authors.get(int(evt["pr"]))
        if not source or not target:
            continue
        key = (str(source), str(target), edge_type)
        bucket = buckets.get(key)
        if bucket is None:
            bucket = {
                "id": _edge_id(str(source), str(target), edge_type),
                "source": str(source),
                "target": str(target),
                "type": edge_type,
                "count": 0,
                "event_ids": [],
            }
            buckets[key] = bucket
        bucket["count"] += 1
        bucket["event_ids"].append(evt["id"])

    return sorted(buckets.values(), key=lambda e: (e["type"], e["source"], e["target"]))
