"""
GitHub poller via `gh api` (read-only). No tokens in process, logs, or output.

Caches ETags + bodies under ingest/.cache/ so a re-run sends If-None-Match
and receives 304s. Allowed repos: ManpreetS2/fencepost, ManpreetS2/agent-mindmap.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .attribute import (
    attribute_from_body,
    extract_task_id,
    extract_verdict,
    load_bots,
)

ALLOWED_REPOS = frozenset(
    {
        "ManpreetS2/fencepost",
        "ManpreetS2/agent-mindmap",
    }
)
DEFAULT_REPOS = ("ManpreetS2/fencepost", "ManpreetS2/agent-mindmap")
RATE_LIMIT_FLOOR = 50
MAX_PRS = 50


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def event_id(source: str, locator: str) -> str:
    return hashlib.sha1(f"{source}{locator}".encode("utf-8")).hexdigest()


@dataclass
class GhResponse:
    status: int
    headers: dict[str, str]
    body: str
    from_cache: bool = False


@dataclass
class GitHubPollResult:
    events: list[dict[str, Any]] = field(default_factory=list)
    meta_github: str = "ok"  # ok | error | skipped
    status_304_count: int = 0
    request_count: int = 0
    errors: list[str] = field(default_factory=list)


class ETagCache:
    """Persist ETags and response bodies under ingest/.cache/."""

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        self.bodies_dir = cache_dir / "bodies"
        self.index_path = cache_dir / "etags.json"
        self._index: dict[str, Any] = {"entries": {}}
        if self.index_path.exists():
            with self.index_path.open(encoding="utf-8") as f:
                self._index = json.load(f)

    def get(self, key: str) -> tuple[str | None, Any | None]:
        entry = self._index.get("entries", {}).get(key)
        if not entry:
            return None, None
        etag = entry.get("etag")
        body_path = self.bodies_dir / entry["body_file"]
        if not body_path.exists():
            return etag, None
        with body_path.open(encoding="utf-8") as f:
            return etag, json.load(f)

    def put(self, key: str, etag: str | None, body: Any) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.bodies_dir.mkdir(parents=True, exist_ok=True)
        safe = hashlib.sha1(key.encode("utf-8")).hexdigest()
        body_file = f"{safe}.json"
        path = self.bodies_dir / body_file
        with path.open("w", encoding="utf-8") as f:
            json.dump(body, f, indent=2, sort_keys=True)
            f.write("\n")
        self._index.setdefault("entries", {})[key] = {
            "etag": etag,
            "body_file": body_file,
        }
        with self.index_path.open("w", encoding="utf-8") as f:
            json.dump(self._index, f, indent=2, sort_keys=True)
            f.write("\n")


def _parse_gh_include(raw: str) -> GhResponse:
    """Parse `gh api --include` output into status, headers, body."""
    text = raw.replace("\r\n", "\n")
    if not text.strip():
        return GhResponse(status=0, headers={}, body="")

    # May include multiple header blocks (redirects); take the last.
    parts = re.split(r"\n(?=HTTP/\d)", text)
    blocks = [p for p in parts if p.strip()]
    block = blocks[-1] if blocks else text
    if "\n\n" in block:
        header_raw, body = block.split("\n\n", 1)
    else:
        header_raw, body = block, ""

    lines = header_raw.split("\n")
    status = 0
    headers: dict[str, str] = {}
    for i, line in enumerate(lines):
        if i == 0 and line.upper().startswith("HTTP/"):
            bits = line.split()
            if len(bits) >= 2 and bits[1].isdigit():
                status = int(bits[1])
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    return GhResponse(status=status, headers=headers, body=body.strip())


def default_gh_runner(args: list[str], *, timeout: float = 60.0) -> GhResponse:
    """
    Run `gh api --include ...` via subprocess. Never passes or logs tokens.
    Relies on the existing `gh` login on the host.
    """
    cmd = ["gh", "api", "--include", *args]
    # Do not pass GITHUB_TOKEN / GH_TOKEN into the child beyond the ambient
    # environment gh already uses; we never read or print those vars.
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    # gh may put the include payload on stdout even when exit != 0 (e.g. 404).
    combined = proc.stdout or ""
    if not combined and proc.stderr:
        # Hard failure (auth/network) — surface as status 0 with stderr body
        # but never echo credentials (stderr is kept only for error classification).
        err = proc.stderr
        if _looks_like_secret(err):
            err = "[redacted]"
        return GhResponse(status=0, headers={}, body=err)
    resp = _parse_gh_include(combined)
    if resp.status == 0 and proc.returncode != 0:
        return GhResponse(status=0, headers={}, body=combined or "[gh failed]")
    return resp


def _looks_like_secret(text: str) -> bool:
    return bool(
        re.search(
            r"(ghp_|gho_|ghu_|ghs_|ghr_|github_pat_|Bearer\s+[A-Za-z0-9._\-]+|"
            r"Authorization:\s*\S+)",
            text,
            re.IGNORECASE,
        )
    )


GhRunner = Callable[..., GhResponse]


class GitHubPoller:
    def __init__(
        self,
        *,
        cache_dir: Path | None = None,
        bots: list[dict[str, Any]] | None = None,
        runner: GhRunner | None = None,
        repos: tuple[str, ...] = DEFAULT_REPOS,
    ) -> None:
        for repo in repos:
            if repo not in ALLOWED_REPOS:
                raise ValueError(f"repo not allowed: {repo}")
        self.repos = repos
        self.cache = ETagCache(cache_dir or (_repo_root() / "ingest" / ".cache"))
        self.bots = bots if bots is not None else load_bots()
        self.runner = runner or default_gh_runner
        self.status_304_count = 0
        self.request_count = 0
        self._rate_limited = False
        self._errors: list[str] = []

    def _get_json(self, api_path: str) -> Any | None:
        """GET api_path with ETag cache. Returns parsed JSON or None on failure."""
        if self._rate_limited:
            return self.cache.get(api_path)[1]

        etag, cached_body = self.cache.get(api_path)
        headers = ["Accept: application/vnd.github+json"]
        if etag:
            headers.append(f"If-None-Match: {etag}")

        args: list[str] = []
        for h in headers:
            args.extend(["-H", h])
        args.append(api_path)

        self.request_count += 1
        try:
            resp = self.runner(args)
        except (OSError, subprocess.TimeoutExpired) as exc:
            self._errors.append(f"gh spawn failed for {api_path}: {type(exc).__name__}")
            return cached_body

        remaining = resp.headers.get("x-ratelimit-remaining")
        if remaining is not None:
            try:
                if int(remaining) < RATE_LIMIT_FLOOR:
                    self._rate_limited = True
            except ValueError:
                pass

        new_etag = resp.headers.get("etag")

        if resp.status == 304:
            self.status_304_count += 1
            return cached_body

        if resp.status == 0 or resp.status >= 400:
            self._errors.append(f"gh api {api_path} -> HTTP {resp.status}")
            return cached_body

        if not resp.body:
            return cached_body

        try:
            data = json.loads(resp.body)
        except json.JSONDecodeError:
            self._errors.append(f"invalid JSON for {api_path}")
            return cached_body

        self.cache.put(api_path, new_etag or etag, data)
        return data

    def poll(self) -> GitHubPollResult:
        events: list[dict[str, Any]] = []
        seen: set[str] = set()

        try:
            for repo in self.repos:
                events.extend(self._poll_repo(repo, seen))
        except Exception as exc:  # noqa: BLE001 — surface as meta.error
            self._errors.append(f"poll crashed: {type(exc).__name__}")

        if self._errors and not events:
            meta = "error"
        elif self._errors and events:
            # Partial: still usable; treat hard transport failures as error
            meta = "error" if any("spawn failed" in e or "-> HTTP 0" in e for e in self._errors) else "ok"
        elif self._rate_limited and not events:
            meta = "error"
        else:
            meta = "ok"

        # If the very first pulls call failed with no cache, mark error.
        if self.request_count > 0 and not events and self._errors:
            meta = "error"

        return GitHubPollResult(
            events=events,
            meta_github=meta,
            status_304_count=self.status_304_count,
            request_count=self.request_count,
            errors=list(self._errors),
        )

    def _poll_repo(self, repo: str, seen: set[str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        pulls = self._get_json(f"repos/{repo}/pulls?state=all&per_page={MAX_PRS}")
        if pulls is None:
            return out
        if not isinstance(pulls, list):
            self._errors.append(f"unexpected pulls payload for {repo}")
            return out

        for pr in pulls[:MAX_PRS]:
            out.extend(self._events_for_pr(repo, pr, seen))
        return out

    def _events_for_pr(
        self,
        repo: str,
        pr: dict[str, Any],
        seen: set[str],
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        number = int(pr["number"])
        html = pr.get("html_url") or f"https://github.com/{repo}/pull/{number}"
        title = pr.get("title") or ""
        body = pr.get("body") or ""
        head_ref = (pr.get("head") or {}).get("ref") or ""
        task_id = extract_task_id(head_ref, title, body)
        created = pr.get("created_at") or pr.get("updated_at")

        # PR opened
        actor, method = attribute_from_body(body, self.bots)
        opened = _event(
            locator=f"{repo}#pr{number}:opened",
            etype="pr_opened",
            actor=actor,
            task_id=task_id,
            pr=number,
            source_url=html,
            source_time=created,
            attribution=method,
            raw=f"Opened pull request #{number}: {title}",
        )
        _append_unique(events, seen, opened)

        # Merged
        if pr.get("merged_at"):
            sha = (pr.get("merge_commit_sha") or "")[:40].lower()
            if len(sha) >= 7 and re.fullmatch(r"[0-9a-f]+", sha):
                sha_val: str | None = sha
            else:
                sha_val = None
            merged = _event(
                locator=f"{repo}#pr{number}:merged:{sha_val or ''}",
                etype="merged",
                actor=actor,
                task_id=task_id,
                pr=number,
                sha=sha_val,
                source_url=html,
                source_time=pr.get("merged_at"),
                attribution=method if actor else "unknown",
                raw=f"squash-merged as {sha_val}" if sha_val else f"Merged PR #{number}",
            )
            # Prefer merge-message attribution from commits if present later.
            _append_unique(events, seen, merged)

        # Reviews
        reviews = self._get_json(f"repos/{repo}/pulls/{number}/reviews")
        if isinstance(reviews, list):
            for rev in reviews:
                events.extend(self._review_events(repo, number, html, task_id, rev, seen))

        # Review comments (line comments)
        review_comments = self._get_json(f"repos/{repo}/pulls/{number}/comments")
        if isinstance(review_comments, list):
            for c in review_comments:
                events.extend(self._comment_events(repo, number, task_id, c, seen, kind="review_comment"))

        # Issue comments (conversation)
        issue_comments = self._get_json(f"repos/{repo}/issues/{number}/comments")
        if isinstance(issue_comments, list):
            for c in issue_comments:
                events.extend(self._comment_events(repo, number, task_id, c, seen, kind="issue_comment"))

        # Commits (optional enrichment; merge sha confirmation)
        commits = self._get_json(f"repos/{repo}/pulls/{number}/commits")
        if isinstance(commits, list) and commits:
            head_sha = (commits[-1].get("sha") or "")[:40].lower()
            if pr.get("merged_at") and head_sha:
                # check-runs on head
                self._get_json(f"repos/{repo}/commits/{head_sha}/check-runs")

        return events

    def _review_events(
        self,
        repo: str,
        number: int,
        html: str,
        task_id: str | None,
        rev: dict[str, Any],
        seen: set[str],
    ) -> list[dict[str, Any]]:
        body = rev.get("body") or ""
        actor, method = attribute_from_body(body, self.bots)
        verdict = extract_verdict(body)
        etype = "verdict" if verdict else "note"
        url = rev.get("html_url") or html
        ts = rev.get("submitted_at") or ""
        extra = {"verdict": verdict} if verdict else {}
        evt = _event(
            locator=f"{repo}#pr{number}:review:{rev.get('id')}",
            etype=etype,
            actor=actor,
            task_id=task_id,
            pr=number,
            source_url=url,
            source_time=ts,
            attribution=method,
            raw=body or f"Review on PR #{number}",
            **extra,
        )
        out: list[dict[str, Any]] = []
        _append_unique(out, seen, evt)
        return out

    def _comment_events(
        self,
        repo: str,
        number: int,
        task_id: str | None,
        comment: dict[str, Any],
        seen: set[str],
        *,
        kind: str,
    ) -> list[dict[str, Any]]:
        body = comment.get("body") or ""
        actor, method = attribute_from_body(body, self.bots)
        verdict = extract_verdict(body)
        etype = "verdict" if verdict else "note"
        url = comment.get("html_url") or f"https://github.com/{repo}/pull/{number}"
        ts = comment.get("created_at") or ""
        extra = {"verdict": verdict} if verdict else {}
        evt = _event(
            locator=f"{repo}#pr{number}:{kind}:{comment.get('id')}",
            etype=etype,
            actor=actor,
            task_id=task_id,
            pr=number,
            source_url=url,
            source_time=ts,
            attribution=method,
            raw=body or f"Comment on PR #{number}",
            **extra,
        )
        out: list[dict[str, Any]] = []
        _append_unique(out, seen, evt)
        return out


def _event(
    *,
    locator: str,
    etype: str,
    actor: str | None,
    task_id: str | None,
    pr: int | None,
    source_url: str,
    source_time: str | None,
    attribution: str,
    raw: str,
    sha: str | None = None,
    verdict: str | None = None,
    target: str | None = None,
) -> dict[str, Any]:
    evt: dict[str, Any] = {
        "id": event_id("github", locator),
        "type": etype,
        "actor": actor,
        "target": target,
        "task_id": task_id,
        "attribution": {"method": attribution},
        "source_url": source_url,
        "source_time": source_time or "1970-01-01T00:00:00Z",
        "raw": raw,
    }
    if pr is not None:
        evt["pr"] = pr
    if sha:
        evt["sha"] = sha
    if verdict:
        evt["verdict"] = verdict
    return evt


def _append_unique(
    events: list[dict[str, Any]],
    seen: set[str],
    evt: dict[str, Any],
) -> None:
    eid = evt["id"]
    if eid in seen:
        return
    seen.add(eid)
    events.append(evt)


def poll_github(
    *,
    cache_dir: Path | None = None,
    bots: list[dict[str, Any]] | None = None,
    runner: GhRunner | None = None,
    repos: tuple[str, ...] = DEFAULT_REPOS,
) -> GitHubPollResult:
    """Poll allowed repos and return events + meta.github status."""
    return GitHubPoller(
        cache_dir=cache_dir,
        bots=bots,
        runner=runner,
        repos=repos,
    ).poll()


def assert_no_credentials(payload: Any) -> None:
    """Raise AssertionError if serialized payload looks like it contains secrets."""
    blob = json.dumps(payload, default=str)
    if _looks_like_secret(blob):
        raise AssertionError("credentials-like pattern found in output")
    banned = ("GITHUB_TOKEN", "GH_TOKEN", "Authorization")
    for word in banned:
        if word in blob:
            raise AssertionError(f"forbidden key {word!r} found in output")
