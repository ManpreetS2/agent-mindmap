"""
MM-020a: membership model — groups.json is source of truth for who belongs where.

Identity (id / aliases / layout) stays in bots.json. Primary `group` on a bot is
layout/home for backward-compatible activity nodes, not sole membership.

QA-MM020a-1: membership_index dedupes repeated member ids within a group
(stable first-seen order of groups; each group id appears at most once per bot).

QA-MM020a-2: unknown members (ids not in bots.json) are **parked** in
`MembershipResult.unknown_members` with a logged warning on stderr and are
**NOT indexed**. They do not raise. Soft-park so a typo in groups.json cannot
break activity builds; fix the config when warned.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

KNOWN_GROUPS = frozenset({"owner", "build", "qr", "radar"})


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_groups(path: Path | None = None) -> dict[str, Any]:
    cfg = path or (_repo_root() / "config" / "groups.json")
    with cfg.open(encoding="utf-8") as f:
        return json.load(f)


def load_bot_ids(path: Path | None = None) -> set[str]:
    """Known bot identity ids from config/bots.json."""
    cfg = path or (_repo_root() / "config" / "bots.json")
    with cfg.open(encoding="utf-8") as f:
        data = json.load(f)
    return {str(b["id"]) for b in data.get("bots", [])}


@dataclass
class MembershipResult:
    """Resolved membership: indexed bots plus parked unknown member refs."""

    index: dict[str, list[str]]
    unknown_members: list[dict[str, str]] = field(default_factory=list)
    # Each parked entry: {"bot_id": "...", "group_id": "..."}


def resolve_membership(
    groups_cfg: dict[str, Any] | None = None,
    *,
    known_bot_ids: set[str] | None = None,
    warn_stream: TextIO | None = None,
) -> MembershipResult:
    """
    Build membership index and park unknown members (QA-MM020a-1 / QA-MM020a-2).

    - Dedupes a bot listed twice in the same group's members list.
    - Unknown ids (not in bots.json) are parked + warned; not indexed.
    """
    cfg = groups_cfg if groups_cfg is not None else load_groups()
    if known_bot_ids is None:
        known_bot_ids = load_bot_ids()
    out = warn_stream if warn_stream is not None else sys.stderr

    index: dict[str, list[str]] = {}
    unknown_members: list[dict[str, str]] = []
    parked_keys: set[tuple[str, str]] = set()

    for group in cfg.get("groups", []):
        gid = str(group["id"])
        seen_in_group: set[str] = set()
        for raw in group.get("members", []):
            bot_id = str(raw)
            if bot_id in seen_in_group:
                # Duplicate within this group's members — keep first only.
                continue
            seen_in_group.add(bot_id)
            if bot_id not in known_bot_ids:
                key = (bot_id, gid)
                if key not in parked_keys:
                    parked_keys.add(key)
                    unknown_members.append({"bot_id": bot_id, "group_id": gid})
                    print(
                        f"warning: groups.json member {bot_id!r} in group {gid!r} "
                        f"is not in bots.json; parking (QA-MM020a-2)",
                        file=out,
                    )
                continue
            groups = index.setdefault(bot_id, [])
            if gid not in groups:
                groups.append(gid)

    return MembershipResult(index=index, unknown_members=unknown_members)


def membership_index(
    groups_cfg: dict[str, Any] | None = None,
    *,
    known_bot_ids: set[str] | None = None,
    warn_stream: TextIO | None = None,
) -> dict[str, list[str]]:
    """bot_id → ordered unique group ids. Unknown members are parked, not indexed."""
    return resolve_membership(
        groups_cfg, known_bot_ids=known_bot_ids, warn_stream=warn_stream
    ).index


def groups_for_bot(
    bot_id: str,
    groups_cfg: dict[str, Any] | None = None,
) -> list[str]:
    return list(membership_index(groups_cfg).get(bot_id, []))


def group_target_id(group_id: str) -> str:
    """Activity edge target for an untargeted group message."""
    return f"group:{group_id}"


def is_group_target(target: str | None) -> bool:
    if not target or not isinstance(target, str):
        return False
    if not target.startswith("group:"):
        return False
    return target.split(":", 1)[1] in KNOWN_GROUPS or bool(target.split(":", 1)[1])
