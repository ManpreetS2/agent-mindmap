"""
Fetch mirrored events.jsonl from GitHub via `gh api` (MM-020c).

Allowlisted only (defaults):
  GET repos/ManpreetS2/agent-mindmap/contents/events.jsonl?ref=data/events

Uses ETag caching (304 → keep cached body). Base64-decodes `content`.
No tokens — relies on host `gh` login. Read-only.

Missing / empty branch → empty list (no throw).
Unknown `group` values pass through (no throw).
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .github_poller import ETagCache, GhResponse, GhRunner, default_gh_runner

EVENTS_REPO = "ManpreetS2/agent-mindmap"
EVENTS_FILE = "events.jsonl"
EVENTS_REF = "data/events"
EVENTS_API_PATH = f"repos/{EVENTS_REPO}/contents/{EVENTS_FILE}?ref={EVENTS_REF}"
EVENTS_SOURCE_URL = (
    f"https://github.com/{EVENTS_REPO}/blob/{EVENTS_REF}/{EVENTS_FILE}"
)

_ALLOWED_REPOS = frozenset({EVENTS_REPO})
_ALLOWED_REFS = frozenset({EVENTS_REF})


@dataclass
class EventsFetchResult:
    events: list[dict[str, Any]] = field(default_factory=list)
    text: str | None = None
    meta_events: str = "ok"  # ok | error | skipped | missing
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
    if name not in (None, EVENTS_FILE) and path not in (None, EVENTS_FILE):
        raise ValueError(f"refusing unexpected contents path {path!r}")
    if path is not None and path != EVENTS_FILE:
        raise ValueError(f"refusing unexpected contents path {path!r}")
    if name is not None and name != EVENTS_FILE:
        raise ValueError(f"refusing unexpected contents name {name!r}")


def _api_path(repo: str, branch: str) -> str:
    return f"repos/{repo}/contents/{EVENTS_FILE}?ref={branch}"


def parse_events_jsonl(text: str) -> list[dict[str, Any]]:
    """
    Parse NetworkEvent JSONL loosely for Mac ingest.

    Invalid lines are skipped. Unknown groups pass through. Never raises on
    content shape beyond skipping bad lines.
    """
    # Prefer shared validator from events_mirror (local) or event_emit when present.
    try:
        from tools.events_mirror import validate_network_event
    except ImportError:  # pragma: no cover
        validate_network_event = None  # type: ignore[assignment]

    out: list[dict[str, Any]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        if validate_network_event is not None:
            ev = validate_network_event(obj)
            if ev is None:
                # Soft-parse fallback: required keys present → keep as-is
                # (unknown group already allowed by validator; other soft cases).
                continue
            out.append(ev)
            continue
        # Minimal passthrough if validator unavailable
        if not isinstance(obj.get("id"), str):
            continue
        out.append(obj)
    return out


class EventsFetcher:
    def __init__(
        self,
        *,
        repo: str = EVENTS_REPO,
        branch: str = EVENTS_REF,
        cache_dir: Path | None = None,
        runner: GhRunner | None = None,
    ) -> None:
        self.repo = repo
        self.branch = branch
        self.api_path = _api_path(repo, branch)
        root = Path(__file__).resolve().parents[1]
        self.cache = ETagCache(cache_dir or (root / "ingest" / ".cache" / "events"))
        self.runner: GhRunner = runner or default_gh_runner

    def _refuse_if_not_allowlisted(self) -> EventsFetchResult | None:
        if self.repo not in _ALLOWED_REPOS or self.branch not in _ALLOWED_REFS:
            return EventsFetchResult(
                events=[],
                text=None,
                meta_events="error",
                status=0,
                errors=[
                    f"refusing non-allowlisted repo/branch "
                    f"{self.repo!r}@{self.branch!r}"
                ],
            )
        return None

    def fetch(self) -> EventsFetchResult:
        refused = self._refuse_if_not_allowlisted()
        if refused is not None:
            return refused

        etag, cached = self.cache.get(self.api_path)
        args = [self.api_path]
        if etag:
            args.extend(["-H", f"If-None-Match: {etag}"])

        try:
            resp: GhResponse = self.runner(args)
        except Exception as exc:  # noqa: BLE001
            return EventsFetchResult(
                events=[],
                text=None,
                meta_events="error",
                errors=[f"gh raised {type(exc).__name__}"],
            )

        # Missing branch / file → empty list (tolerate).
        if resp.status in (404, 409):
            return EventsFetchResult(
                events=[],
                text="",
                meta_events="missing",
                status=resp.status,
                from_cache=False,
            )

        if resp.status == 304:
            if isinstance(cached, str):
                events = parse_events_jsonl(cached)
                return EventsFetchResult(
                    events=events,
                    text=cached,
                    meta_events="ok",
                    etag=etag,
                    status=304,
                    from_cache=True,
                )
            if isinstance(cached, list):
                return EventsFetchResult(
                    events=list(cached),
                    text=None,
                    meta_events="ok",
                    etag=etag,
                    status=304,
                    from_cache=True,
                )
            return EventsFetchResult(
                events=[],
                text=None,
                meta_events="error",
                status=304,
                from_cache=True,
                errors=["304 but no cached events body"],
            )

        if resp.status != 200:
            return EventsFetchResult(
                events=[],
                text=None,
                meta_events="error",
                status=resp.status,
                errors=[f"contents API status {resp.status}"],
            )

        try:
            data = json.loads(resp.body)
            if not isinstance(data, dict):
                raise ValueError("contents payload is not an object")
            _assert_allowlisted_contents(data)
            # Empty file / null content
            if not data.get("content") and data.get("size", 0) == 0:
                text = ""
            else:
                text = _decode_contents_payload(data)
            sha = data.get("sha")
        except Exception as exc:  # noqa: BLE001
            return EventsFetchResult(
                events=[],
                text=None,
                meta_events="error",
                status=resp.status,
                errors=[f"decode failed: {type(exc).__name__}: {exc}"],
            )

        events = parse_events_jsonl(text)
        new_etag = resp.headers.get("etag") or etag
        # Prefer ETag; fall back to contents sha for caching when ETag absent.
        cache_key_meta = new_etag or (f'sha:"{sha}"' if sha else None)
        self.cache.put(self.api_path, cache_key_meta, text)
        return EventsFetchResult(
            events=events,
            text=text,
            meta_events="ok",
            etag=cache_key_meta,
            status=200,
            from_cache=False,
        )


def fetch_events_from_gh(
    repo: str = EVENTS_REPO,
    branch: str = EVENTS_REF,
    *,
    cache_dir: Path | None = None,
    runner: GhRunner | None = None,
) -> list[dict[str, Any]]:
    """
    Mac-side entry point for DEV 1 live.py.

    Returns a list of NetworkEvent dicts. Missing branch → []. Never raises for
    empty/missing content. Non-allowlisted repo/branch → [].
    """
    result = EventsFetcher(
        repo=repo,
        branch=branch,
        cache_dir=cache_dir,
        runner=runner,
    ).fetch()
    return list(result.events)
