"""MM-010: ledger_mirror flush decisions (stdlib tool)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.ledger_mirror import (
    FLUSH_MIN_INTERVAL_S,
    decide_flush,
    load_state,
    mark_flushed,
    sha256_text,
    state_change_fingerprints,
)

ROOT = Path(__file__).resolve().parents[1]
MIRROR = ROOT / "tools" / "ledger_mirror.py"

BASE = """# Task ledger

| Task ID | Project | Owner | Mode | Model | Status | Evidence |
|---|---|---|---|---|---|---|
| MM-010 | x | Architect | a | m | PLANNED | — |
"""

STATE_LINE = (
    "- 2026-10-20 10:00 AM PDT Architect: assigned DEV 1 on MM-010.\n"
)
STATE_LINE_2 = (
    "- 2026-10-20 10:05 AM PDT Architect: MM-010 DONE; squash-merged as abcdef1.\n"
)
NOTE_ONLY = (
    "- 2026-10-20 10:01 AM PDT Architect: hallway chatter, no state change.\n"
)


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MIRROR), *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


def test_unchanged_content_does_not_flush(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.md"
    state = tmp_path / "state.json"
    content = BASE + STATE_LINE
    ledger.write_text(content, encoding="utf-8")
    digest = sha256_text(content)
    mark_flushed(
        state_path=state,
        sha256=digest,
        content=content,
        now=1_000_000.0,
    )
    decision = decide_flush(
        content=content,
        state=load_state(state),
        now=1_000_000.0 + 10_000,
        force=False,
    )
    assert decision["flush"] is False
    assert decision["reason"] == "unchanged"


def test_non_state_change_addition_does_not_flush(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.md"
    state = tmp_path / "state.json"
    first = BASE + STATE_LINE
    ledger.write_text(first, encoding="utf-8")
    mark_flushed(
        state_path=state,
        sha256=sha256_text(first),
        content=first,
        now=1_000_000.0,
    )
    second = first + NOTE_ONLY
    decision = decide_flush(
        content=second,
        state=load_state(state),
        now=1_000_000.0 + 10_000,
        force=False,
    )
    assert decision["flush"] is False
    assert decision["reason"] == "no_state_change"
    assert sha256_text(second) != sha256_text(first)


def test_under_180s_blocks_flush(tmp_path: Path) -> None:
    first = BASE + STATE_LINE
    second = first + STATE_LINE_2
    state = {
        "last_flushed_sha256": sha256_text(first),
        "last_flushed_at": 1_000_000.0,
        "state_change_fingerprints": state_change_fingerprints(first),
    }
    decision = decide_flush(
        content=second,
        state=state,
        now=1_000_000.0 + 60,  # < 180s
        force=False,
    )
    assert decision["flush"] is False
    assert decision["reason"] == "under_180s"


def test_state_change_after_180s_flushes(tmp_path: Path) -> None:
    first = BASE + STATE_LINE
    second = first + STATE_LINE_2
    state = {
        "last_flushed_sha256": sha256_text(first),
        "last_flushed_at": 1_000_000.0,
        "state_change_fingerprints": state_change_fingerprints(first),
    }
    decision = decide_flush(
        content=second,
        state=state,
        now=1_000_000.0 + FLUSH_MIN_INTERVAL_S,
        force=False,
    )
    assert decision["flush"] is True
    assert decision["reason"] == "state_change"


def test_force_flushes_even_under_180s(tmp_path: Path) -> None:
    first = BASE + STATE_LINE
    second = first + STATE_LINE_2
    state = {
        "last_flushed_sha256": sha256_text(first),
        "last_flushed_at": 1_000_000.0,
        "state_change_fingerprints": state_change_fingerprints(first),
    }
    decision = decide_flush(
        content=second,
        state=state,
        now=1_000_000.0 + 1,
        force=True,
    )
    assert decision["flush"] is True
    assert decision["reason"] == "force"


def test_force_idempotent_same_content(tmp_path: Path) -> None:
    """Same content never flushes twice, even with --force."""
    content = BASE + STATE_LINE
    state = {
        "last_flushed_sha256": sha256_text(content),
        "last_flushed_at": 1_000_000.0,
        "state_change_fingerprints": state_change_fingerprints(content),
    }
    decision = decide_flush(
        content=content, state=state, now=1_000_000.0 + 10_000, force=True
    )
    assert decision["flush"] is False
    assert decision["reason"] == "unchanged"


def test_cli_writes_payload_and_mark_flushed(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.md"
    state = tmp_path / "mirror-state.json"
    payload = tmp_path / "ledger.md.payload"
    content = BASE + STATE_LINE
    ledger.write_text(content, encoding="utf-8")

    t0 = 2_000_000.0
    proc = _run(
        [
            "--ledger",
            str(ledger),
            "--state",
            str(state),
            "--payload",
            str(payload),
            "--now",
            str(t0),
        ]
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["flush"] is True
    assert out["sha256"] == sha256_text(content)
    assert payload.is_file()
    assert payload.read_text(encoding="utf-8") == content
    # State not updated yet
    assert not state.is_file() or load_state(state).get("last_flushed_sha256") is None

    mark = _run(
        [
            "--mark-flushed",
            out["sha256"],
            "--state",
            str(state),
            "--ledger",
            str(ledger),
            "--now",
            str(t0),
        ]
    )
    assert mark.returncode == 0, mark.stderr
    st = load_state(state)
    assert st["last_flushed_sha256"] == out["sha256"]

    # Idempotent second decide
    again = _run(
        [
            "--ledger",
            str(ledger),
            "--state",
            str(state),
            "--payload",
            str(payload),
            "--force",
            "--now",
            str(t0 + 10_000),
        ]
    )
    assert again.returncode == 0
    out2 = json.loads(again.stdout)
    assert out2["flush"] is False
    assert out2["reason"] == "unchanged"
