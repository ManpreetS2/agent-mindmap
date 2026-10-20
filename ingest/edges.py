"""Derive graph edges from activity events (handoff / verdict / pr / merge / message)."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from .attribute import VERDICT_TOKENS
from .membership import group_target_id

# Event types that always yield a handoff-style edge (actor → target).
_HANDOFF_TYPES = frozenset({"handoff", "assigned"})

_GITHUB_PR_URL_RE = re.compile(
    r"github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/pull/(\d+)",
    re.IGNORECASE,
)


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


def pr_key(evt: dict[str, Any]) -> tuple[str, int] | None:
    """
    QA-MM004-8: join PRs by (repo, number), never number alone.

    Prefer explicit `repo`; else parse from github.com/.../pull/N in source_url/raw.
    """
    pr = evt.get("pr")
    if pr is None:
        return None
    repo = evt.get("repo")
    if isinstance(repo, str) and "/" in repo:
        return (repo, int(pr))
    for text in (evt.get("source_url"), evt.get("raw")):
        if not text:
            continue
        m = _GITHUB_PR_URL_RE.search(str(text))
        if m and int(m.group(2)) == int(pr):
            return (m.group(1), int(pr))
    return None


def _merger_eligible(evt: dict[str, Any]) -> bool:
    """
    QA-MM004-7 / Director: merger only from ledger actor or ~Bot signature.
    Never attribute from merged_by / unknown owner login.
    """
    if not evt.get("actor"):
        return False
    method = _attr_method(evt)
    if method == "signature":
        return True
    if method == "ledger_owner" or _is_ledger_source(evt):
        return True
    return False


def _merger_score(evt: dict[str, Any]) -> int:
    if not _merger_eligible(evt):
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
    eligible = [e for e in merge_events if _merger_eligible(e)]
    if not eligible:
        return None
    best = max(eligible, key=_merger_score)
    return str(best["actor"])


def _explicit_recipients(evt: dict[str, Any]) -> list[str]:
    """
    Return explicit recipients only — never invent.

    Prefer `recipients` when present (non-empty list of strings).
    Else a single non-null `target` that is not a group:{id} sentinel.
    """
    raw = evt.get("recipients")
    if isinstance(raw, list) and raw:
        out: list[str] = []
        for item in raw:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
        if out:
            return out
    target = evt.get("target")
    if isinstance(target, str) and target.strip() and not target.startswith("group:"):
        return [target.strip()]
    return []


def derive_edges(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Build aggregated edges from events.

    Rulings:
    - merge: merger → PR author, keyed by (repo, number). Merger from ledger
      or ~Bot signature only (never merged_by / owner account). Unknown →
      keep event, no edge. Never self-loops.
    - verdict: signature-attributed review/comment with a verdict token →
      reviewer → PR author.
    - pr: each signature-attributed review/comment → PR author → reviewer,
      deduped per (author, reviewer, repo, pr).
    - message (MM-020a): explicit recipients → sender→each recipient;
      untargeted → sender→group:{group}. Recipients are never invented.
    """
    pr_authors: dict[tuple[str, int], str] = {}
    merges_by_pr: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for evt in events:
        key = pr_key(evt)
        if key is None:
            continue
        if evt.get("type") == "pr_opened" and evt.get("actor"):
            pr_authors[key] = str(evt["actor"])
        if evt.get("type") == "merged":
            merges_by_pr.setdefault(key, []).append(evt)

    buckets: dict[tuple[str, str, str], dict[str, Any]] = {}
    pr_pairs_seen: set[tuple[str, str, str, int]] = set()

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

    # --- merge edges (one per (repo, pr), best eligible merger) ---
    for key, cands in merges_by_pr.items():
        merger = _pick_merger(cands)
        author = pr_authors.get(key)
        eligible = [e for e in cands if _merger_eligible(e)]
        winner = max(eligible, key=_merger_score) if eligible else None
        eid = str(winner["id"]) if winner else f"merge-{key[0]}#{key[1]}"
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
        key = pr_key(evt)
        if not reviewer or key is None:
            continue
        author = pr_authors.get(key)
        if not author:
            continue

        repo, pr = key
        pair_key = (str(author), str(reviewer), repo, pr)
        if pair_key not in pr_pairs_seen:
            pr_pairs_seen.add(pair_key)
            add_edge(str(author), str(reviewer), "pr", str(evt["id"]))

        verdict = evt.get("verdict")
        if evt.get("type") == "verdict" or (
            isinstance(verdict, str) and verdict.upper() in VERDICT_TOKENS
        ):
            add_edge(str(reviewer), str(author), "verdict", str(evt["id"]))

    # --- message edges (MM-020a) ---
    for evt in events:
        if evt.get("type") != "message":
            continue
        sender = evt.get("actor")
        if not sender:
            continue
        recipients = _explicit_recipients(evt)
        eid = str(evt["id"])
        if recipients:
            for dest in recipients:
                add_edge(str(sender), dest, "message", eid)
        else:
            group = evt.get("group")
            if isinstance(group, str) and group.strip():
                add_edge(str(sender), group_target_id(group.strip()), "message", eid)

    return sorted(buckets.values(), key=lambda e: (e["type"], e["source"], e["target"]))
