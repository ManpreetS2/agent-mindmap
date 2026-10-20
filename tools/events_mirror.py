#!/usr/bin/env python3
"""
Events mirror flush decision helper (MM-020c).

Clones the MM-010 ledger_mirror pattern for the shared NetworkEvent JSONL:
bots append sanitized lines; this tool decides whether to flush one overwritten
`events.jsonl` to branch `data/events` (never main). It never talks to the
network.

Pipeline before flush decision:
  1. Parse JSONL; drop invalid NetworkEvent lines (warning to stderr).
  2. Dedupe by `id` (latest `ts` wins).
  3. Keep only events from the last 7 days (Director: overwrite + 7-day retention).

Flush is true only when:
  - content sha256 changed since last successful flush, AND
  - at least one new event id since last flush, AND
  - >= 180 seconds have elapsed since last flush,
  OR `--force` is set.

Idempotent: the same content sha256 never flushes twice.
State is updated only via `--mark-flushed <sha256>`.

SEC-MM010-1 / SEC-MM020c-2: before any flush, scan with
tools.secret_scan.looks_like_secret (shared denylist). Secrets refuse the
flush (reason=secret_detected, line numbers only); --force cannot bypass.
Matched secret text is never printed.

Stdlib only (+ shared tools.secret_scan; no new deps).
event_emit.py is not on this branch yet — minimal local NetworkEvent validator.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.atomic_write import atomic_write_text  # noqa: E402  — QA-MM020c-3
from tools.secret_scan import looks_like_secret  # noqa: E402  — shared scanner (SEC-MM020c-2)

FLUSH_MIN_INTERVAL_S = 180
RETENTION_DAYS = 7
# SEC-MM020b-2: drop lines whose summary exceeds 280 chars.
SUMMARY_MAX_CHARS = 280
_SCHEMA_PATH = _ROOT / "schema" / "activity.schema.json"


def _provenance_values_from_schema() -> frozenset[str]:
    """Load $defs/provenance.enum from activity.schema.json (MM-020a source of truth)."""
    with _SCHEMA_PATH.open(encoding="utf-8") as f:
        root = json.load(f)
    enum = root["$defs"]["provenance"]["enum"]
    return frozenset(str(v) for v in enum)


PROVENANCE_VALUES = _provenance_values_from_schema()

# Match schema/$defs/taskId (same contract as MM-020b event_emit / activity.schema.json).
_TASK_ID_RE = re.compile(
    r"^(?:"
    r"[A-Z]{2,}-[0-9]{3}[A-Za-z0-9]*(-[0-9]+)?"
    r"|"
    r"[A-Z]{2,}-[A-Z]{2}[0-9]{3}(-[0-9]+)?"
    r")$"
)

DEFAULT_EVENTS_PATH = Path(
    os.environ.get("MINDMAP_EVENTS", "/workspace/events.jsonl")
)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def secret_line_numbers(content: str) -> list[int]:
    """1-based line numbers that match looks_like_secret (never return text)."""
    hits: list[int] = []
    for i, line in enumerate(content.splitlines(), start=1):
        if looks_like_secret(line):
            hits.append(i)
    return hits


def parse_iso_ts(value: str) -> datetime | None:
    """Parse ISO-8601 with optional trailing Z; return aware datetime or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def validate_network_event(obj: Any) -> dict[str, Any] | None:
    """
    Minimal NetworkEvent validator aligned with MM-020b / schema $defs/networkEvent.

    Standalone on purpose: do not import tools.event_emit (PR #17 @ 48a13d9) —
    that helper raises-or-None via jsonschema and is not on this branch yet.
    Follow-up after #17 merges: dedupe validators / reuse one shared helper.

    Field + secret contract (aligned with MM-020b / schema $defs/networkEvent):
      required: id, ts, sender, group, type, summary, provenance
      provenance ∈ {observed, agent-reported, github-verified}
      summary: non-empty string, max SUMMARY_MAX_CHARS (280) — SEC-MM020b-2
      group: any non-empty string (unknown groups pass through)
      recipients: optional list of non-empty strings
      task_id: optional null or schema taskId pattern
      secrets: refused at flush via tools.secret_scan (SEC-MM010-1 / SEC-MM020c-2)

    Returns a cleaned dict, or None if invalid (caller drops the line).
    """
    if not isinstance(obj, dict):
        return None

    eid = obj.get("id")
    ts = obj.get("ts")
    sender = obj.get("sender")
    group = obj.get("group")
    etype = obj.get("type")
    summary = obj.get("summary")
    provenance = obj.get("provenance")

    if not isinstance(eid, str) or not eid.strip():
        return None
    if not isinstance(ts, str) or parse_iso_ts(ts) is None:
        return None
    if not isinstance(sender, str) or not sender.strip():
        return None
    if not isinstance(group, str) or not group.strip():
        return None
    if not isinstance(etype, str) or not etype.strip():
        return None
    # Emitter refuses empty summaries; SEC-MM020b-2: max SUMMARY_MAX_CHARS (280).
    if not isinstance(summary, str) or not summary.strip():
        return None
    if len(summary) > SUMMARY_MAX_CHARS:
        return None
    if provenance not in PROVENANCE_VALUES:
        return None

    out: dict[str, Any] = {
        "id": eid.strip(),
        "ts": ts.strip(),
        "sender": sender.strip(),
        "group": group.strip(),  # unknown groups allowed
        "type": etype.strip(),
        "summary": summary,
        "provenance": provenance,
    }

    if "recipients" in obj and obj["recipients"] is not None:
        rec = obj["recipients"]
        if not isinstance(rec, list):
            return None
        if not all(isinstance(x, str) and x.strip() for x in rec):
            return None
        out["recipients"] = list(rec)

    if "task_id" in obj:
        tid = obj["task_id"]
        if tid is None:
            out["task_id"] = None
        elif isinstance(tid, str) and _TASK_ID_RE.match(tid):
            out["task_id"] = tid
        else:
            return None

    if "related_id" in obj:
        rid = obj["related_id"]
        if rid is not None and not isinstance(rid, str):
            return None
        out["related_id"] = rid

    return out


