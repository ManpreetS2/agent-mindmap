"""MM-020b: NetworkEvent JSONL emitter."""

from __future__ import annotations

import json
import multiprocessing as mp
from pathlib import Path

import pytest

from ingest.github_poller import _looks_like_secret
from tools.event_emit import (
    PIPE_BUF,
    SecretRefusedError,
    append_event,
    build_locator,
    build_network_event,
    emit_message,
    event_id_from_locator,
    sanitize_summary,
    summary_safe_for_emit,
    validate_network_event,
)

def test_deterministic_event_id() -> None:
    loc = build_locator(
        ts="2026-10-20T12:00:00+00:00",
        sender="dev-1",
        group="build",
        summary="hello",
    )
    a = event_id_from_locator(loc)
    b = event_id_from_locator(loc)
    assert a == b
    assert len(a) == 40


def test_build_network_event_matches_schema() -> None:
    evt = build_network_event(
        ts="2026-10-20T12:00:00+00:00",
        sender="architect",
        group="build",
        summary="Ship MM-020b emitter",
        recipients=["dev-1"],
        task_id="MM-020b",
    )
    assert evt["type"] == "message"
    assert evt["provenance"] == "agent-reported"
    validate_network_event(evt)


def test_same_inputs_same_id_via_build() -> None:
    kwargs = {
        "ts": "2026-10-20T12:00:00+00:00",
        "sender": "director",
        "group": "qr",
        "summary": "Review gate",
    }
    assert build_network_event(**kwargs)["id"] == build_network_event(**kwargs)["id"]


def test_secret_summary_refused() -> None:
    with pytest.raises(SecretRefusedError):
        sanitize_summary("token ghp_abcdefghijklmnopqrstuvwxyz1234567890AB")
    safe, err = summary_safe_for_emit("ghp_deadbeef")
    assert safe is None
    assert err


def test_emit_refuses_secret_in_summary(tmp_path: Path) -> None:
    out = tmp_path / "events.jsonl"
    with pytest.raises(SecretRefusedError):
        emit_message(
            out,
            sender="dev-1",
            group="build",
            summary="Authorization: Bearer abcdef",
            ts="2026-10-20T12:00:00+00:00",
        )
    assert not out.exists() or out.stat().st_size == 0


def test_line_within_pipe_buf(tmp_path: Path) -> None:
    out = tmp_path / "events.jsonl"
    evt = emit_message(
        out,
        sender="dev-1",
        group="build",
        summary="x" * 3000,
        ts="2026-10-20T12:00:00+00:00",
    )
    line = out.read_bytes()
    assert len(line) <= PIPE_BUF
    assert line.endswith(b"\n")
    validate_network_event(evt)


def _worker_append(path_str: str, worker_id: int, count: int) -> None:
    path = Path(path_str)
    for i in range(count):
        emit_message(
            path,
            sender="dev-1",
            group="build",
            summary=f"w{worker_id}-line-{i}",
            ts=f"2026-10-20T12:00:{worker_id:02d}:{i % 60:02d}+00:00",
        )


def test_concurrent_append_no_lost_lines(tmp_path: Path) -> None:
    """N processes × M lines — all lines present, valid JSON, none corrupted."""
    out = tmp_path / "shared.jsonl"
    workers = 8
    per_worker = 500
    ctx = mp.get_context("fork")
    with ctx.Pool(workers) as pool:
        pool.starmap(
            _worker_append,
            [(str(out), wid, per_worker) for wid in range(workers)],
        )

    raw = out.read_bytes()
    assert raw
    lines = raw.splitlines()
    assert len(lines) == workers * per_worker
    ids: set[str] = set()
    for line in lines:
        assert len(line) <= PIPE_BUF
        obj = json.loads(line)
        validate_network_event(obj)
        assert obj["provenance"] == "agent-reported"
        assert obj["type"] == "message"
        eid = obj["id"]
        assert eid not in ids
        ids.add(eid)
    assert not _looks_like_secret(raw.decode("utf-8", errors="replace"))


def test_single_write_append_only(tmp_path: Path) -> None:
    """Each append adds exactly one newline-terminated record."""
    out = tmp_path / "one.jsonl"
    emit_message(
        out,
        sender="dev-2",
        group="build",
        summary="first",
        ts="2026-10-20T12:00:00+00:00",
    )
    emit_message(
        out,
        sender="dev-2",
        group="build",
        summary="second",
        ts="2026-10-20T12:00:01+00:00",
    )
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["summary"] == "first"
    assert json.loads(lines[1])["summary"] == "second"
