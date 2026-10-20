"""MM-020i: DEMO mode fixtures and safe activity-out checks (stdlib only)."""

from __future__ import annotations

import errno
import json
import os
from pathlib import Path
from typing import Any, Literal

from tools.event_emit import validate_network_event

from .migrate import migrate_activity

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURES_DIR = ROOT / "fixtures"
DEFAULT_DEMO_ACTIVITY = DEFAULT_FIXTURES_DIR / "sample-activity.json"
DEMO_EVENTS_GLOB = "demo-network-events.jsonl"

ServerMode = Literal["demo", "live"]


class DemoFixtureError(ValueError):
    """Demo fixtures missing or unusable."""


class UnsafeActivityOutError(ValueError):
    """Refuse symlink or unsafe activity-out path."""


def assert_safe_activity_out_path(activity_out: Path) -> None:
    """O_NOFOLLOW-style safety for lock/output parent paths."""
    if activity_out.is_symlink():
        raise UnsafeActivityOutError(f"refusing symlink activity-out: {activity_out}")
    parent = activity_out.parent
    if parent.exists() and parent.is_symlink():
        raise UnsafeActivityOutError(f"refusing symlink activity-out parent: {parent}")


def ensure_activity_out_parent(activity_out: Path) -> None:
    assert_safe_activity_out_path(activity_out)
    activity_out.parent.mkdir(parents=True, exist_ok=True)


def load_demo_network_events(fixtures_dir: Path | None = None) -> list[dict[str, Any]]:
    """
    Load demo NetworkEvents from ``fixtures/demo-network-events.jsonl``.

    Malformed lines are skipped. Missing file → empty list (demo still starts).
    """
    base = fixtures_dir or DEFAULT_FIXTURES_DIR
    path = base / DEMO_EVENTS_GLOB
    if not path.is_file():
        return []

    events: list[dict[str, Any]] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        try:
            validate_network_event(obj)
        except Exception:
            continue
        events.append(obj)
    return events


def load_demo_activity_bytes(
    fixtures_dir: Path | None = None,
    *,
    mode: ServerMode = "demo",
) -> bytes:
    """In-memory activity snapshot for DEMO (never written to live activity-out)."""
    base = fixtures_dir or DEFAULT_FIXTURES_DIR
    activity_path = base / "sample-activity.json"
    if not activity_path.is_file():
        raise DemoFixtureError(f"demo activity fixture missing: {activity_path}")
    doc = json.loads(activity_path.read_text(encoding="utf-8"))
    doc = migrate_activity(doc)
    meta = doc.setdefault("meta", {})
    meta["mode"] = mode
    meta["github"] = "skipped"
    meta["ledger"] = "demo"
    return (json.dumps(doc, indent=2, sort_keys=False) + "\n").encode("utf-8")
