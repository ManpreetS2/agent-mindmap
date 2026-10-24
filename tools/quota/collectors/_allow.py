"""Allowlists: the only commands and JSON-RPC methods quota collectors may use. None of them invoke a model."""
from __future__ import annotations

import os

from ..models import QuotaError

ALLOWED_COMMANDS = {
    ("codex", "app-server"),
    ("cursor-agent", "about", "--format", "json"),
}
ALLOWED_RPC_METHODS = frozenset({"initialize", "initialized", "account/rateLimits/read"})


def check_argv(argv: list[str]) -> list[str]:
    if not argv or (os.path.basename(argv[0]), *argv[1:]) not in ALLOWED_COMMANDS:
        raise QuotaError("command is not on the quota collector allowlist")
    return argv


def check_method(method: str) -> str:
    if method not in ALLOWED_RPC_METHODS:
        raise QuotaError(f"JSON-RPC method {method!r} is not on the quota collector allowlist")
    return method
