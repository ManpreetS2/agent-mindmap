#!/usr/bin/env python3
"""
MM-020b: opt-in NetworkEvent JSONL emitter (stdlib only).

Appends one sanitized JSON line per event with a single O_APPEND write (≤ PIPE_BUF).
Opens the JSONL path with O_NOFOLLOW (refuses symlinks) and creates new files mode 0o600.

Summary contract: **short sanitized summary** only — never raw transcripts. Whitespace is
collapsed, secrets are refused (MM-010 scan), and text is capped at SUMMARY_MAX_CHARS (240)
before emit. Longer input is truncated with a trailing ellipsis character.

No network; no token reads. Secret scan reuses ingest.github_poller._looks_like_secret.
"""

from __future__ import annotations

import errno
import hashlib
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from ingest.attribute import load_bots  # noqa: E402
from ingest.github_poller import _looks_like_secret  # noqa: E402 — MM-010 pattern

logger = logging.getLogger(__name__)

PIPE_BUF = 4096
SUMMARY_MAX_CHARS = 240
JSONL_FILE_MODE = 0o600
EVENT_SOURCE = "network-event"
DEFAULT_PROVENANCE = "agent-reported"
DEFAULT_EVENT_TYPE = "message"
SCHEMA_PATH = _ROOT / "schema" / "activity.schema.json"

# MM-020b / QA-MM020b-2: extra free-text patterns beyond MM-010 github_poller scan.
_RE_OPENAI_SK = re.compile(r"sk-[A-Za-z0-9_-]+")
_RE_AWS_AKIA = re.compile(r"AKIA[0-9A-Z]{16}")
_RE_JWT = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
_RE_PEM_PRIVATE = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.IGNORECASE
)
_RE_EMAIL = re.compile(
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
    re.IGNORECASE,
)

_FREE_TEXT_SCANNERS: tuple[re.Pattern[str], ...] = (
    _RE_OPENAI_SK,
    _RE_AWS_AKIA,
    _RE_JWT,
    _RE_PEM_PRIVATE,
    _RE_EMAIL,
)


def _free_text_looks_like_secret(text: str) -> bool:
    """Refuse OpenAI/AWS/JWT/PEM/email patterns plus MM-010 credential scan."""
    if _looks_like_secret(text):
        return True
    return any(p.search(text) for p in _FREE_TEXT_SCANNERS)


def _refuse_free_text_field(field: str, value: str) -> None:
    if _free_text_looks_like_secret(value):
        raise SecretRefusedError(f"{field} refused: secret-like content")


class EventEmitError(ValueError):
    """Base error for emitter failures."""


class SecretRefusedError(EventEmitError):
    """Summary or payload matched the secret scanner."""


class LineTooLongError(EventEmitError):
    """Serialized line exceeds PIPE_BUF even after summary truncation."""


class SymlinkRefusedError(EventEmitError):
    """JSONL path is a symlink or O_NOFOLLOW rejected the open."""


def event_id_from_locator(locator: str) -> str:
    """Deterministic id: same locator → same id (sha1, stable across processes)."""
    return hashlib.sha1(f"{EVENT_SOURCE}{locator}".encode("utf-8")).hexdigest()


def build_locator(
    *,
    ts: str,
    sender: str,
    group: str,
    summary: str,
    event_type: str = DEFAULT_EVENT_TYPE,
    recipients: list[str] | None = None,
    task_id: str | None = None,
    related_id: str | None = None,
) -> str:
    """Canonical locator string for id generation (sorted recipients)."""
    rec = ",".join(sorted(recipients)) if recipients else ""
    parts = [
        ts,
        sender,
        group,
        event_type,
        summary,
        rec,
        task_id or "",
        related_id or "",
    ]
    return "|".join(parts)


def sanitize_summary(text: str, *, max_chars: int = SUMMARY_MAX_CHARS) -> str:
    """
    Short sanitized summary: normalize whitespace, cap length, refuse secrets.

    Raises SecretRefusedError if the text looks like a credential or banned key name.
    """
    cleaned = " ".join(text.split())
    if not cleaned:
        raise EventEmitError("summary must not be empty")
    if _free_text_looks_like_secret(cleaned):
        raise SecretRefusedError("summary refused: secret-like content")
    if len(cleaned) > max_chars:
        cleaned = cleaned[: max_chars - 1] + "…"
    return cleaned


