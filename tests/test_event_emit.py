"""MM-020b: NetworkEvent JSONL emitter."""

from __future__ import annotations

import json
import multiprocessing as mp
import os
import stat
from pathlib import Path

import pytest

from ingest.github_poller import _looks_like_secret
from tools.event_emit import (
    JSONL_FILE_MODE,
    PIPE_BUF,
    SUMMARY_MAX_CHARS,
    SecretRefusedError,
    SymlinkRefusedError,
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


@pytest.mark.parametrize(
    "summary",
    [
        "sk-proj-abcdefghijklmnopqrstuvwxyz1234567890ABCDEF",
        "AKIAIOSFODNN7EXAMPLE",
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0In0.signature",
        "-----BEGIN PRIVATE KEY----- MIIEvQIBADANBg -----END PRIVATE KEY-----",
        "contact alice@example.com please",
    ],
)
def test_emit_refuses_extended_secret_patterns(tmp_path: Path, summary: str) -> None:
    out = tmp_path / "events.jsonl"
    with pytest.raises(SecretRefusedError):
        emit_message(
            out,
            sender="dev-1",
            group="build",
            summary=summary,
            ts="2026-10-20T12:00:00+00:00",
        )
    assert not out.exists()


def test_preexisting_jsonl_mode_tightened_to_600(tmp_path: Path) -> None:
    out = tmp_path / "events.jsonl"
    out.write_text("", encoding="utf-8")
    os.chmod(out, 0o644)
    emit_message(
        out,
        sender="dev-1",
        group="build",
        summary="preexisting mode",
        ts="2026-10-20T12:00:00+00:00",
    )
    assert stat.S_IMODE(out.stat().st_mode) == JSONL_FILE_MODE


def test_unknown_recipients_partitioned_and_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    out = tmp_path / "rec.jsonl"
    with caplog.at_level("WARNING"):
        evt = emit_message(
            out,
            sender="director",
            group="build",
            summary="explicit ping",
            recipients=["dev-1", "not-a-real-bot"],
            ts="2026-10-20T15:00:01+00:00",
        )
    assert evt["recipients"] == ["dev-1"]
    assert evt["unknown_recipients"] == ["not-a-real-bot"]
    assert "not-a-real-bot" in caplog.text
    validate_network_event(evt)
    line = json.loads(out.read_text(encoding="utf-8").strip())
    assert line["unknown_recipients"] == ["not-a-real-bot"]


def test_recipients_not_inferred_from_mentions(tmp_path: Path) -> None:
    out = tmp_path / "rec.jsonl"
    evt = emit_message(
        out,
        sender="director",
        group="build",
        summary="Hey @dev-1 and @qa please review this",
        ts="2026-10-20T15:00:00+00:00",
    )
    assert "recipients" not in evt
    assert "unknown_recipients" not in evt


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


def test_summary_capped_at_240_chars() -> None:
    long_text = "word " * 200
    capped = sanitize_summary(long_text)
    assert len(capped) <= SUMMARY_MAX_CHARS
    assert capped.endswith("…")
    evt = build_network_event(
        ts="2026-10-20T12:00:00+00:00",
        sender="dev-1",
        group="build",
        summary=long_text,
    )
    assert len(evt["summary"]) <= SUMMARY_MAX_CHARS


def test_jsonl_file_mode_0o600(tmp_path: Path) -> None:
    out = tmp_path / "events.jsonl"
    emit_message(
        out,
        sender="dev-1",
        group="build",
        summary="mode check",
        ts="2026-10-20T12:00:00+00:00",
    )
    mode = out.stat().st_mode & 0o777
    assert mode == JSONL_FILE_MODE


def test_refuse_symlink_jsonl_path(tmp_path: Path) -> None:
    target = tmp_path / "real.jsonl"
    link = tmp_path / "events.jsonl"
    link.symlink_to(target)
    with pytest.raises(SymlinkRefusedError):
        emit_message(
            link,
            sender="dev-1",
            group="build",
            summary="via symlink",
            ts="2026-10-20T12:00:00+00:00",
        )
    assert not target.exists() or target.stat().st_size == 0


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
    assert len(evt["summary"]) <= SUMMARY_MAX_CHARS
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


def test_append_event_defaults_missing_provenance(tmp_path: Path) -> None:
    out = tmp_path / "events.jsonl"
    evt = build_network_event(
        ts="2026-10-20T12:00:00+00:00",
        sender="dev-1",
        group="build",
        summary="provenance default",
    )
    del evt["provenance"]
    append_event(out, evt)
    row = json.loads(out.read_text(encoding="utf-8").strip())
    assert row["provenance"] == "agent-reported"
    validate_network_event(row)


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
