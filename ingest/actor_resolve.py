"""MM-020-P0: strict actor attribution (no GitHub-login guessing)."""

from __future__ import annotations

from typing import Any

from .attribute import load_bots, owner_to_bot_id

_UNKNOWN_SENDER = frozenset({"", "UNKNOWN", "unknown", "unattributed"})


def _bot_id_from_identity(value: str, bots: list[dict[str, Any]]) -> str | None:
    key = value.strip()
    if not key or key in _UNKNOWN_SENDER:
        return None
    for bot in bots:
        if key == bot.get("id"):
            return str(bot["id"])
        if key == bot.get("display_name"):
            return str(bot["id"])
        for alias in bot.get("aliases", []):
            if key == str(alias).lstrip("~"):
                return str(bot["id"])
    return None


def signature_at_start(
    body: str | None,
    bots: list[dict[str, Any]] | None = None,
) -> tuple[str | None, str]:
    """Match roster ``~`` aliases only at body start (after leading whitespace)."""
    if not body:
        return None, "unknown"
    text = body.lstrip()
    if not text.startswith("~"):
        return None, "unknown"
    bot_list = bots if bots is not None else load_bots()
    pairs: list[tuple[str, str]] = []
    for bot in bot_list:
        for alias in bot.get("aliases", []):
            a = str(alias).strip()
            if a.startswith("~"):
                pairs.append((a, str(bot["id"])))
    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    for alias, bot_id in pairs:
        if not text.startswith(alias):
            continue
        rest = text[len(alias) :]
        if rest == "" or rest[0] in " \t\n\r:,.;!?)]":
            return bot_id, "signature"
    return None, "unknown"


def actor_from_ledger_task(
    task_id: str | None,
    ledger_tasks: list[dict[str, Any]] | None,
    bots: list[dict[str, Any]],
) -> tuple[str | None, str]:
    if not task_id or not ledger_tasks:
        return None, "unknown"
    for task in ledger_tasks:
        if str(task.get("id") or "") == task_id:
            owner = str(task.get("owner") or "")
            bot_id = owner_to_bot_id(owner, bots)
            if bot_id:
                return bot_id, "ledger_owner"
            return None, "unknown"
    return None, "unknown"


def resolve_pr_lane_actor(
    *,
    body: str | None,
    from_field: str | None = None,
    sender_field: str | None = None,
    task_id: str | None = None,
    head_ref: str | None = None,
    ledger_tasks: list[dict[str, Any]] | None = None,
    bots: list[dict[str, Any]] | None = None,
) -> tuple[str | None, str]:
    """
    Strict order: (1) from/sender identity, (2) ~Bot at body start, (3) ledger task owner.
    Never use GitHub login. Returns (bot_id | None, attribution method).
    """
    bot_list = bots if bots is not None else load_bots()
    for raw in (from_field, sender_field):
        if isinstance(raw, str) and raw.strip():
            bid = _bot_id_from_identity(raw, bot_list)
            if bid:
                return bid, "network_from"
    actor, method = signature_at_start(body, bot_list)
    if actor:
        return actor, method
    tid = task_id
    if not tid and head_ref:
        from .attribute import extract_task_id

        tid = extract_task_id(head_ref)
    actor, method = actor_from_ledger_task(tid, ledger_tasks, bot_list)
    if actor:
        return actor, method
    return None, "unknown"


def apply_strict_attribution(
    events: list[dict[str, Any]],
    *,
    bots: list[dict[str, Any]],
    ledger_tasks: list[dict[str, Any]] | None,
) -> int:
    """
    Re-apply strict attribution on activity events (GitHub + network-shaped).
    Returns count of events still without ``actor``.
    """
    unattributed = 0
    ledger = ledger_tasks if ledger_tasks else []
    for evt in events:
        source_url = str(evt.get("source_url") or "")
        if "task-ledger" in source_url or source_url.endswith("ledger-sample.md"):
            if not evt.get("actor"):
                unattributed += 1
            continue
        prov = evt.get("provenance")
        body = evt.get("raw") or evt.get("summary")
        from_field = evt.get("from")
        sender_field = evt.get("sender")
        if sender_field is None and isinstance(evt.get("actor"), str):
            sender_field = evt.get("actor")
        task_id = evt.get("task_id")
        head_ref = evt.get("head_ref")
        existing = evt.get("actor")
        existing_method = (
            (evt.get("attribution") or {}).get("method")
            if isinstance(evt.get("attribution"), dict)
            else None
        )
        if existing and existing_method not in {None, "unknown", "github_login_unmapped"}:
            continue
        if prov == "github-verified" or source_url.startswith("live:"):
            actor, method = resolve_pr_lane_actor(
                body=str(body) if body is not None else None,
                from_field=from_field if isinstance(from_field, str) else None,
                sender_field=sender_field if isinstance(sender_field, str) else None,
                task_id=str(task_id) if task_id is not None else None,
                head_ref=str(head_ref) if isinstance(head_ref, str) else None,
                ledger_tasks=ledger,
                bots=bots,
            )
            evt["actor"] = actor
            evt["attribution"] = {"method": method}
        if not evt.get("actor"):
            unattributed += 1
    return unattributed


def resolve_network_sender_strict(
    ne: dict[str, Any],
    *,
    bots: list[dict[str, Any]] | None = None,
    ledger_tasks: list[dict[str, Any]] | None = None,
) -> tuple[str | None, str]:
    """NetworkEventLog entry → (actor, attribution method)."""
    summary = ne.get("summary")
    body = summary if isinstance(summary, str) else None
    return resolve_pr_lane_actor(
        body=body,
        from_field=ne.get("from") if isinstance(ne.get("from"), str) else None,
        sender_field=ne.get("sender") if isinstance(ne.get("sender"), str) else None,
        task_id=ne.get("task_id") if ne.get("task_id") is not None else None,
        head_ref=ne.get("branch") if isinstance(ne.get("branch"), str) else None,
        ledger_tasks=ledger_tasks,
        bots=bots,
    )
