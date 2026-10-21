"""
Fetch mirrored ledger.md from GitHub via `gh api` (MM-010).

Allowlisted only:
  GET repos/ManpreetS2/agent-mindmap/contents/ledger.md?ref=data/ledger

Uses ETag caching (304 → keep cached body). Base64-decodes `content`.
No tokens — relies on host `gh` login. Read-only.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .github_poller import ETagCache, GhResponse, GhRunner, default_gh_runner

LEDGER_REPO = "ManpreetS2/agent-mindmap"
LEDGER_FILE = "ledger.md"
LEDGER_REF = "data/ledger"
# Hardcoded allowlist — never take repo/path/ref from caller input.
LEDGER_API_PATH = f"repos/{LEDGER_REPO}/contents/{LEDGER_FILE}?ref={LEDGER_REF}"
LEDGER_SOURCE_URL = (
    f"https://github.com/{LEDGER_REPO}/blob/{LEDGER_REF}/{LEDGER_FILE}"
)


@dataclass
class LedgerFetchResult:
    text: str | None = None
    meta_ledger: str = "ok"  # ok | not_found | error | skipped
    etag: str | None = None
    status: int = 0
    from_cache: bool = False
    errors: list[str] = field(default_factory=list)


def _decode_contents_payload(data: dict[str, Any]) -> str:
    encoding = (data.get("encoding") or "").lower()
    content = data.get("content") or ""
    if encoding != "base64":
        raise ValueError(f"unsupported contents encoding {encoding!r}")
    raw = base64.b64decode("".join(str(content).split()))
    return raw.decode("utf-8")


def _assert_allowlisted_contents(data: dict[str, Any]) -> None:
    name = data.get("name")
    path = data.get("path")
    if name not in (None, LEDGER_FILE) and path not in (None, LEDGER_FILE):
        raise ValueError(f"refusing unexpected contents path {path!r}")
    if path is not None and path != LEDGER_FILE:
        raise ValueError(f"refusing unexpected contents path {path!r}")
    if name is not None and name != LEDGER_FILE:
        raise ValueError(f"refusing unexpected contents name {name!r}")


class LedgerFetcher:
    def __init__(
        self,
        *,
        cache_dir: Path | None = None,
        runner: GhRunner | None = None,
    ) -> None:
        root = Path(__file__).resolve().parents[1]
        self.cache = ETagCache(cache_dir or (root / "ingest" / ".cache" / "ledger"))
        self.runner: GhRunner = runner or default_gh_runner

    def fetch(self) -> LedgerFetchResult:
        etag, cached = self.cache.get(LEDGER_API_PATH)
        args = [LEDGER_API_PATH]
        if etag:
            args.extend(["-H", f"If-None-Match: {etag}"])

        try:
            resp: GhResponse = self.runner(args)
        except Exception as exc:  # noqa: BLE001
            return LedgerFetchResult(
                text=None,
                meta_ledger="error",
                errors=[f"gh raised {type(exc).__name__}"],
            )

        if resp.status == 304:
            if isinstance(cached, str):
                return LedgerFetchResult(
                    text=cached,
                    meta_ledger="ok",
                    etag=etag,
                    status=304,
                    from_cache=True,
                )
            return LedgerFetchResult(
                text=None,
                meta_ledger="error",
                status=304,
                from_cache=True,
                errors=["304 but no cached ledger body"],
            )

        if resp.status == 404:
            return LedgerFetchResult(
                text=None,
                meta_ledger="not_found",
                status=404,
                errors=["ledger not found at data/ledger"],
            )

        if resp.status != 200:
            return LedgerFetchResult(
                text=None,
                meta_ledger="error",
                status=resp.status,
                errors=[f"contents API status {resp.status}"],
            )

        try:
            data = json.loads(resp.body)
            if not isinstance(data, dict):
                raise ValueError("contents payload is not an object")
            _assert_allowlisted_contents(data)
            text = _decode_contents_payload(data)
        except Exception as exc:  # noqa: BLE001
            return LedgerFetchResult(
                text=None,
                meta_ledger="error",
                status=resp.status,
                errors=[f"decode failed: {type(exc).__name__}"],
            )

        new_etag = resp.headers.get("etag") or etag
        self.cache.put(LEDGER_API_PATH, new_etag, text)
        return LedgerFetchResult(
            text=text,
            meta_ledger="ok",
            etag=new_etag,
            status=200,
            from_cache=False,
        )


def fetch_ledger_from_gh(
    *,
    cache_dir: Path | None = None,
    runner: GhRunner | None = None,
) -> LedgerFetchResult:
    return LedgerFetcher(cache_dir=cache_dir, runner=runner).fetch()
