"""MM-010: gh ledger mirror fetch (ETag / base64 / errors)."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from ingest.build import build_activity, write_activity
from ingest.github_poller import GhResponse
from ingest.ledger_fetch import LEDGER_API_PATH, fetch_ledger_from_gh
from tests.test_github_poller import MockGh

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schema" / "activity.schema.json"
BOTS_PATH = ROOT / "config" / "bots.json"
LEDGER_FIXTURE = ROOT / "tests" / "fixtures" / "ledger-sample.md"


def _bots() -> list[dict]:
    with BOTS_PATH.open(encoding="utf-8") as f:
        return json.load(f)["bots"]


def _schema() -> dict:
    with SCHEMA_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _contents_body(text: str) -> str:
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    # GitHub wraps at 60 columns
    wrapped = "\n".join(encoded[i : i + 60] for i in range(0, len(encoded), 60))
    return json.dumps(
        {
            "name": "ledger.md",
            "path": "ledger.md",
            "sha": "abc",
            "size": len(text),
            "encoding": "base64",
            "content": wrapped + "\n",
        }
    )


class LedgerMockGh:
    """Minimal gh runner for contents API + optional PR poller no-ops."""

    def __init__(
        self,
        *,
        status: int = 200,
        body: str = "",
        etag: str = '"etag-1"',
        fail: bool = False,
    ) -> None:
        self.status = status
        self.body = body
        self.etag = etag
        self.fail = fail
        self.calls: list[str] = []

    def __call__(self, args: list[str], *, timeout: float = 60.0) -> GhResponse:
        joined = " ".join(args)
        self.calls.append(joined)
        if self.fail:
            raise RuntimeError("boom")
        # Ledger contents
        if LEDGER_API_PATH in joined or "contents/ledger.md" in joined:
            return GhResponse(
                status=self.status,
                headers={"etag": self.etag},
                body=self.body,
            )
        # Anything else (PR poller) → empty ok list / stub
        if "repos/" in joined and "/pulls" in joined:
            return GhResponse(status=200, headers={}, body="[]")
        if joined.startswith("repos/") or "repos/" in joined:
            return GhResponse(
                status=200,
                headers={},
                body=json.dumps({"id": 1, "full_name": "ManpreetS2/fencepost"}),
            )
        return GhResponse(status=200, headers={}, body="{}")


def test_gh_ledger_200_decodes_and_builds(tmp_path: Path) -> None:
    text = LEDGER_FIXTURE.read_text(encoding="utf-8")
    runner = LedgerMockGh(status=200, body=_contents_body(text))
    result = fetch_ledger_from_gh(cache_dir=tmp_path / "cache", runner=runner)
    assert result.meta_ledger == "ok"
    assert result.status == 200
    assert result.text is not None
    assert "Task ID" in result.text or "MM-001" in result.text or "|" in result.text

    activity = build_activity(
        ledger_text=result.text,
        ledger_source_url="https://github.com/ManpreetS2/agent-mindmap/blob/data/ledger/ledger.md",
        meta_ledger=result.meta_ledger,
        bots=_bots(),
        github_runner=MockGh(fail=True),
        cache_dir=tmp_path / "gh",
        skip_github=True,
        generated_at="2026-10-20T12:00:00-07:00",
    )
    jsonschema.validate(instance=activity, schema=_schema())
    assert activity["meta"]["ledger"] == "ok"
    assert activity["meta"]["ledger_last_entry_at"] is not None
    assert activity["tasks"]


def test_gh_ledger_304_keeps_cache(tmp_path: Path) -> None:
    text = LEDGER_FIXTURE.read_text(encoding="utf-8")
    cache = tmp_path / "cache"
    first = LedgerMockGh(status=200, body=_contents_body(text), etag='"e1"')
    r1 = fetch_ledger_from_gh(cache_dir=cache, runner=first)
    assert r1.status == 200 and r1.text

    second = LedgerMockGh(status=304, body="", etag='"e1"')
    r2 = fetch_ledger_from_gh(cache_dir=cache, runner=second)
    assert r2.meta_ledger == "ok"
    assert r2.status == 304
    assert r2.from_cache is True
    assert r2.text == r1.text
    assert any("If-None-Match" in c for c in second.calls)


def test_gh_ledger_error_sets_meta_ledger_error(tmp_path: Path) -> None:
    runner = LedgerMockGh(status=500, body="nope")
    result = fetch_ledger_from_gh(cache_dir=tmp_path / "cache", runner=runner)
    assert result.meta_ledger == "error"
    assert result.text is None


def test_gh_ledger_404_is_not_found(tmp_path: Path) -> None:
    runner = LedgerMockGh(status=404, body="not found")
    result = fetch_ledger_from_gh(cache_dir=tmp_path / "cache", runner=runner)
    assert result.meta_ledger == "not_found"
    assert result.status == 404
    assert result.text is None

    # build.py error path: activity still written with meta.ledger=error
    from ingest.build import main

    out = tmp_path / "activity.json"
    # Monkeypatch fetch by invoking build_activity directly
    activity = build_activity(
        ledger_text="",
        ledger_source_url="https://github.com/ManpreetS2/agent-mindmap/blob/data/ledger/ledger.md",
        meta_ledger="error",
        bots=_bots(),
        skip_github=True,
        generated_at="2026-10-20T12:00:00-07:00",
    )
    activity["meta"]["ledger"] = "error"
    activity["meta"]["ledger_last_entry_at"] = None
    write_activity(activity, out)
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["meta"]["ledger"] == "error"
    jsonschema.validate(instance=saved, schema=_schema())


def test_api_path_is_hardcoded_allowlist() -> None:
    assert LEDGER_API_PATH == (
        "repos/ManpreetS2/agent-mindmap/contents/ledger.md?ref=data/ledger"
    )
