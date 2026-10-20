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
from urllib.parse import urlparse

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
PER_PAGE = 100
MAX_PAGES = 20  # sub-resource page cap
MAX_PRS = 50  # architecture §8 — PR list hard cap
LINK_NEXT_RE = re.compile(r'<([^>]+)>\s*;\s*rel="next"', re.IGNORECASE)


class PaginationLinkError(ValueError):
    """Raised when a Link rel=next target fails host/repo allowlisting."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def event_id(source: str, locator: str) -> str:
    return hashlib.sha1(f"{source}{locator}".encode("utf-8")).hexdigest()


def repo_id_from_item(item: dict[str, Any]) -> int | None:
    """Best-effort numeric repository id from a PR/issue-like JSON object."""
    for key in ("repository", "base", "head"):
        node = item.get(key)
        if isinstance(node, dict):
            repo = node.get("repo") if key in {"base", "head"} else node
            if isinstance(repo, dict) and isinstance(repo.get("id"), int):
                return int(repo["id"])
            if key == "repository" and isinstance(node.get("id"), int):
                return int(node["id"])
    return None


def next_link_path(
    link_header: str | None,
    *,
    allowed_repos: frozenset[str] = ALLOWED_REPOS,
    allowed_repo_ids: frozenset[int] | set[int] | None = None,
) -> str | None:
    """
    Extract the next page path from a GitHub Link header.

    SEC-MM003-1 / QA-MM003-9: netloc must be `api.github.com`, and the path must
    start with either `repos/<allowlisted owner/repo>/` or
    `repositories/<allowlisted numeric id>/`.
    Raises PaginationLinkError on foreign host/repo (caller stops + meta=error).
    """
    if not link_header:
        return None
    m = LINK_NEXT_RE.search(link_header)
    if not m:
        return None

    parsed = urlparse(m.group(1))
    if parsed.netloc != "api.github.com":
        raise PaginationLinkError(
            f"refusing pagination link host {parsed.netloc!r} (want api.github.com)"
        )

    path = parsed.path.lstrip("/")
    parts = path.split("/")
    if not parts:
        raise PaginationLinkError(f"refusing pagination link path {path!r}")

    if parts[0] == "repos":
        if len(parts) < 3:
            raise PaginationLinkError(f"refusing pagination link path {path!r}")
        repo = f"{parts[1]}/{parts[2]}"
        if repo not in allowed_repos:
            raise PaginationLinkError(f"refusing pagination link repo {repo!r}")
        if not path.startswith(f"repos/{repo}/") and path != f"repos/{repo}":
            raise PaginationLinkError(f"refusing pagination link path {path!r}")
    elif parts[0] == "repositories":
        if len(parts) < 2 or not parts[1].isdigit():
            raise PaginationLinkError(f"refusing pagination link path {path!r}")
        rid = int(parts[1])
        if not allowed_repo_ids or rid not in allowed_repo_ids:
            raise PaginationLinkError(
                f"refusing pagination link repository id {rid!r}"
            )
        if not path.startswith(f"repositories/{rid}/") and path != f"repositories/{rid}":
            raise PaginationLinkError(f"refusing pagination link path {path!r}")
    else:
        raise PaginationLinkError(f"refusing pagination link path {path!r}")

    if parsed.query:
        return f"{path}?{parsed.query}"
    return path


@dataclass
class GhResponse:
    status: int
    headers: dict[str, str]
    body: str
    from_cache: bool = False


@dataclass
class GitHubPollResult:
    events: list[dict[str, Any]] = field(default_factory=list)
    meta_github: str = "ok"  # ok | error | skipped | rate_limited
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
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    combined = proc.stdout or ""
    if not combined and proc.stderr:
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


def _is_rate_limit_response(resp: GhResponse) -> bool:
    if resp.status == 429:
        return True
    if resp.status != 403:
        return False
    remaining = resp.headers.get("x-ratelimit-remaining")
    if remaining == "0":
        return True
    body = (resp.body or "").lower()
    return "rate limit" in body or "secondary rate limit" in body


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
        # owner/repo → numeric GitHub repository id (for Link /repositories/<id>/)
        self._repo_ids: dict[str, int] = {}

    def _request(self, api_path: str) -> tuple[GhResponse | None, Any | None]:
        """
        One cached GET. Returns (response|None, body_json|None).
        On 304, response status is 304 and body_json is the cached payload.
        """
        if self._rate_limited:
            return None, self.cache.get(api_path)[1]

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
            return None, cached_body

        remaining = resp.headers.get("x-ratelimit-remaining")
        if remaining is not None:
            try:
                if int(remaining) < RATE_LIMIT_FLOOR:
                    self._rate_limited = True
            except ValueError:
                pass

        if _is_rate_limit_response(resp):
            self._rate_limited = True
            self._errors.append(f"gh api {api_path} -> HTTP {resp.status} (rate limited)")
            return resp, cached_body

        new_etag = resp.headers.get("etag")

        if resp.status == 304:
            self.status_304_count += 1
            return resp, cached_body

        if resp.status >= 500:
            self._errors.append(f"gh api {api_path} -> HTTP {resp.status}")
            return resp, cached_body

        if resp.status == 0 or resp.status >= 400:
            self._errors.append(f"gh api {api_path} -> HTTP {resp.status}")
            return resp, cached_body

        if not resp.body:
            return resp, cached_body

        try:
            data = json.loads(resp.body)
        except json.JSONDecodeError:
            self._errors.append(f"invalid JSON for {api_path}")
            return resp, cached_body

        self.cache.put(api_path, new_etag or etag, data)
        return resp, data

    def _get_json(self, api_path: str) -> Any | None:
        _resp, data = self._request(api_path)
        return data

    def _remember_repo_id(self, repo: str, repo_id: int | None) -> None:
        if repo_id is None:
            return
        self._repo_ids[repo] = int(repo_id)

    def _resolve_repo_id(self, repo: str) -> int | None:
        """GET repos/{owner}/{repo} once; cache numeric id for Link allowlisting."""
        if repo in self._repo_ids:
            return self._repo_ids[repo]
        data = self._get_json(f"repos/{repo}")
        if isinstance(data, dict) and isinstance(data.get("id"), int):
            self._remember_repo_id(repo, int(data["id"]))
            return self._repo_ids[repo]
        return None

    def _allowed_ids_for(self, repo: str) -> frozenset[int]:
        rid = self._repo_ids.get(repo)
        return frozenset({rid}) if rid is not None else frozenset()

    def _get_json_list(
        self,
        api_path: str,
        *,
        repo: str,
        max_pages: int | None = MAX_PAGES,
        max_items: int | None = None,
    ) -> list[Any]:
        """
        Paginated list GET (per_page=100, follow Link rel=next).

        Sub-resources: max_pages=MAX_PAGES (20).
        PR lists: max_items=MAX_PRS (50); page cap optional/None.
        """
        items: list[Any] = []
        path = api_path
        if "per_page=" not in path:
            sep = "&" if "?" in path else "?"
            path = f"{path}{sep}per_page={PER_PAGE}"

        seen_paths: set[str] = set()
        page_count = 0
        while path and path not in seen_paths:
            page_count += 1
            if max_pages is not None and page_count > max_pages:
                self._errors.append(
                    f"pagination page cap ({max_pages}) exceeded for {api_path}"
                )
                break

            seen_paths.add(path)
            resp, data = self._request(path)
            if isinstance(data, list):
                if data and repo not in self._repo_ids and isinstance(data[0], dict):
                    self._remember_repo_id(repo, repo_id_from_item(data[0]))
                items.extend(data)
                if max_items is not None and len(items) >= max_items:
                    items = items[:max_items]
                    break
            elif data is not None:
                self._errors.append(f"unexpected list payload for {path}")
                break

            if self._rate_limited:
                break
            if resp is None:
                break
            if resp.status >= 500 or resp.status == 0 or (
                resp.status >= 400 and resp.status != 304
            ):
                break

            try:
                path_next = next_link_path(
                    resp.headers.get("link"),
                    allowed_repo_ids=self._allowed_ids_for(repo),
                )
            except PaginationLinkError as exc:
                self._errors.append(str(exc))
                break
            if not path_next:
                break
            path = path_next

        return items

    def _meta(self, events: list[dict[str, Any]]) -> str:
        if self._rate_limited:
            return "rate_limited"
        if self._errors:
            return "error"
        if not events and self.request_count > 0 and self._errors:
            return "error"
        return "ok"

    def poll(self) -> GitHubPollResult:
        events: list[dict[str, Any]] = []
        seen: set[str] = set()

        try:
            for repo in self.repos:
                events.extend(self._poll_repo(repo, seen))
        except Exception as exc:  # noqa: BLE001
            self._errors.append(f"poll crashed: {type(exc).__name__}")

        return GitHubPollResult(
            events=events,
            meta_github=self._meta(events),
            status_304_count=self.status_304_count,
            request_count=self.request_count,
            errors=list(self._errors),
        )

    def _poll_repo(self, repo: str, seen: set[str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        self._resolve_repo_id(repo)
        pulls = self._get_json_list(
            f"repos/{repo}/pulls?state=all",
            repo=repo,
            max_pages=None,
            max_items=MAX_PRS,
        )
        for pr in pulls:
            if not isinstance(pr, dict):
                continue
            if repo not in self._repo_ids:
                self._remember_repo_id(repo, repo_id_from_item(pr))
            out.extend(self._events_for_pr(repo, pr, seen))
            if self._rate_limited:
                break
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

        if pr.get("merged_at"):
            sha = (pr.get("merge_commit_sha") or "")[:40].lower()
            sha_val = sha if len(sha) >= 7 and re.fullmatch(r"[0-9a-f]+", sha) else None
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
            _append_unique(events, seen, merged)

        reviews = self._get_json_list(
            f"repos/{repo}/pulls/{number}/reviews", repo=repo
        )
        for rev in reviews:
            if isinstance(rev, dict):
                events.extend(self._review_events(repo, number, html, task_id, rev, seen))

        review_comments = self._get_json_list(
            f"repos/{repo}/pulls/{number}/comments", repo=repo
        )
        for c in review_comments:
            if isinstance(c, dict):
                events.extend(
                    self._comment_events(repo, number, task_id, c, seen, kind="review_comment")
                )

        issue_comments = self._get_json_list(
            f"repos/{repo}/issues/{number}/comments", repo=repo
        )
        for c in issue_comments:
            if isinstance(c, dict):
                events.extend(
                    self._comment_events(repo, number, task_id, c, seen, kind="issue_comment")
                )

        commits = self._get_json_list(
            f"repos/{repo}/pulls/{number}/commits", repo=repo
        )
        if commits:
            head_sha = (commits[-1].get("sha") or "")[:40].lower()
            if pr.get("merged_at") and head_sha:
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
