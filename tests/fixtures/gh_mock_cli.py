#!/usr/bin/env python3
"""Test-only `gh` stub: auth status + `gh api --include` via recorded fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ingest.github_poller import GhResponse  # noqa: E402
from tests.test_events_fetch import EventsMockGh  # noqa: E402
from tests.test_github_poller import MockGh  # noqa: E402


def _emit(resp: GhResponse) -> None:
    status_line = f"HTTP/1.1 {resp.status or 200} OK"
    print(status_line)
    for key, value in resp.headers.items():
        print(f"{key}: {value}")
    print()
    if resp.body:
        print(resp.body)


def main() -> int:
    argv = sys.argv[1:]
    if argv[:2] == ["auth", "status"]:
        return 0

    if len(argv) >= 2 and argv[0] == "api" and argv[1] == "--include":
        args = argv[2:]
        path = args[-1] if args else ""
        if "events.jsonl" in path or path.startswith("repos/ManpreetS2/agent-mindmap/contents/events"):
            resp = EventsMockGh()(
                args,
            )
        else:
            resp = MockGh()(args)
        _emit(resp)
        return 0 if (resp.status or 0) < 400 else 1

    print("gh_mock_cli: unsupported invocation", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
