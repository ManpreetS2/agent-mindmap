"""
MM-020a: membership model — groups.json is source of truth for who belongs where.

Identity (id / aliases / layout) stays in bots.json. Primary `group` on a bot is
layout/home for backward-compatible activity nodes, not sole membership.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

KNOWN_GROUPS = frozenset({"owner", "build", "qr", "radar"})


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_groups(path: Path | None = None) -> dict[str, Any]:
    cfg = path or (_repo_root() / "config" / "groups.json")
    with cfg.open(encoding="utf-8") as f:
        return json.load(f)


def membership_index(
    groups_cfg: dict[str, Any] | None = None,
) -> dict[str, list[str]]:
    """bot_id → ordered list of group ids (from groups.json members)."""
    cfg = groups_cfg if groups_cfg is not None else load_groups()
    index: dict[str, list[str]] = {}
    for group in cfg.get("groups", []):
        gid = str(group["id"])
        for bot_id in group.get("members", []):
            index.setdefault(str(bot_id), []).append(gid)
    return index


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
