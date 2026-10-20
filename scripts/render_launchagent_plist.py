#!/usr/bin/env python3
"""Render ops/com.manpreet.mindmap.plist with plistlib (no sed). MM-020-OPS."""

from __future__ import annotations

import argparse
import plistlib
import sys
from pathlib import Path
from typing import Any

PLACEHOLDER_REPO = "REPLACE_WITH_AGENT_MINDMAP_REPO_ROOT"
PLACEHOLDER_LEDGER = "REPLACE_WITH_ABSOLUTE_PATH_TO_task-ledger.md"
PLACEHOLDER_LOG = "REPLACE_WITH_ABSOLUTE_LOG_DIR"


def _substitute(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, str):
        out = value
        for needle, repl in mapping.items():
            out = out.replace(needle, repl)
        return out
    if isinstance(value, list):
        return [_substitute(item, mapping) for item in value]
    if isinstance(value, dict):
        return {key: _substitute(val, mapping) for key, val in value.items()}
    return value


def render_plist(
    template_path: Path,
    *,
    repo_root: Path,
    ledger_path: Path,
    log_dir: Path,
) -> dict[str, Any]:
    with template_path.open("rb") as f:
        data = plistlib.load(f)
    mapping = {
        PLACEHOLDER_REPO: str(repo_root.resolve()),
        PLACEHOLDER_LEDGER: str(ledger_path.resolve()),
        PLACEHOLDER_LOG: str(log_dir.resolve()),
    }
    rendered = _substitute(data, mapping)
    if not isinstance(rendered, dict):
        raise TypeError("plist root must be a dict")
    _assert_no_placeholders(rendered)
    return rendered


def _assert_no_placeholders(obj: Any) -> None:
    if isinstance(obj, str):
        if "REPLACE_WITH_" in obj:
            raise ValueError(f"unsubstituted placeholder in plist: {obj!r}")
        return
    if isinstance(obj, list):
        for item in obj:
            _assert_no_placeholders(item)
        return
    if isinstance(obj, dict):
        for val in obj.values():
            _assert_no_placeholders(val)


def write_plist(data: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as f:
        plistlib.dump(data, f, fmt=plistlib.FMT_XML)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render mindmap LaunchAgent plist")
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--log-dir", type=Path, required=True)
    args = parser.parse_args(argv)

    if not args.ledger.is_file():
        print(f"error: ledger not found: {args.ledger}", file=sys.stderr)
        return 1

    try:
        data = render_plist(
            args.template,
            repo_root=args.repo_root,
            ledger_path=args.ledger,
            log_dir=args.log_dir,
        )
    except (ValueError, TypeError, plistlib.InvalidFileException) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    write_plist(data, args.output)

    # Round-trip validate (same as plutil -lint for structure).
    with args.output.open("rb") as f:
        plistlib.load(f)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
