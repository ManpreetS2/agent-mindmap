"""MM-020k / QA-MM020g-8: resolve UNKNOWN network senders without inventing identity."""

from __future__ import annotations

from typing import Any

from .attribute import attribute_from_body, load_bots
from .membership import membership_index

UNATTRIBUTED = "unattributed"
_UNKNOWN_TOKENS = frozenset({"", "UNKNOWN", "unknown", UNATTRIBUTED})


def room_member_bots(
    group: str | None,
    bots: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """
    Bots that belong to a room/group via membership index or home layout group.

    This is the room member map used to resolve UNKNOWN senders.
    """
    bot_list = bots if bots is not None else load_bots()
    if not isinstance(group, str) or not group.strip():
        return list(bot_list)
    gid = group.strip()
    member_ids: set[str] = set()
    for bot_id, groups in membership_index().items():
        if gid in groups:
            member_ids.add(bot_id)
    for bot in bot_list:
        if str(bot.get("group") or "") == gid:
            member_ids.add(str(bot["id"]))
    if not member_ids:
        return []
    return [b for b in bot_list if str(b.get("id")) in member_ids]


def resolve_network_sender(
    ne: dict[str, Any],
    bots: list[dict[str, Any]] | None = None,
) -> str | None:
    """
    Resolve a NetworkEvent sender to a bot id, or None → label unattributed.

    Rules (QA-MM020g-8):
    - Known non-UNKNOWN sender string is kept (may be a bot id).
    - UNKNOWN / empty → try ~Bot signature match against the room member map
      (members of ``ne.group`` only). A signature hit returns that bot id.
    - Otherwise return None — callers must use ``unattributed`` / null actor.
      Never invent a sender from ambient context.
    """
    bot_list = bots if bots is not None else load_bots()
    raw = ne.get("sender")
    if isinstance(raw, str) and raw.strip() and raw.strip() not in _UNKNOWN_TOKENS:
        return raw.strip()

    summary = ne.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        return None

    room = room_member_bots(ne.get("group") if isinstance(ne.get("group"), str) else None, bot_list)
    if not room:
        return None
    bot_id, method = attribute_from_body(summary, room)
    if bot_id and method == "signature":
        return bot_id
    return None


def sender_label(bot_id: str | None) -> str:
    """Display / NetworkEvent sender string — never invent bot ids."""
    return bot_id if bot_id else UNATTRIBUTED