def event_state_fingerprints(events: list[dict[str, Any]]) -> list[str]:
    """Stable fingerprints = event ids (order-preserving, unique)."""
    out: list[str] = []
    seen: set[str] = set()
    for ev in events:
        eid = ev.get("id")
        if not isinstance(eid, str) or eid in seen:
            continue
        seen.add(eid)
        out.append(eid)
    return out


def load_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {
            "last_flushed_sha256": None,
            "last_flushed_at": None,
            "state_change_fingerprints": [],
        }
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    return {
        "last_flushed_sha256": data.get("last_flushed_sha256"),
        "last_flushed_at": data.get("last_flushed_at"),
        "state_change_fingerprints": list(data.get("state_change_fingerprints") or []),
    }


def save_state(path: Path, state: dict[str, Any]) -> None:
    """Persist mirror state atomically (temp + fsync + os.replace; QA-MM020c-3)."""
    payload = json.dumps(state, indent=2, sort_keys=True) + "\n"
    atomic_write_text(path, payload)


def prepare_events_payload(
    raw_text: str,
    *,
    now: datetime | None = None,
    retention_days: int = RETENTION_DAYS,
    warn: bool = True,
) -> tuple[str, list[dict[str, Any]], list[str], bool]:
    """
    Validate / dedupe / retain.

    Returns (jsonl_text, events, warning_messages, secrets_seen).
    secrets_seen is True when any line was dropped for secret-like content
    (QA-MM020b-2 / SEC-MM010-1); caller must refuse flush.
    """
    now_dt = now or datetime.now(timezone.utc)
    cutoff = now_dt - timedelta(days=retention_days)
    warnings_out: list[str] = []
    parsed: list[dict[str, Any]] = []
    secrets_seen = False

    for lineno, raw in enumerate(raw_text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            msg = f"events_mirror: drop invalid JSON at line {lineno}"
            warnings_out.append(msg)
            if warn:
                print(msg, file=sys.stderr)
            continue
        # SEC-MM020b-2: call out over-long summaries before generic invalid drop.
        if (
            isinstance(obj, dict)
            and isinstance(obj.get("summary"), str)
            and len(obj["summary"]) > SUMMARY_MAX_CHARS
        ):
            msg = (
                f"events_mirror: drop summary over {SUMMARY_MAX_CHARS} chars "
                f"at line {lineno} (SEC-MM020b-2)"
            )
            warnings_out.append(msg)
            if warn:
                print(msg, file=sys.stderr)
            continue
        # Director: provenance required on new events; only allowlisted values.
        if isinstance(obj, dict):
            prov = obj.get("provenance")
            if prov is None or "provenance" not in obj:
                msg = (
                    f"events_mirror: drop missing provenance at line {lineno}"
                )
                warnings_out.append(msg)
                if warn:
                    print(msg, file=sys.stderr)
                continue
            if prov not in PROVENANCE_VALUES:
                msg = (
                    f"events_mirror: drop invalid provenance at line {lineno}"
                )
                warnings_out.append(msg)
                if warn:
                    print(msg, file=sys.stderr)
                continue
        ev = validate_network_event(obj)
        if ev is None:
            msg = f"events_mirror: drop invalid NetworkEvent at line {lineno}"
            warnings_out.append(msg)
            if warn:
                print(msg, file=sys.stderr)
            continue
        # QA-MM020b-2 / SEC-MM010-1: drop secret-like lines (warning only — never echo).
        summary = ev.get("summary") if isinstance(ev.get("summary"), str) else ""
        if looks_like_secret(summary) or looks_like_secret(line):
            secrets_seen = True
            msg = (
                f"events_mirror: drop secret-like content at line {lineno} "
                f"(QA-MM020b-2)"
            )
            warnings_out.append(msg)
            if warn:
                print(msg, file=sys.stderr)
            continue
        parsed.append(ev)

    # Dedupe by id — latest ts wins; equal ts → last seen wins.
    by_id: dict[str, dict[str, Any]] = {}
    for ev in parsed:
        eid = ev["id"]
        prev = by_id.get(eid)
        if prev is None:
            by_id[eid] = ev
            continue
        prev_ts = parse_iso_ts(prev["ts"])
        cur_ts = parse_iso_ts(ev["ts"])
        if prev_ts is None or (cur_ts is not None and cur_ts >= prev_ts):
            by_id[eid] = ev

    retained: list[dict[str, Any]] = []
    for ev in by_id.values():
        ts = parse_iso_ts(ev["ts"])
        if ts is None or ts < cutoff:
            continue
        retained.append(ev)

    retained.sort(key=lambda e: (parse_iso_ts(e["ts"]) or datetime.min.replace(tzinfo=timezone.utc), e["id"]))

    lines = [json.dumps(ev, sort_keys=True, separators=(",", ":")) for ev in retained]
    text = ("\n".join(lines) + ("\n" if lines else ""))
    return text, retained, warnings_out, secrets_seen


def decide_flush(
    *,
    content: str,
    events: list[dict[str, Any]],
    state: dict[str, Any],
    now: float,
    force: bool = False,
) -> dict[str, Any]:
    """
    Return decision dict: flush, sha256, reason (+ payload filled by caller).
    Same gating as ledger_mirror (MM-010).
    """
    digest = sha256_text(content)
    last_sha = state.get("last_flushed_sha256")
    last_at = state.get("last_flushed_at")
    prev_fps = set(state.get("state_change_fingerprints") or [])
    cur_fps = event_state_fingerprints(events)
    new_fps = [fp for fp in cur_fps if fp not in prev_fps]

    # Idempotent: identical content never flushes twice (even with --force).
    if last_sha is not None and digest == last_sha:
        return {
            "flush": False,
            "sha256": digest,
            "reason": "unchanged",
            "new_state_change_count": 0,
        }

    # SEC-MM010-1: refuse flush if secrets present; --force must not bypass.
    secret_lines = secret_line_numbers(content)
    if secret_lines:
        return {
            "flush": False,
            "sha256": digest,
            "reason": "secret_detected",
            "lines": secret_lines,
            "new_state_change_count": len(new_fps),
        }

    if force:
        return {
            "flush": True,
            "sha256": digest,
            "reason": "force",
            "new_state_change_count": len(new_fps),
        }

    if not new_fps:
        return {
            "flush": False,
            "sha256": digest,
            "reason": "no_state_change",
            "new_state_change_count": 0,
        }

    if last_at is not None:
        try:
            elapsed = now - float(last_at)
        except (TypeError, ValueError):
            elapsed = FLUSH_MIN_INTERVAL_S
        if elapsed < FLUSH_MIN_INTERVAL_S:
            return {
                "flush": False,
                "sha256": digest,
                "reason": "under_180s",
                "new_state_change_count": len(new_fps),
                "elapsed_s": elapsed,
            }

    return {
        "flush": True,
        "sha256": digest,
        "reason": "state_change",
        "new_state_change_count": len(new_fps),
    }


def mark_flushed(
    *,
    state_path: Path,
    sha256: str,
    events: list[dict[str, Any]] | None,
    now: float,
) -> dict[str, Any]:
    """Record a successful flush. Fingerprints come from current event ids."""
    state = load_state(state_path)
    fps = (
        event_state_fingerprints(events)
        if events is not None
        else list(state.get("state_change_fingerprints") or [])
    )
    new_state = {
        "last_flushed_sha256": sha256,
        "last_flushed_at": now,
        "state_change_fingerprints": fps,
    }
    save_state(state_path, new_state)
    return new_state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Decide whether to flush the local events mirror (MM-020c)"
    )
    parser.add_argument(
        "--events",
        type=Path,
        default=None,
        help="Path to shared NetworkEvent JSONL (default: MINDMAP_EVENTS or /workspace/events.jsonl)",
    )
    parser.add_argument(
        "--state",
        type=Path,
        required=True,
        help="JSON state file (last flush sha / time / fingerprints)",
    )
    parser.add_argument(
        "--payload",
        type=Path,
        default=None,
        help="When flushing, write cleaned events.jsonl bytes here",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Flush even if under 180s / no new event id (still idempotent on sha)",
    )
    parser.add_argument(
        "--mark-flushed",
        metavar="SHA256",
        default=None,
        help="Record a successful flush for this content hash (updates state only)",
    )
    parser.add_argument(
        "--now",
        type=float,
        default=None,
        help="Override unix epoch seconds (tests)",
    )
    args = parser.parse_args(argv)
    now = float(args.now if args.now is not None else time.time())
    now_dt = datetime.fromtimestamp(now, tz=timezone.utc)

    events_path = args.events if args.events is not None else DEFAULT_EVENTS_PATH

    if args.mark_flushed:
        events: list[dict[str, Any]] | None = None
        if args.events is not None:
            if not events_path.is_file():
                print(f"events not found: {events_path}", file=sys.stderr)
                return 1
            raw = events_path.read_text(encoding="utf-8")
            content, events, _, _ = prepare_events_payload(
                raw, now=now_dt, warn=False
            )
            digest = sha256_text(content)
            if digest != args.mark_flushed:
                print(
                    f"error: --mark-flushed {args.mark_flushed} does not match "
                    f"events sha256 {digest}",
                    file=sys.stderr,
                )
                return 1
        mark_flushed(
            state_path=args.state,
            sha256=args.mark_flushed,
            events=events,
            now=now,
        )
        print(
            json.dumps(
                {
                    "flush": False,
                    "sha256": args.mark_flushed,
                    "reason": "marked",
                },
                sort_keys=True,
            )
        )
        return 0

    if not events_path.is_file():
        print(f"events not found: {events_path}", file=sys.stderr)
        return 1

    raw = events_path.read_text(encoding="utf-8")
    content, events, _, secrets_seen = prepare_events_payload(
        raw, now=now_dt, warn=True
    )
    state = load_state(args.state)

    # Secrets dropped from payload still refuse flush (never write payload).
    if secrets_seen:
        decision = {
            "flush": False,
            "sha256": sha256_text(content),
            "reason": "secret_detected",
            "lines": secret_line_numbers(raw),
        }
    else:
        decision = decide_flush(
            content=content,
            events=events,
            state=state,
            now=now,
            force=bool(args.force),
        )

    out: dict[str, Any] = {
        "flush": decision["flush"],
        "sha256": decision["sha256"],
        "reason": decision["reason"],
    }
    if decision.get("reason") == "secret_detected":
        out["lines"] = list(decision.get("lines") or [])
    if decision["flush"]:
        payload_path = args.payload
        if payload_path is None:
            payload_path = events_path.with_name("events.jsonl.payload")
        atomic_write_text(payload_path, content)
        out["payload"] = str(payload_path)

    print(json.dumps(out, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
