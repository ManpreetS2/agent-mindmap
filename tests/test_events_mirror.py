"""MM-020c: events_mirror flush decisions (stdlib tool)."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tools.events_mirror import (
    FLUSH_MIN_INTERVAL_S,
    RETENTION_DAYS,
    decide_flush,
    event_state_fingerprints,
    load_state,
    mark_flushed,
    prepare_events_payload,
    secret_line_numbers,
    sha256_text,
    validate_network_event,
)

ROOT = Path(__file__).resolve().parents[1]
MIRROR = ROOT / "tools" / "events_mirror.py"

NOW = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)
NOW_EPOCH = NOW.timestamp()


def _ev(
    eid: str,
    *,
    hours_ago: float = 1.0,
    group: str = "build",
    etype: str = "message",
    summary: str = "hello",
    provenance: str = "agent-reported",
    **extra: object,
) -> dict:
    ts = (NOW - timedelta(hours=hours_ago)).isoformat()
    obj: dict = {
        "id": eid,
        "ts": ts,
        "sender": "dev-2",
        "group": group,
        "type": etype,
        "summary": summary,
        "provenance": provenance,
    }
    obj.update(extra)
    return obj


def _jsonl(events: list[dict]) -> str:
    return "".join(json.dumps(e, sort_keys=True) + "\n" for e in events)


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MIRROR), *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


def test_validate_network_event_ok_and_unknown_group() -> None:
    ok = validate_network_event(_ev("e1", group="build"))
    assert ok is not None and ok["id"] == "e1"
    # Unknown group must pass through (no throw).
    weird = validate_network_event(_ev("e2", group="future-room-xyz"))
    assert weird is not None
    assert weird["group"] == "future-room-xyz"


def test_validate_drops_bad_provenance_and_missing_fields() -> None:
    assert validate_network_event(_ev("e1", provenance="invented")) is None
    bad = _ev("e1")
    del bad["sender"]
    assert validate_network_event(bad) is None
    assert validate_network_event("not-a-dict") is None


def test_invalid_line_drop_with_warning() -> None:
    good = _ev("keep-me")
    raw = (
        "{not json\n"
        + json.dumps(good) + "\n"
        + json.dumps({"id": "x"}) + "\n"  # incomplete NetworkEvent
    )
    text, events, warns = prepare_events_payload(raw, now=NOW, warn=False)
    assert [e["id"] for e in events] == ["keep-me"]
    assert len(warns) >= 2
    assert "keep-me" in text


def test_dedupe_by_id_keeps_latest_ts() -> None:
    older = _ev("same", hours_ago=5.0, summary="old")
    newer = _ev("same", hours_ago=1.0, summary="new")
    # File order: newer first, then older — still keep latest ts.
    raw = _jsonl([newer, older])
    _, events, _ = prepare_events_payload(raw, now=NOW, warn=False)
    assert len(events) == 1
    assert events[0]["summary"] == "new"


def test_seven_day_retention() -> None:
    inside = _ev("in", hours_ago=24.0)
    edge = _ev("edge", hours_ago=RETENTION_DAYS * 24 - 1)
    outside = _ev("out", hours_ago=RETENTION_DAYS * 24 + 12)
    raw = _jsonl([inside, edge, outside])
    _, events, _ = prepare_events_payload(raw, now=NOW, warn=False)
    ids = {e["id"] for e in events}
    assert ids == {"in", "edge"}
    assert "out" not in ids


SECRET_TOKEN = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def test_secret_blocks_flush(tmp_path: Path) -> None:
    """SEC-MM010-1: secret in payload → flush false, reason secret_detected."""
    dirty = _ev("s1", summary=f"note with token {SECRET_TOKEN}")
    content, events, _ = prepare_events_payload(_jsonl([dirty]), now=NOW, warn=False)
    decision = decide_flush(
        content=content,
        events=events,
        state=load_state(tmp_path / "missing.json"),
        now=NOW_EPOCH,
        force=False,
    )
    assert decision["flush"] is False
    assert decision["reason"] == "secret_detected"
    assert decision["lines"] == secret_line_numbers(content)
    assert SECRET_TOKEN not in json.dumps(decision)


def test_secret_blocks_force(tmp_path: Path) -> None:
    dirty = _ev("s1", summary=f"assigned follow-up {SECRET_TOKEN}")
    content, events, _ = prepare_events_payload(_jsonl([dirty]), now=NOW, warn=False)
    state = {
        "last_flushed_sha256": "other",
        "last_flushed_at": NOW_EPOCH - 10_000,
        "state_change_fingerprints": [],
    }
    decision = decide_flush(
        content=content, events=events, state=state, now=NOW_EPOCH, force=True
    )
    assert decision["flush"] is False
    assert decision["reason"] == "secret_detected"


def test_flush_gating_unchanged_no_state_under_180_and_ok(tmp_path: Path) -> None:
    first = _ev("a1")
    content1, events1, _ = prepare_events_payload(_jsonl([first]), now=NOW, warn=False)
    mark_flushed(
        state_path=tmp_path / "state.json",
        sha256=sha256_text(content1),
        events=events1,
        now=NOW_EPOCH,
    )
    st = load_state(tmp_path / "state.json")

    # Unchanged
    d0 = decide_flush(
        content=content1, events=events1, state=st, now=NOW_EPOCH + 10_000, force=False
    )
    assert d0["flush"] is False and d0["reason"] == "unchanged"

    # New event but under 180s
    second = _ev("a2", hours_ago=0.5)
    content2, events2, _ = prepare_events_payload(
        _jsonl([first, second]), now=NOW, warn=False
    )
    d1 = decide_flush(
        content=content2, events=events2, state=st, now=NOW_EPOCH + 60, force=False
    )
    assert d1["flush"] is False and d1["reason"] == "under_180s"

    # After 180s → flush
    d2 = decide_flush(
        content=content2,
        events=events2,
        state=st,
        now=NOW_EPOCH + FLUSH_MIN_INTERVAL_S,
        force=False,
    )
    assert d2["flush"] is True and d2["reason"] == "state_change"

    # No new event id (only summary tweak on same retained set via force path)
    # Re-build identical ids → fingerprints already known; change content somehow
    # by reordering is not possible (sorted). Use force with new content hash
    # that has no new ids: drop nothing, same events → unchanged after mark.
    # Separate case: content changes but no new fingerprints → no_state_change
    # Simulate by marking with empty fingerprints then same events without "new"
    # relative to a state that already has those fingerprints but different sha.
    st2 = {
        "last_flushed_sha256": "deadbeef",
        "last_flushed_at": NOW_EPOCH - 10_000,
        "state_change_fingerprints": event_state_fingerprints(events2),
    }
    # Force a different content hash: add blank is stripped; use force=False
    # with identical event set text already hashed — need different text same ids.
    # prepare always sort_keys — identical set → same content. So invent by
    # including an event that fails retention after mark... skip; use force.
    d_force = decide_flush(
        content=content2, events=events2, state=st2, now=NOW_EPOCH, force=True
    )
    assert d_force["flush"] is True and d_force["reason"] == "force"


def test_no_state_change_when_only_known_ids(tmp_path: Path) -> None:
    """Content hash differs but every event id was already flushed → no_state_change."""
    e1 = _ev("x1", summary="v1")
    e1b = _ev("x1", summary="v2")  # same id, newer summary → different content
    c1, ev1, _ = prepare_events_payload(_jsonl([e1]), now=NOW, warn=False)
    c2, ev2, _ = prepare_events_payload(_jsonl([e1b]), now=NOW, warn=False)
    assert sha256_text(c1) != sha256_text(c2)
    state = {
        "last_flushed_sha256": sha256_text(c1),
        "last_flushed_at": NOW_EPOCH - 10_000,
        "state_change_fingerprints": event_state_fingerprints(ev1),
    }
    decision = decide_flush(
        content=c2, events=ev2, state=state, now=NOW_EPOCH, force=False
    )
    assert decision["flush"] is False
    assert decision["reason"] == "no_state_change"


def test_cli_secret_detected_no_payload_no_leak(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    state = tmp_path / "mirror-state.json"
    payload = tmp_path / "events.jsonl.payload"
    dirty = _ev("s1", summary=f"Bearer {SECRET_TOKEN}")
    events_path.write_text(_jsonl([dirty]), encoding="utf-8")

    proc = _run(
        [
            "--events",
            str(events_path),
            "--state",
            str(state),
            "--payload",
            str(payload),
            "--force",
            "--now",
            str(NOW_EPOCH),
        ]
    )
    assert proc.returncode == 0, proc.stderr
    combined = proc.stdout + proc.stderr
    assert SECRET_TOKEN not in combined
    out = json.loads(proc.stdout)
    assert out["flush"] is False
    assert out["reason"] == "secret_detected"
    assert out["lines"]
    assert "payload" not in out
    assert not payload.exists()


def test_cli_writes_payload_and_mark_flushed(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    state = tmp_path / "mirror-state.json"
    payload = tmp_path / "events.jsonl.payload"
    content_raw = _jsonl([_ev("c1")])
    events_path.write_text(content_raw, encoding="utf-8")
    expected, _, _ = prepare_events_payload(content_raw, now=NOW, warn=False)

    proc = _run(
        [
            "--events",
            str(events_path),
            "--state",
            str(state),
            "--payload",
            str(payload),
            "--now",
            str(NOW_EPOCH),
        ]
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["flush"] is True
    assert out["sha256"] == sha256_text(expected)
    assert payload.is_file()
    assert payload.read_text(encoding="utf-8") == expected

    mark = _run(
        [
            "--mark-flushed",
            out["sha256"],
            "--state",
            str(state),
            "--events",
            str(events_path),
            "--now",
            str(NOW_EPOCH),
        ]
    )
    assert mark.returncode == 0, mark.stderr
    st = load_state(state)
    assert st["last_flushed_sha256"] == out["sha256"]

    again = _run(
        [
            "--events",
            str(events_path),
            "--state",
            str(state),
            "--payload",
            str(payload),
            "--force",
            "--now",
            str(NOW_EPOCH + 10_000),
        ]
    )
    assert again.returncode == 0
    out2 = json.loads(again.stdout)
    assert out2["flush"] is False
    assert out2["reason"] == "unchanged"