def summary_safe_for_emit(text: str) -> tuple[str | None, str | None]:
    """
    Secret-safe summary helper for callers.

    Returns (summary, None) on success or (None, reason) when refused.
    """
    try:
        return sanitize_summary(text), None
    except SecretRefusedError as exc:
        return None, str(exc)
    except EventEmitError as exc:
        return None, str(exc)


def _known_bot_ids() -> set[str]:
    return {str(bot["id"]) for bot in load_bots()}


def _partition_recipients(
    recipients: list[str] | None,
) -> tuple[list[str], list[str]]:
    """Split explicit recipients into config-known ids vs unknown (never invent)."""
    if not recipients:
        return [], []
    known_ids = _known_bot_ids()
    known: list[str] = []
    unknown: list[str] = []
    for recipient in recipients:
        if recipient in known_ids:
            known.append(recipient)
        else:
            unknown.append(recipient)
    return known, unknown


def build_network_event(
    *,
    ts: str,
    sender: str,
    group: str,
    summary: str,
    recipients: list[str] | None = None,
    task_id: str | None = None,
    related_id: str | None = None,
    event_type: str = DEFAULT_EVENT_TYPE,
    provenance: str = DEFAULT_PROVENANCE,
    locator: str | None = None,
) -> dict[str, Any]:
    """Build a networkEvent-shaped dict (schema $defs/networkEvent)."""
    _refuse_free_text_field("sender", sender)
    _refuse_free_text_field("group", group)
    _refuse_free_text_field("type", event_type)
    _refuse_free_text_field("provenance", provenance)
    if task_id is not None:
        _refuse_free_text_field("task_id", task_id)
    if related_id is not None:
        _refuse_free_text_field("related_id", related_id)
    if recipients:
        for recipient in recipients:
            _refuse_free_text_field("recipient", recipient)

    safe_summary = sanitize_summary(summary)
    known_recipients, unknown_recipients = _partition_recipients(recipients)
    if unknown_recipients:
        logger.warning(
            "unknown recipient id(s) in explicit recipients: %s",
            ", ".join(sorted(unknown_recipients)),
        )

    loc = locator or build_locator(
        ts=ts,
        sender=sender,
        group=group,
        summary=safe_summary,
        event_type=event_type,
        recipients=recipients,
        task_id=task_id,
        related_id=related_id,
    )
    evt: dict[str, Any] = {
        "id": event_id_from_locator(loc),
        "ts": ts,
        "sender": sender,
        "group": group,
        "type": event_type,
        "summary": safe_summary,
        "provenance": provenance,
    }
    if known_recipients:
        evt["recipients"] = list(known_recipients)
    if unknown_recipients:
        evt["unknown_recipients"] = list(unknown_recipients)
    if task_id is not None:
        evt["task_id"] = task_id
    if related_id is not None:
        evt["related_id"] = related_id
    return evt


def _serialize_line(event: dict[str, Any]) -> bytes:
    blob = json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if _free_text_looks_like_secret(blob):
        raise SecretRefusedError("serialized event refused: secret-like content")
    line = (blob + "\n").encode("utf-8")
    if b"\n" in blob.encode("utf-8"):
        raise EventEmitError("event must not contain embedded newlines")
    return line


