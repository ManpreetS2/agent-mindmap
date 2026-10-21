"""Top-level activity.json ``groups`` snapshot from config/groups.json."""

from __future__ import annotations

from typing import Any

from .membership import load_groups


def snapshot_activity_groups() -> tuple[list[dict[str, Any]], str]:
    """
    Return (groups, reason). ``reason`` is non-empty only when ``groups`` is [].
    """
    try:
        cfg = load_groups()
    except OSError:
        return [], "groups.json unreadable"
    raw = cfg.get("groups")
    if not isinstance(raw, list) or not raw:
        return [], "groups.json has no groups"
    out: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        gid = entry.get("id")
        if not isinstance(gid, str) or not gid.strip():
            continue
        members = entry.get("members")
        member_list = (
            [str(m) for m in members if isinstance(m, str) and m.strip()]
            if isinstance(members, list)
            else []
        )
        label = entry.get("label")
        out.append(
            {
                "id": gid.strip(),
                "label": str(label).strip() if isinstance(label, str) and label.strip() else gid.strip(),
                "members": member_list,
            }
        )
    if not out:
        return [], "groups.json empty after parse"
    return out, ""
