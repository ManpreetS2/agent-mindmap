"""MM-020-P0: resolve UNKNOWN network senders without inventing identity."""

from __future__ import annotations

from typing import Any

from .actor_resolve import resolve_network_sender_strict


def resolve_network_sender(
    ne: dict[str, Any],
    bots: list[dict[str, Any]] | None = None,
    ledger_tasks: list[dict[str, Any]] | None = None,
) -> str | None:
    actor, _method = resolve_network_sender_strict(
        ne, bots=bots, ledger_tasks=ledger_tasks
    )
    return actor
