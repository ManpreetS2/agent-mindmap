"""
MM-020a: load legacy activity.json (schema 1.0.0) without rewriting fixtures.

Old snapshots remain valid under the 1.1.0 schema (enum accepts both versions).
migrate_activity() is a pure in-memory pass that does not invent recipients,
provenance, or membership — it only normalizes optional defaults when absent.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

SUPPORTED = frozenset({"1.0.0", "1.1.0"})
CURRENT = "1.1.0"


def migrate_activity(doc: dict[str, Any], *, bump_version: bool = False) -> dict[str, Any]:
    """
    Return an activity dict safe for 1.1.0 consumers.

    Fixtures are left unchanged on disk; callers may bump_version in memory only.
    Does not invent recipients, provenance, or node.groups.
    """
    out = deepcopy(doc)
    version = out.get("schema_version")
    if version not in SUPPORTED:
        raise ValueError(f"unsupported schema_version: {version!r}")
    if bump_version:
        out["schema_version"] = CURRENT
    # Optional fields stay absent unless already present — no invention.
    return out