def _fit_line_to_pipe_buf(event: dict[str, Any], *, max_bytes: int = PIPE_BUF) -> bytes:
    line = _serialize_line(event)
    if len(line) <= max_bytes:
        return line

    summary = str(event.get("summary") or "")
    if not summary:
        raise LineTooLongError(f"line {len(line)} bytes exceeds PIPE_BUF {max_bytes}")

    # Truncate summary until the line fits (or refuse).
    low, high = 0, len(summary)
    best: bytes | None = None
    while low <= high:
        mid = (low + high) // 2
        trial = dict(event)
        trial["summary"] = summary[:mid] + ("…" if mid < len(summary) else "")
        try:
            candidate = _serialize_line(trial)
        except SecretRefusedError:
            raise
        if len(candidate) <= max_bytes:
            best = trial
            low = mid + 1
        else:
            high = mid - 1

    if best is None:
        raise LineTooLongError(f"line exceeds PIPE_BUF {max_bytes} after truncation")
    loc = build_locator(
        ts=str(best["ts"]),
        sender=str(best["sender"]),
        group=str(best["group"]),
        summary=str(best["summary"]),
        event_type=str(best.get("type", DEFAULT_EVENT_TYPE)),
        recipients=best.get("recipients"),
        task_id=best.get("task_id"),
        related_id=best.get("related_id"),
    )
    best["id"] = event_id_from_locator(loc)
    return _serialize_line(best)


def _open_jsonl_append(path: Path) -> int:
    """O_APPEND + O_NOFOLLOW; create with 0o600; fchmod existing files to 0o600."""
    if path.is_symlink():
        raise SymlinkRefusedError(f"refusing symlink JSONL path: {path}")
    existed = path.exists()
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, JSONL_FILE_MODE)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.EMLINK):
            raise SymlinkRefusedError(f"refusing symlink JSONL path: {path}") from exc
        raise
    if existed:
        os.fchmod(fd, JSONL_FILE_MODE)
    return fd


def append_event(
    path: Path,
    event: dict[str, Any],
    *,
    max_line_bytes: int = PIPE_BUF,
) -> int:
    """
    Append one JSONL line with a single O_APPEND write.

    Returns bytes written. Raises SecretRefusedError or LineTooLongError on refusal.
    """
    line = _fit_line_to_pipe_buf(event, max_bytes=max_line_bytes)
    if len(line) > max_line_bytes:
        raise LineTooLongError(f"line {len(line)} exceeds limit {max_line_bytes}")

    fd = _open_jsonl_append(path)
    try:
        written = os.write(fd, line)
        if written != len(line):
            raise OSError(f"short write: {written} of {len(line)}")
        return written
    finally:
        os.close(fd)


def emit_message(
    path: Path,
    *,
    sender: str,
    group: str,
    summary: str,
    ts: str | None = None,
    recipients: list[str] | None = None,
    task_id: str | None = None,
    related_id: str | None = None,
    locator: str | None = None,
) -> dict[str, Any]:
    """Build agent-reported message event, append to path, return the event."""
    when = ts or datetime.now(timezone.utc).isoformat()
    event = build_network_event(
        ts=when,
        sender=sender,
        group=group,
        summary=summary,
        recipients=recipients,
        task_id=task_id,
        related_id=related_id,
        locator=locator,
    )
    append_event(path, event)
    return event


def _network_event_validator() -> Any:
    """Validator for $defs/networkEvent with $ref resolution against the full schema."""
    import jsonschema

    with SCHEMA_PATH.open(encoding="utf-8") as f:
        root = json.load(f)
    sub = root["$defs"]["networkEvent"]
    schema = {
        "$schema": root.get(
            "$schema", "https://json-schema.org/draft/2020-12/schema"
        ),
        "$defs": root["$defs"],
        **{k: v for k, v in sub.items()},
    }
    return jsonschema.Draft202012Validator(schema)


def validate_network_event(event: dict[str, Any]) -> None:
    """Validate against schema/activity.schema.json $defs/networkEvent."""
    _network_event_validator().validate(event)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Append one NetworkEvent JSONL line")
    parser.add_argument("--out", type=Path, required=True, help="JSONL file path")
    parser.add_argument("--sender", required=True)
    parser.add_argument("--group", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--ts", default=None)
    parser.add_argument("--recipients", nargs="*", default=None)
    parser.add_argument("--task-id", default=None)
    parser.add_argument("--related-id", default=None)
    args = parser.parse_args(argv)

    try:
        evt = emit_message(
            args.out,
            sender=args.sender,
            group=args.group,
            summary=args.summary,
            ts=args.ts,
            recipients=args.recipients,
            task_id=args.task_id,
            related_id=args.related_id,
        )
    except EventEmitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps({"id": evt["id"], "bytes": "ok"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
