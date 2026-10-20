#!/usr/bin/env python3
"""
Ledger mirror flush decision helper (MM-010).

Bots push one overwritten `ledger.md` to branch `data/ledger` (never main).
This tool only decides *whether* to flush and writes a local payload copy;
it never talks to the network.

Flush is true only when:
  - content sha256 changed since last successful flush, AND
  - at least one state-change line was added since last flush, AND
  - >= 180 seconds have elapsed since last flush,
  OR `--force` is set.

Idempotent: the same content sha256 never flushes twice.
State is updated only via `--mark-flushed <sha256>`.

SEC-MM010-1: before any flush, scan with tools.secret_scan.looks_like_secret
(shared denylist; SEC-MM020c-2). Secrets refuse the flush
(reason=secret_detected, line numbers only); --force cannot bypass.
Matched secret text is never printed.

Stdlib only (+ shared tools.secret_scan; no new deps).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.secret_scan import looks_like_secret  # noqa: E402  — shared scanner (SEC-MM020c-2)

FLUSH_MIN_INTERVAL_S = 180

# Lines that count as state changes for the mirror contract.
STATE_CHANGE_RE = re.compile(
    r"\b("
    r"assigned|"
    r"done|"
    r"blocked|"
    r"verdict|"
    r"merge[ds]?|"
    r"handoff|"
    r"handed\s+to"
    r")\b",
    re.IGNORECASE,
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


def state_change_fingerprints(text: str) -> list[str]:
    """Stable fingerprints of lines that match the state-change vocabulary."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or not STATE_CHANGE_RE.search(line):
            continue
        fp = hashlib.sha1(line.encode("utf-8")).hexdigest()
        if fp in seen:
            continue
        seen.add(fp)
        out.append(fp)
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
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state, indent=2, sort_keys=True) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)


def decide_flush(
    *,
    content: str,
    state: dict[str, Any],
    now: float,
    force: bool = False,
) -> dict[str, Any]:
    """
    Return decision dict: flush, sha256, reason (+ payload filled by caller).
    """
    digest = sha256_text(content)
    last_sha = state.get("last_flushed_sha256")
    last_at = state.get("last_flushed_at")
    prev_fps = set(state.get("state_change_fingerprints") or [])
    cur_fps = state_change_fingerprints(content)
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
    content: str | None,
    now: float,
) -> dict[str, Any]:
    """Record a successful flush. Fingerprints come from current ledger content."""
    state = load_state(state_path)
    fps = state_change_fingerprints(content) if content is not None else list(
        state.get("state_change_fingerprints") or []
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
        description="Decide whether to flush the local ledger mirror (MM-010)"
    )
    parser.add_argument("--ledger", type=Path, help="Path to local task-ledger.md")
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
        help="When flushing, write ledger bytes here",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Flush even if under 180s / no new state-change (still idempotent on sha)",
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

    if args.mark_flushed:
        content: str | None = None
        if args.ledger is not None:
            if not args.ledger.is_file():
                print(f"ledger not found: {args.ledger}", file=sys.stderr)
                return 1
            content = args.ledger.read_text(encoding="utf-8")
            digest = sha256_text(content)
            if digest != args.mark_flushed:
                print(
                    f"error: --mark-flushed {args.mark_flushed} does not match "
                    f"ledger sha256 {digest}",
                    file=sys.stderr,
                )
                return 1
        mark_flushed(
            state_path=args.state,
            sha256=args.mark_flushed,
            content=content,
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

    if args.ledger is None:
        print("error: --ledger is required unless using --mark-flushed", file=sys.stderr)
        return 2
    if not args.ledger.is_file():
        print(f"ledger not found: {args.ledger}", file=sys.stderr)
        return 1

    content = args.ledger.read_text(encoding="utf-8")
    state = load_state(args.state)
    decision = decide_flush(
        content=content, state=state, now=now, force=bool(args.force)
    )

    out: dict[str, Any] = {
        "flush": decision["flush"],
        "sha256": decision["sha256"],
        "reason": decision["reason"],
    }
    if decision.get("reason") == "secret_detected":
        # Line numbers only — never echo matched secret text.
        out["lines"] = list(decision.get("lines") or [])
    if decision["flush"]:
        payload_path = args.payload
        if payload_path is None:
            payload_path = args.ledger.with_name("ledger.md.payload")
        payload_path.parent.mkdir(parents=True, exist_ok=True)
        payload_path.write_text(content, encoding="utf-8")
        out["payload"] = str(payload_path)

    print(json.dumps(out, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
