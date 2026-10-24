"""Compose the operational document served at /observability.json (schema/observability.schema.json).

Pure composition of three independently owned sources, each optional and fail-soft:
  machine identity  tools.machine_identity.load_identity()
  feed ownership    tools.publisher_ownership.feed_health()
  quota pools       tools.quota.api.pools()
A missing or failing source degrades to an honest UNKNOWN/unavailable value plus a note; it never raises, never
invents a reading, and never includes hostnames, usernames, paths or credentials. Demo mode is the synthetic
fixture shifted to "now"; it can never claim a verified reading.
"""
from __future__ import annotations

import json
import platform
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEMO_FIXTURE = ROOT / "fixtures" / "observability" / "demo.json"
POOL_IDS = ("claude-1", "claude-2", "cursor-premium", "devin-free", "codex")
_POOLS = {
    "claude-1": ("Claude 1", "claude", "claude-1"),
    "claude-2": ("Claude 2", "claude", "claude-2"),
    "cursor-premium": ("Cursor Premium", "cursor", "cursor-premium"),
    "devin-free": ("Devin Free", "devin", "devin-free"),
    "codex": ("Codex", "codex", "codex"),
}
UNKNOWN_MACHINE = {"id": "mac-00000000", "label": "Unregistered", "role": "reader"}


def unknown_pools(reason: str) -> list[dict]:
    out = []
    for pid in POOL_IDS:
        label, provider, alias = _POOLS[pid]
        out.append({
            "id": pid, "label": label, "provider": provider, "account_alias": alias, "plan": None,
            "status": "UNKNOWN", "windows": [],
            "source": {"kind": "none", "method": "no collector available", "supported_programmatically": False},
            "observed_at": None, "expires_at": None, "reason": reason[:200],
        })
    return out


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _parse(value: Any) -> datetime | None:
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return dt if dt.utcoffset() is not None else None


def shift_times(doc: Any, delta: timedelta) -> Any:
    """Move every ISO timestamp in a fixture by `delta` (keeps relative ages deterministic)."""
    if isinstance(doc, dict):
        return {k: shift_times(v, delta) for k, v in doc.items()}
    if isinstance(doc, list):
        return [shift_times(v, delta) for v in doc]
    if isinstance(doc, str) and len(doc) >= 20 and doc[4:5] == "-" and "T" in doc:
        dt = _parse(doc)
        if dt is not None:
            return _iso(dt + delta)
    return doc


def demo_document(now: datetime) -> dict:
    fixture = json.loads(DEMO_FIXTURE.read_text(encoding="utf-8"))
    base = _parse(fixture["generated_at"]) or now
    doc = shift_times(fixture, now - base)
    doc["generated_at"] = _iso(now)
    return doc


def _machine(config_dir: Path | None, notes: list[str]) -> dict:
    info = dict(UNKNOWN_MACHINE)
    try:
        from tools.machine_identity import load_identity  # owned by the runtime engineer

        ident = load_identity(config_dir) if config_dir else load_identity()
        if ident is not None:
            info = {"id": ident.id, "label": ident.label, "role": ident.role}
        else:
            notes.append("Machine identity not initialised (run the bootstrap); treated as a read-only reader")
    except ImportError:
        notes.append("Machine identity module not installed")
    except Exception:  # noqa: BLE001 - never let a diagnostics source break the dashboard
        notes.append("Machine identity could not be read")
    info["platform"] = f"{sys.platform}-{platform.machine()}"[:40]
    return info


def _feed(now: datetime, state_dir: Path | None, notes: list[str]) -> dict:
    fallback = {
        "status": "unknown", "last_published_at": None, "last_observed_at": None, "trusted_until": None,
        "owner": None, "owned_by_this_machine": None, "last_error": None,
    }
    try:
        from tools.publisher_ownership import feed_health  # owned by the runtime engineer

        health = feed_health(state_dir=state_dir, now=now)
        if isinstance(health, dict):
            return {**fallback, **{k: health.get(k, fallback[k]) for k in fallback}}
    except ImportError:
        notes.append("Publisher ownership module not installed; feed state unknown")
    except Exception:  # noqa: BLE001
        notes.append("Feed state could not be read")
    return fallback


def _quota(now: datetime, quota_dir: Path | None, notes: list[str]) -> tuple[list[dict], str | None]:
    try:
        from tools.quota.api import pools  # owned by the quota engineer

        got = pools(now=now, state_dir=quota_dir)
        if isinstance(got, list) and [p.get("id") for p in got] == list(POOL_IDS):
            seen = [p["observed_at"] for p in got if p.get("observed_at")]
            return got, (max(seen) if seen else None)
        notes.append("Quota module returned an unexpected shape; all pools UNKNOWN")
    except ImportError:
        notes.append("Quota module not installed; all pools UNKNOWN")
    except Exception:  # noqa: BLE001
        notes.append("Quota readings could not be collected; all pools UNKNOWN")
    return unknown_pools("Quota collection unavailable"), None


def build_observability(
    activity: dict | None,
    health: dict | None,
    *,
    now: datetime | None = None,
    config_dir: Path | None = None,
    state_dir: Path | None = None,
    quota_dir: Path | None = None,
) -> dict | None:
    """None for non-T3 (legacy ledger) sources: there is nothing operational to report."""
    now = now or datetime.now(UTC)
    t3 = ((activity or {}).get("meta") or {}).get("t3")
    if not isinstance(t3, dict):
        return None
    if t3.get("mode") == "demo":
        return demo_document(now)

    notes: list[str] = []
    polled = (health or {}).get("last_t3_poll")
    stale_after = t3.get("stale_after_sec")
    connection = t3.get("connection")
    status = connection if connection in {"connected", "unavailable"} else "unknown"
    poll_dt = _parse(polled)
    reason = None
    if status == "connected" and poll_dt is not None and isinstance(stale_after, int) and stale_after > 0:
        if (now - poll_dt).total_seconds() > stale_after:
            status, reason = "unavailable", "No successful T3 poll within the stale window"
    if status == "unavailable" and reason is None:
        reason = "T3 did not answer the last poll"
    pools, collected = _quota(now, quota_dir, notes)
    return {
        "schema": "agent-mindmap-observability/v1",
        "generated_at": _iso(now),
        "mode": "live",
        "machine": _machine(config_dir, notes),
        "collector": {
            "status": status,
            "last_t3_poll": _iso(poll_dt) if poll_dt else None,
            "stale_after_sec": stale_after if isinstance(stale_after, int) and stale_after > 0 else None,
            "reason": reason,
        },
        "feed": _feed(now, state_dir, notes),
        "quota": {"pools": pools, "collected_at": collected},
        "notes": notes[:20],
    }
