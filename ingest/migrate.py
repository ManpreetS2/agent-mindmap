"""
MM-020a: load legacy activity.json (schema 1.0.0) without rewriting fixtures.

migrate_activity() is a pure in-memory pass:
- Optionally bumps schema_version to 1.1.0
- Fills missing event/unparsed `provenance` from source rules (Director):
  - bot-signature attribution → agent-reported
  - GitHub-derived → github-verified
  - ledger / ledger_owner → agent-reported
- Does not invent recipients or membership

Backward compatibility: 1.0.0 fixtures stay on disk unchanged; callers migrate
in memory before treating them as 1.1.0 (where provenance is required).
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

SUPPORTED = frozenset({"1.0.0", "1.1.0"})
CURRENT = "1.1.0"


def _attr_method(evt: dict[str, Any]) -> str:
    attr = evt.get("attribution") or {}
    if isinstance(attr, dict):
        return str(attr.get("method") or "unknown")
    return str(attr or "unknown")


def _is_ledger_source(evt: dict[str, Any]) -> bool:
    url = str(evt.get("source_url") or "")
    return (
        "task-ledger" in url
        or url.endswith("ledger-sample.md")
        or "/ledger" in url
        or url.startswith("build/")
    )


def _is_github_source(evt: dict[str, Any]) -> bool:
    url = str(evt.get("source_url") or "")
    raw = str(evt.get("raw") or "")
    if "github.com" in url.lower():
        return True
    if "api.github.com" in url.lower():
        return True
    # Poller often stores repo-qualified PR facts
    if evt.get("repo") and evt.get("pr") is not None:
        if "github" in url.lower() or url.startswith("https://"):
            return True
    if "github.com" in raw.lower():
        return True
    return False


def infer_provenance(evt: dict[str, Any]) -> str:
    """
    Director ruling for legacy fill:
    - GitHub-derived → github-verified
    - ledger or bot-signature → agent-reported
    Signature wins over GitHub URL when both apply (explicit bot-reported fact).
    """
    method = _attr_method(evt)
    if method == "signature":
        return "agent-reported"
    if _is_github_source(evt) and not _is_ledger_source(evt):
        return "github-verified"
    if _is_ledger_source(evt) or method == "ledger_owner":
        return "agent-reported"
    # Remaining legacy notes without clear source
    return "agent-reported"


def _fill_event_provenance(evt: dict[str, Any]) -> dict[str, Any]:
    if evt.get("provenance") in {"observed", "agent-reported", "github-verified"}:
        return evt
    evt["provenance"] = infer_provenance(evt)
    return evt


def migrate_activity(doc: dict[str, Any], *, bump_version: bool = False) -> dict[str, Any]:
    """
    Return an activity dict safe for 1.1.0 consumers.

    Fixtures are left unchanged on disk. When bump_version is True (or the doc
    is already 1.1.0), missing provenance is filled on events and unparsed.
    """
    out = deepcopy(doc)
    version = out.get("schema_version")
    if version not in SUPPORTED:
        raise ValueError(f"unsupported schema_version: {version!r}")
    if bump_version:
        out["schema_version"] = CURRENT

    # Fill provenance whenever targeting / emitting 1.1.0.
    if out["schema_version"] == CURRENT or bump_version:
        out["events"] = [_fill_event_provenance(dict(e)) for e in out.get("events", [])]
        out["unparsed"] = [
            _fill_event_provenance(dict(e)) for e in out.get("unparsed", [])
        ]
    return out
