"""Derive graph edges from activity events (handoff / verdict / pr / merge)."""

from __future__ import annotations

import hashlib
from typing import Any

from .attribute import VERDICT_TOKENS

# Event types that always yield a handoff-style edge (actor → target).
_HANDOFF_TYPES = frozenset({"handoff", "assigned"})


def _edge_id(source: str, target: str, etype: str) -> str:
    return hashlib.sha1(f"edge:{etype}:{source}->{target}".encode("utf-8")).hexdigest()


def _attr_method(evt: dict[str, Any]) -> str:
    attr = evt.get("attribution") or {}
    if isinstance(attr, dict):
        return str(attr.get("method") or "unknown")
    return str(attr or "unknown")


def _is_ledger_source(evt: dict[str, Any]) -> bool:
    url = str(evt.get("source_url") or "")
    return "task-ledger" in url or url.endswith("ledger-sample.md") or "/ledger" in url


def _merger_score(evt: dict[str, Any]) -> int:
    """Prefer ledger merged notes and ~Bot signatures over mapped GitHub owner."""
    if not evt.get("actor"):
        return -1
    score = 0
    method = _attr_method(evt)
    if method == "signature":
        score += 20
    if _is_ledger_source(evt):
        score += 10
    if method == "ledger_owner":
        score += 5
    return score


def _pick_merger(merge_events: list[dict[str, Any]]) -> str | None:
    if not merge_events:
        return None
    best = max(merge_events, key=_merger_score)
    if _merger_score(best) < 0:
        return None
    return str(best["actor"])


def derive_edges(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Build aggregated edges from events.

    Rulings (QA-MM004-1 / QA-MM004-2):
    - merge: merger → PR author. Merger comes from the merged event's actor
      (poller sets it from `merged_by`, preferring a ledger note or ~Bot
      signature when present). Unknown merger → keep event, no edge.
      Never emit a self-loop.
    - verdict: signature-attributed review/comment with a verdict token →
      reviewer → PR author.
    - pr: each signature-attributed review/comment → PR author → reviewer,
      deduped per (author, reviewer, pr).
    - Unknown attribution produces no verdict/pr edge.
    """
    pr_authors: dict[int, str] = {}
    merges_by_pr: dict[int, list[dict[str, Any]]] = {}
    for evt in events:
        pr = evt.get("pr")
        if evt.get("type") == "pr_opened" and pr and evt.get("actor"):
            pr_authors[int(pr)] = str(evt["actor"])
        if evt.get("type") == "merged" and pr:
            merges_by_pr.setdefault(int(pr), []).append(evt)

    buckets: dict[tuple[str, str, str], dict[str, Any]] = {}
    pr_pairs_seen: set[tuple[str, str, int]] = set()

    def add_edge(source: str | None, target: str | None, etype: str, event_id: str) -> None:
        if not source or not target:
            return
        if source == target:
            return
        key = (source, target, etype)
        bucket = buckets.get(key)
        if bucket is None:
            bucket = {
                "id": _edge_id(source, target, etype),
                "source": source,
                "target": target,
                "type": etype,
                "count": 0,
                "event_ids": [],
            }
            buckets[key] = bucket
        bucket["count"] += 1
        bucket["event_ids"].append(event_id)

    # --- merge edges (one per PR, best merger candidate) ---
    for pr, cands in merges_by_pr.items():
        merger = _pick_merger(cands)
        author = pr_authors.get(pr)
        # Attach the winning merged event id when possible.
        winner = max(cands, key=_merger_score) if cands else None
        eid = str(winner["id"]) if winner else f"merge-pr{pr}"
        add_edge(merger, author, "merge", eid)

    # --- handoff / assigned ---
    for evt in events:
        if evt.get("type") not in _HANDOFF_TYPES:
            continue
        add_edge(evt.get("actor"), evt.get("target"), "handoff", str(evt["id"]))

    # --- signature-attributed reviews / comments → verdict + pr ---
    for evt in events:
        if _attr_method(evt) != "signature":
            continue
        if evt.get("type") not in {"verdict", "note"}:
            continue
        reviewer = evt.get("actor")
        pr = evt.get("pr")
        if not reviewer or pr is None:
            continue
        author = pr_authors.get(int(pr))
        if not author:
            continue

        pair_key = (str(author), str(reviewer), int(pr))
        if pair_key not in pr_pairs_seen:
            pr_pairs_seen.add(pair_key)
            add_edge(str(author), str(reviewer), "pr", str(evt["id"]))

        verdict = evt.get("verdict")
        if evt.get("type") == "verdict" or (
            isinstance(verdict, str) and verdict.upper() in VERDICT_TOKENS
        ):
            add_edge(str(reviewer), str(author), "verdict", str(evt["id"]))

    return sorted(buckets.values(), key=lambda e: (e["type"], e["source"], e["target"]))
