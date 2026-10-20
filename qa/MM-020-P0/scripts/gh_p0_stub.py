#!/usr/bin/env python3
"""Realistic gh stub for MM-020-P0 QA: ledger missing, GitHub+events present."""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

ROOT = Path("/tmp/qa-mm020p0/checkout")
sys.path.insert(0, str(ROOT))

from ingest.github_poller import GhResponse  # noqa: E402
from tests.test_github_poller import MockGh  # noqa: E402

EVENTS = [
    {
        "id": "p0-net-1",
        "ts": "2026-10-20T22:00:00+00:00",
        "sender": "director",
        "recipients": ["architect"],
        "group": "build",
        "type": "message",
        "summary": "P0 demo message to architect",
        "provenance": "agent-reported",
        "repo": "ManpreetS2/agent-mindmap",
    },
    {
        "id": "p0-net-2",
        "ts": "2026-10-20T22:01:00+00:00",
        "sender": "architect",
        "recipients": ["qa-verifier"],
        "group": "qr",
        "type": "message",
        "summary": "Cross-group ping to QA",
        "provenance": "agent-reported",
        "repo": "ManpreetS2/agent-mindmap",
    },
    {
        "id": "p0-net-3",
        "ts": "2026-10-20T22:02:00+00:00",
        "sender": "dev-1",
        "recipients": ["dev-2", "director"],
        "group": "build",
        "type": "message",
        "summary": "Multi-recipient status",
        "provenance": "agent-reported",
        "repo": "ManpreetS2/fencepost",
    },
]


def _events_body() -> str:
    text = "".join(json.dumps(e, sort_keys=True) + "\n" for e in EVENTS)
    encoded = base64.b64encode(text.encode()).decode("ascii")
    wrapped = "\n".join(encoded[i : i + 60] for i in range(0, len(encoded), 60))
    return json.dumps(
        {
            "name": "events.jsonl",
            "path": "events.jsonl",
            "sha": "p0qa",
            "encoding": "base64",
            "content": wrapped + "\n",
        }
    )


def _emit(resp: GhResponse) -> None:
    print(f"HTTP/1.1 {resp.status or 200} OK")
    for k, v in resp.headers.items():
        print(f"{k}: {v}")
    print()
    if resp.body:
        print(resp.body)


def main() -> int:
    argv = sys.argv[1:]
    if argv[:2] == ["auth", "status"]:
        return 0
    if not (len(argv) >= 2 and argv[0] == "api" and argv[1] == "--include"):
        print("gh_p0_stub: unsupported", file=sys.stderr)
        return 1
    args = argv[2:]
    path = args[-1] if args else ""
    # data/ledger missing
    if "contents/ledger.md" in path or "data/ledger" in path and "ledger.md" in path:
        _emit(
            GhResponse(
                status=404,
                headers={"x-ratelimit-remaining": "5000"},
                body='{"message":"Not Found"}',
            )
        )
        return 1
    if "events.jsonl" in path or "contents/events" in path:
        _emit(
            GhResponse(
                status=200,
                headers={"etag": '"p0-events"', "x-ratelimit-remaining": "5000"},
                body=_events_body(),
            )
        )
        return 0
    # otherwise recorded MockGh fixtures (fencepost PRs etc.)
    resp = MockGh()(args)
    _emit(resp)
    return 0 if (resp.status or 0) < 400 else 1


if __name__ == "__main__":
    raise SystemExit(main())
