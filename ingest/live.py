"""
MM-011: Live daemon + localhost HTTP server (one stdlib process).

Polls ledger + GitHub on a schedule, rebuilds activity.json when inputs change,
and serves web/dist plus /activity.json on 127.0.0.1 only.
"""

from __future__ import annotations

import argparse
import errno
import fcntl
import hashlib
import json
import os
import select
import signal
import socket
import sys
import threading
import time
from typing import TextIO
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Iterable, Literal
from urllib.parse import unquote, urlparse

from .attribute import load_bots
from .build import (
    DEFAULT_BOTS,
    build_nodes,
    merge_events,
    resolve_ledger_path,
    write_activity,
)
from .edges import derive_edges
from .github_poller import GhRunner, GitHubPollResult, poll_github
from .events_fetch import EVENTS_REF, EVENTS_SOURCE_URL, EventsFetcher
from .ledger_fetch import LEDGER_SOURCE_URL, fetch_ledger_from_gh
from .ledger_parser import (
    LedgerParseResult,
    ledger_last_entry_at,
    parse_ledger,
    parse_ledger_file,
)
from .membership import membership_index
from .migrate import migrate_activity

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATIC = ROOT / "web" / "dist"
DEFAULT_ACTIVITY = DEFAULT_STATIC / "activity.json"
DEFAULT_CACHE = ROOT / "ingest" / ".cache"
BIND_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
DEFAULT_LEDGER_POLL_SEC = 30.0
DEFAULT_GH_POLL_SEC = 60.0
DEFAULT_EVENTS_POLL_SEC = 30.0
DEFAULT_SSE_HEARTBEAT_SEC = 15.0
MAX_SSE_CONNECTIONS = 8
SSE_RETRY_AFTER_SEC = 5
PROCESS_LOCK_MODE = 0o600
PROCESS_LOCK_BASENAME = ".mindmap-live.lock"
MIN_PYTHON_VERSION = (3, 12)
LedgerSource = Literal["path", "gh"]
EventsSource = Literal["gh", "off"]

Clock = Callable[[], float]
Sleeper = Callable[[float], None]


def ensure_python_version(
    version_info: tuple[int, ...] | None = None,
    *,
    stderr: TextIO | None = None,
) -> int:
    """
    Require Python 3.12+ (matches pyproject.toml). Return 0 if ok, else 1.

    Used at startup so launchd / system python3.9 fails fast with a clear log line.
    """
    if version_info is not None:
        major, minor = int(version_info[0]), int(version_info[1])
    else:
        major, minor = sys.version_info.major, sys.version_info.minor
    if (major, minor) < MIN_PYTHON_VERSION:
        out = stderr if stderr is not None else sys.stderr
        need = f"{MIN_PYTHON_VERSION[0]}.{MIN_PYTHON_VERSION[1]}"
        got = f"{major}.{minor}"
        print(
            f"mindmap live requires Python {need}+ (interpreter reports {got}); "
            "use REPLACE_WITH_AGENT_MINDMAP_REPO_ROOT/.venv/bin/python "
            "(pip install -e '.[dev]' in the repo venv)",
            file=out,
        )
        return 1
    return 0


class SingletonLockError(OSError):
    """Another live daemon holds the process lock."""


def process_lock_path(activity_path: Path) -> Path:
    """QA-MM011-2: lock file adjacent to activity.json output."""
    return activity_path.parent / PROCESS_LOCK_BASENAME


class ProcessSingletonLock:
    """
    QA-MM011-2: exclusive non-blocking flock on a lock file (O_NOFOLLOW, 0o600).

    Held for the process lifetime; released when the fd is closed.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._fd: int | None = None

    def acquire(self) -> None:
        if self.path.is_symlink():
            raise SingletonLockError(
                errno.ELOOP,
                f"refusing symlink lock path: {self.path}",
            )
        flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW
        try:
            fd = os.open(self.path, flags, PROCESS_LOCK_MODE)
        except OSError as exc:
            if exc.errno in (errno.ELOOP, errno.EMLINK):
                raise SingletonLockError(
                    errno.ELOOP,
                    f"refusing symlink lock path: {self.path}",
                ) from exc
            raise
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(fd)
            raise SingletonLockError(
                errno.EAGAIN,
                f"another mindmap live instance holds {self.path}",
            ) from exc
        self._fd = fd

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)
            self._fd = None

    def __enter__(self) -> ProcessSingletonLock:
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


class SseConnectionLimiter:
    """SEC-MM020d-1: cap concurrent open /events SSE streams."""

    def __init__(self, max_connections: int = MAX_SSE_CONNECTIONS) -> None:
        self._max = max_connections
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._active = 0

    def try_acquire(self) -> bool:
        with self._lock:
            if self._active >= self._max:
                return False
            self._active += 1
            return True

    def release(self) -> None:
        with self._lock:
            self._active = max(0, self._active - 1)
            self._cond.notify_all()

    def active_count(self) -> int:
        with self._lock:
            return self._active

    def wait_until_active_at_most(
        self, limit: int, *, timeout: float = 2.0
    ) -> bool:
        """Block until ``active_count <= limit`` (for tests; no time.sleep polling)."""
        with self._cond:
            deadline = time.monotonic() + timeout
            while self._active > limit:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._cond.wait(timeout=remaining)
            return True


def refuse_public_bind(host: str) -> None:
    """AC1: never bind all interfaces; localhost only."""
    normalized = host.strip().lower()
    if normalized in {"0.0.0.0", "::", "::0", ""}:
        raise ValueError(f"refusing to bind host {host!r} (127.0.0.1 only)")
    if normalized not in {"127.0.0.1", "localhost"}:
        raise ValueError(f"only 127.0.0.1 is supported (got {host!r})")


def _host_from_header(value: str | None) -> str | None:
    if not value:
        return None
    host = value.strip()
    if host.startswith("["):
        return None
    return host.split(":", 1)[0].lower()


def host_header_allowed(value: str | None) -> bool:
    """SEC-MM011-1: Host must be 127.0.0.1 or localhost (port optional)."""
    parsed = _host_from_header(value)
    return parsed in {"127.0.0.1", "localhost"}


def origin_header_allowed(value: str | None) -> bool:
    """SEC-MM011-1: missing Origin ok; literal ``null`` and foreign origins → deny."""
    if value is None:
        return True
    raw = value.strip()
    if not raw:
        return True
    if raw.lower() == "null":
        return False
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        return False
    hostname = (parsed.hostname or "").lower()
    return hostname in {"127.0.0.1", "localhost"}


def localhost_request_allowed(headers: Any) -> bool:
    """SEC-MM011-1 gate for every HTTP route (incl. SSE)."""
    if not host_header_allowed(headers.get("Host")):
        return False
    return origin_header_allowed(headers.get("Origin"))


class NetworkEventLog:
    """In-memory NetworkEvent stream with dedupe by ``id`` (insertion order)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: list[dict[str, Any]] = []
        self._ids: set[str] = set()

    def append_many(self, events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        added: list[dict[str, Any]] = []
        with self._lock:
            for evt in events:
                eid = evt.get("id")
                if not isinstance(eid, str) or not eid or eid in self._ids:
                    continue
                self._ids.add(eid)
                self._events.append(dict(evt))
                added.append(self._events[-1])
        return added

    def events_after(self, last_id: str | None) -> list[dict[str, Any]]:
        with self._lock:
            if not last_id:
                return list(self._events)
            for idx, evt in enumerate(self._events):
                if evt.get("id") == last_id:
                    return list(self._events[idx + 1 :])
            return list(self._events)

    def count(self) -> int:
        with self._lock:
            return len(self._events)


@dataclass
class HealthState:
    last_ledger_poll: str | None = None
    last_gh_poll: str | None = None
    last_events_poll: str | None = None
    last_build: str | None = None
    ledger_last_entry_at: str | None = None
    network_event_count: int = 0
    errors: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "last_ledger_poll": self.last_ledger_poll,
            "last_gh_poll": self.last_gh_poll,
            "last_events_poll": self.last_events_poll,
            "last_build": self.last_build,
            "ledger_last_entry_at": self.ledger_last_entry_at,
            "network_event_count": self.network_event_count,
            "errors": list(self.errors),
        }


def _iso_now(clock: Clock) -> str:
    return datetime.fromtimestamp(clock(), tz=timezone.utc).isoformat()


def _fingerprint_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fingerprint_github(gh: GitHubPollResult) -> str:
    payload = {
        "meta": gh.meta_github,
        "events": [e.get("id") for e in gh.events],
        "errors": gh.errors,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def assemble_activity(
    *,
    ledger: LedgerParseResult,
    gh: GitHubPollResult,
    bots: list[dict[str, Any]],
    generated_at: str,
    meta_ledger: str = "ok",
) -> dict[str, Any]:
    """Same shape as build.build_activity without re-fetching sources."""
    events = merge_events(ledger, gh)
    edges = derive_edges(events)
    nodes = build_nodes(
        bots, ledger.tasks, events, membership=membership_index()
    )
    activity = {
        "schema_version": "1.1.0",
        "generated_at": generated_at,
        "project": "fencepost",
        "meta": {
            "github": gh.meta_github,
            "ledger": meta_ledger,
            "ledger_last_entry_at": ledger_last_entry_at(ledger),
        },
        "nodes": nodes,
        "tasks": ledger.tasks,
        "events": events,
        "edges": edges,
        "unparsed": ledger.unparsed,
    }
    return migrate_activity(activity)


@dataclass
class LiveDaemon:
    activity_path: Path
    static_dir: Path
    cache_dir: Path
    bots: list[dict[str, Any]]
    ledger_source: LedgerSource = "path"
    ledger_path: Path | None = None
    ledger_source_url: str = "build/task-ledger.md"
    ledger_poll_sec: float = DEFAULT_LEDGER_POLL_SEC
    gh_poll_sec: float = DEFAULT_GH_POLL_SEC
    events_source: EventsSource = "gh"
    events_poll_sec: float = DEFAULT_EVENTS_POLL_SEC
    github_runner: GhRunner | None = None
    clock: Clock = time.time
    sleeper: Sleeper = time.sleep

    _lock: threading.RLock = field(default_factory=threading.RLock, init=False)
    _health: HealthState = field(default_factory=HealthState, init=False)
    _stop: threading.Event = field(default_factory=threading.Event, init=False)
    _activity_etag: str | None = field(default=None, init=False)
    _activity_bytes: bytes | None = field(default=None, init=False)
    _activity_fp: str | None = field(default=None, init=False)
    _last_build_inputs_fp: str | None = field(default=None, init=False)

    _ledger_fp: str | None = field(default=None, init=False)
    _ledger: LedgerParseResult | None = field(default=None, init=False)
    _meta_ledger: str = field(default="ok", init=False)
    _gh_fp: str | None = field(default=None, init=False)
    _gh: GitHubPollResult | None = field(default=None, init=False)
    _last_good_gh: GitHubPollResult | None = field(default=None, init=False)
    _gh_backoff_until: float = field(default=0.0, init=False)
    _poll_thread: threading.Thread | None = field(default=None, init=False)
    _rate_limit_reset: int | None = field(default=None, init=False)
    _event_log: NetworkEventLog = field(default_factory=NetworkEventLog, init=False)
    sse_limiter: SseConnectionLimiter = field(
        default_factory=SseConnectionLimiter, init=False
    )

    def health(self) -> HealthState:
        with self._lock:
            return HealthState(
                last_ledger_poll=self._health.last_ledger_poll,
                last_gh_poll=self._health.last_gh_poll,
                last_events_poll=self._health.last_events_poll,
                last_build=self._health.last_build,
                ledger_last_entry_at=self._health.ledger_last_entry_at,
                network_event_count=self._event_log.count(),
                errors=list(self._health.errors),
            )

    def activity_etag(self) -> str | None:
        with self._lock:
            return self._activity_etag

    def activity_body(self) -> bytes | None:
        with self._lock:
            return self._activity_bytes

    def _append_error(self, msg: str) -> None:
        with self._lock:
            self._health.errors.append(msg)

    def _clear_errors(self) -> None:
        with self._lock:
            self._health.errors.clear()

    def _load_activity_from_disk(self) -> None:
        if not self.activity_path.is_file():
            return
        body = self.activity_path.read_bytes()
        etag = _etag_for_body(body)
        with self._lock:
            self._activity_bytes = body
            self._activity_etag = etag
            self._activity_fp = hashlib.sha256(body).hexdigest()

    def _gh_runner(self) -> GhRunner:
        base = self.github_runner

        def wrapped(args: list[str], **kwargs: Any) -> Any:
            from .github_poller import default_gh_runner

            runner = base or default_gh_runner
            resp = runner(args, **kwargs)
            reset_hdr = resp.headers.get("x-ratelimit-reset")
            if reset_hdr and reset_hdr.isdigit():
                self._rate_limit_reset = int(reset_hdr)
            if resp.status in (403, 429):
                remaining = resp.headers.get("x-ratelimit-remaining")
                body_l = (resp.body or "").lower()
                if remaining == "0" or "rate limit" in body_l:
                    if self._rate_limit_reset:
                        self._gh_backoff_until = float(self._rate_limit_reset)
            return resp

        return wrapped

    def _poll_ledger_from_path(self, now: str) -> bool:
        path = self.ledger_path
        if path is None or not path.is_file():
            self._append_error(f"ledger not found: {path}")
            with self._lock:
                self._health.last_ledger_poll = now
            return False
        try:
            fp = hashlib.sha256(path.read_bytes()).hexdigest()
            parsed = parse_ledger_file(
                path,
                source_url=self.ledger_source_url,
                bots=self.bots,
            )
        except OSError as exc:
            self._append_error(f"ledger read failed: {type(exc).__name__}")
            with self._lock:
                self._health.last_ledger_poll = now
            return False

        changed = fp != self._ledger_fp
        with self._lock:
            self._health.last_ledger_poll = now
            self._health.ledger_last_entry_at = ledger_last_entry_at(parsed)
            self._meta_ledger = "ok"
            if changed:
                self._ledger_fp = fp
                self._ledger = parsed
        return changed

    def _poll_ledger_from_gh(self, now: str) -> bool:
        fetched = fetch_ledger_from_gh(
            cache_dir=self.cache_dir / "ledger",
            runner=self._gh_runner(),
        )
        with self._lock:
            self._health.last_ledger_poll = now

        if fetched.meta_ledger != "ok" or fetched.text is None:
            for err in fetched.errors:
                self._append_error(err)
            if fetched.meta_ledger == "error":
                self._append_error("ledger fetch failed")
            return False

        fp = _fingerprint_text(fetched.text)
        if fetched.etag:
            fp = f"{fp}:{fetched.etag}"

        try:
            parsed = parse_ledger(
                fetched.text,
                source_url=LEDGER_SOURCE_URL,
                bots=self.bots,
            )
        except Exception as exc:  # noqa: BLE001
            self._append_error(f"ledger parse failed: {type(exc).__name__}")
            return False

        changed = fp != self._ledger_fp
        with self._lock:
            self._health.ledger_last_entry_at = ledger_last_entry_at(parsed)
            self._meta_ledger = fetched.meta_ledger
            if changed:
                self._ledger_fp = fp
                self._ledger = parsed
        return changed

    def poll_ledger_once(self) -> bool:
        """Read ledger; return True if fingerprint changed."""
        now = _iso_now(self.clock)
        if self.ledger_source == "gh":
            return self._poll_ledger_from_gh(now)
        return self._poll_ledger_from_path(now)

    def poll_github_once(self) -> bool:
        """Poll GitHub; return True if merged snapshot fingerprint changed."""
        now = _iso_now(self.clock)
        with self._lock:
            self._health.last_gh_poll = now

        if self.clock() < self._gh_backoff_until:
            self._append_error("github poll skipped (rate-limit backoff)")
            return False

        try:
            gh = poll_github(
                cache_dir=self.cache_dir,
                bots=self.bots,
                runner=self._gh_runner(),
            )
        except Exception as exc:  # noqa: BLE001
            self._append_error(f"github poll failed: {type(exc).__name__}")
            return False

        if gh.meta_github == "rate_limited" and self._rate_limit_reset:
            self._gh_backoff_until = float(self._rate_limit_reset)

        if gh.meta_github in {"error", "rate_limited"}:
            for err in gh.errors:
                self._append_error(err)
            return False

        fp = _fingerprint_github(gh)
        changed = fp != self._gh_fp
        with self._lock:
            if changed:
                self._gh_fp = fp
                self._gh = gh
                self._last_good_gh = gh
        return changed

    def ingest_network_events(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Append validated-shaped events (dedupe by id). For tests and poll ingest."""
        return self._event_log.append_many(events)

    def network_events_after(self, last_id: str | None) -> list[dict[str, Any]]:
        return self._event_log.events_after(last_id)

    def poll_events_once(self) -> bool:
        """Fetch data/events via gh; return True if new event ids were ingested."""
        now = _iso_now(self.clock)
        with self._lock:
            self._health.last_events_poll = now

        if self.events_source == "off":
            return False

        result = EventsFetcher(
            cache_dir=self.cache_dir / "events",
            runner=self._gh_runner(),
        ).fetch()

        if result.meta_events == "error":
            for err in result.errors:
                self._append_error(err)
            return False

        added = self._event_log.append_many(result.events)
        return bool(added)

    def maybe_rebuild(self, *, force: bool = False) -> bool:
        return _maybe_rebuild(self, force=force)

    def run_poll_cycle(self) -> None:
        ledger_changed = self.poll_ledger_once()
        gh_changed = self.poll_github_once()
        self.poll_events_once()
        if ledger_changed or gh_changed or self._activity_bytes is None:
            self.maybe_rebuild()

    def start_polling(self) -> None:
        if self._poll_thread and self._poll_thread.is_alive():
            return

        def loop() -> None:
            next_ledger = self.clock()
            next_gh = self.clock()
            next_events = self.clock()
            while not self._stop.is_set():
                now = self.clock()
                if now >= next_ledger:
                    changed = self.poll_ledger_once()
                    next_ledger = now + self.ledger_poll_sec
                    if changed:
                        self.maybe_rebuild()
                if now >= next_gh:
                    changed = self.poll_github_once()
                    next_gh = now + self.gh_poll_sec
                    if changed:
                        self.maybe_rebuild()
                if now >= next_events:
                    self.poll_events_once()
                    next_events = now + self.events_poll_sec
                if self._activity_bytes is None and self._ledger is not None:
                    self.maybe_rebuild()
                wait = min(
                    max(0.0, next_ledger - self.clock()),
                    max(0.0, next_gh - self.clock()),
                    max(0.0, next_events - self.clock()),
                    1.0,
                )
                if self._stop.wait(timeout=wait):
                    break

        self._poll_thread = threading.Thread(target=loop, name="mindmap-poll", daemon=True)
        self._poll_thread.start()

    def stop_polling(self) -> None:
        self._stop.set()
        if self._poll_thread:
            self._poll_thread.join(timeout=5.0)


def _maybe_rebuild(daemon: LiveDaemon, *, force: bool = False) -> bool:
    """
    Write activity.json when inputs changed (or force).

    On failure, keep the last on-disk file and record errors.
    Returns True if a new file was written.
    """
    ledger = daemon._ledger
    gh = daemon._gh if daemon._gh is not None else daemon._last_good_gh
    meta_ledger = daemon._meta_ledger
    inputs_fp = (
        None
        if daemon._ledger_fp is None
        else f"{daemon._ledger_fp}:{daemon._gh_fp or 'none'}"
    )

    if ledger is None:
        return False

    if not force and inputs_fp is not None and inputs_fp == daemon._last_build_inputs_fp:
        if daemon.activity_path.is_file():
            return False

    if gh is None:
        gh = GitHubPollResult(events=[], meta_github="skipped")

    try:
        activity = assemble_activity(
            ledger=ledger,
            gh=gh,
            bots=daemon.bots,
            generated_at=_iso_now(daemon.clock),
            meta_ledger=meta_ledger,
        )
        if daemon.events_source != "off":
            activity["meta"]["events_source"] = EVENTS_SOURCE_URL
        write_activity(activity, daemon.activity_path)
    except Exception as exc:  # noqa: BLE001
        daemon._append_error(f"build failed: {type(exc).__name__}")
        return False

    body = daemon.activity_path.read_bytes()
    etag = _etag_for_body(body)
    with daemon._lock:
        daemon._activity_bytes = body
        daemon._activity_etag = etag
        daemon._activity_fp = hashlib.sha256(body).hexdigest()
        daemon._last_build_inputs_fp = inputs_fp
        daemon._health.last_build = _iso_now(daemon.clock)
        daemon._clear_errors()
    return True


def _etag_for_body(body: bytes) -> str:
    digest = hashlib.sha256(body).hexdigest()
    return f'"{digest}"'


def _safe_static_path(static_root: Path, url_path: str) -> Path | None:
    if not url_path or url_path == "/":
        url_path = "/index.html"
    raw = url_path.split("?", 1)[0]
    if "%" in raw or ".." in raw:
        return None
    decoded = unquote(raw)
    if ".." in decoded:
        return None
    decoded = decoded.lstrip("/")
    if not decoded or "\x00" in decoded:
        return None
    candidate = (static_root / decoded).resolve()
    root = static_root.resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


class MindmapHandler(BaseHTTPRequestHandler):
    daemon: LiveDaemon
    static_dir: Path
    sse_heartbeat_sec: float = DEFAULT_SSE_HEARTBEAT_SEC

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), format % args))

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_bytes(
        self,
        status: int,
        body: bytes,
        *,
        content_type: str,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        self._handle_get_head()

    def do_HEAD(self) -> None:  # noqa: N802
        self._handle_get_head()

    def _reject_unless_localhost(self) -> bool:
        if localhost_request_allowed(self.headers):
            return False
        self.send_error(HTTPStatus.FORBIDDEN)
        return True

    def _write_sse_frame(self, *, event_id: str | None, data: str | None, comment: str | None) -> None:
        if event_id is not None:
            self.wfile.write(f"id: {event_id}\n".encode("utf-8"))
        if data is not None:
            for line in data.splitlines() or [""]:
                self.wfile.write(f"data: {line}\n".encode("utf-8"))
            self.wfile.write(b"\n")
        if comment is not None:
            self.wfile.write(f": {comment}\n\n".encode("utf-8"))
        self.wfile.flush()

    def _peer_closed(self) -> bool:
        """True when the client half-closed the TCP connection (EOF on read)."""
        conn = self.connection
        if conn is None:
            return True
        try:
            readable, _, _ = select.select([conn], [], [], 0)
            if not readable:
                return False
            peek = conn.recv(1, socket.MSG_PEEK)
            return peek == b""
        except BlockingIOError:
            return False
        except OSError as exc:
            if exc.errno in (
                errno.EBADF,
                errno.ENOTCONN,
                errno.ECONNRESET,
                errno.EPIPE,
                errno.ESHUTDOWN,
            ):
                return True
            return False

    def _push_sse_events(
        self,
        *,
        last_id: str | None,
        sent: set[str],
    ) -> str | None:
        for evt in self.daemon.network_events_after(last_id):
            eid = str(evt.get("id") or "")
            if not eid or eid in sent:
                continue
            payload = json.dumps(evt, separators=(",", ":"), ensure_ascii=False)
            self._write_sse_frame(event_id=eid, data=payload, comment=None)
            sent.add(eid)
            last_id = eid
        return last_id

    def _handle_sse(self) -> None:
        if self.command == "HEAD":
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            return

        if not self.daemon.sse_limiter.try_acquire():
            self.send_response(HTTPStatus.SERVICE_UNAVAILABLE)
            self.send_header("Retry-After", str(SSE_RETRY_AFTER_SEC))
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(b"SSE connection limit reached\n")
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        try:
            last_id = self.headers.get("Last-Event-ID")
            if last_id is not None:
                last_id = last_id.strip() or None

            sent: set[str] = set()
            last_id = self._push_sse_events(last_id=last_id, sent=sent)

            heartbeat = max(0.05, float(self.sse_heartbeat_sec))
            conn = self.connection
            while conn is not None:
                if self._peer_closed():
                    break
                try:
                    last_id = self._push_sse_events(last_id=last_id, sent=sent)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    break

                readable, _, _ = select.select([conn], [], [], heartbeat)
                if readable:
                    if self._peer_closed():
                        break
                    continue

                try:
                    self._write_sse_frame(event_id=None, data=None, comment="heartbeat")
                except (BrokenPipeError, ConnectionResetError, OSError):
                    break
        finally:
            self.daemon.sse_limiter.release()

    def _handle_get_head(self) -> None:
        if self._reject_unless_localhost():
            return

        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/events":
            self._handle_sse()
            return

        if path == "/healthz":
            self._send_json(HTTPStatus.OK, self.daemon.health().to_json())
            return

        if path == "/activity.json":
            etag = self.daemon.activity_etag()
            body = self.daemon.activity_body()
            if body is None and self.daemon.activity_path.is_file():
                body = self.daemon.activity_path.read_bytes()
                etag = _etag_for_body(body)
            if body is None:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            client_etag = self.headers.get("If-None-Match")
            headers = {
                "ETag": etag or _etag_for_body(body),
                "Cache-Control": "no-cache",
            }
            if client_etag and etag and client_etag.strip() == etag:
                self.send_response(HTTPStatus.NOT_MODIFIED)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.end_headers()
                return
            self._send_bytes(
                HTTPStatus.OK,
                body,
                content_type="application/json; charset=utf-8",
                extra_headers=headers,
            )
            return

        if path != "/" and ".." in path:
            self.send_error(HTTPStatus.BAD_REQUEST)
            return

        file_path = _safe_static_path(self.static_dir, path)
        if file_path is None or not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        data = file_path.read_bytes()
        content_type = "application/octet-stream"
        if file_path.suffix == ".html":
            content_type = "text/html; charset=utf-8"
        elif file_path.suffix == ".js":
            content_type = "text/javascript; charset=utf-8"
        elif file_path.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif file_path.suffix == ".json":
            content_type = "application/json; charset=utf-8"
        self._send_bytes(HTTPStatus.OK, data, content_type=content_type)

    def do_POST(self) -> None:  # noqa: N802
        self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)

    def do_PUT(self) -> None:  # noqa: N802
        self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)

    def do_DELETE(self) -> None:  # noqa: N802
        self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)


def make_handler_class(
    daemon: LiveDaemon,
    static_dir: Path,
    *,
    sse_heartbeat_sec: float = DEFAULT_SSE_HEARTBEAT_SEC,
) -> type[MindmapHandler]:
    class Handler(MindmapHandler):
        pass

    Handler.daemon = daemon
    Handler.static_dir = static_dir
    Handler.sse_heartbeat_sec = sse_heartbeat_sec
    return Handler


def create_http_server(
    daemon: LiveDaemon,
    *,
    host: str = BIND_HOST,
    port: int = DEFAULT_PORT,
    static_dir: Path | None = None,
    sse_heartbeat_sec: float = DEFAULT_SSE_HEARTBEAT_SEC,
) -> ThreadingHTTPServer:
    refuse_public_bind(host)
    static = static_dir or daemon.static_dir
    handler = make_handler_class(daemon, static, sse_heartbeat_sec=sse_heartbeat_sec)
    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.daemon_threads = True
    return httpd


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def resolve_live_ledger(
    *,
    ledger_source: LedgerSource,
    ledger_path: Path | None,
    env: dict[str, str] | None = None,
) -> tuple[LedgerSource, Path | None, str]:
    """Return (source, path or None, source_url for parser)."""
    if ledger_source == "gh":
        return "gh", None, LEDGER_SOURCE_URL
    resolved = resolve_ledger_path(ledger_path, env)
    if resolved is None:
        raise ValueError(
            "provide --ledger PATH or set MINDMAP_LEDGER (or use --ledger-source gh)"
        )
    return "path", resolved, "build/task-ledger.md"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MINDMAP live daemon + localhost server")
    parser.add_argument("--ledger", type=Path, default=None, help="Path to task-ledger.md")
    parser.add_argument(
        "--ledger-source",
        choices=("path", "gh"),
        default="path",
        help="path (default) or gh (data/ledger mirror via gh api)",
    )
    parser.add_argument("--activity-out", type=Path, default=DEFAULT_ACTIVITY)
    parser.add_argument("--static-dir", type=Path, default=DEFAULT_STATIC)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--bots", type=Path, default=DEFAULT_BOTS)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--ledger-poll-sec",
        type=float,
        default=None,
        help=f"Ledger poll interval (default {DEFAULT_LEDGER_POLL_SEC}, env MINDMAP_LEDGER_POLL_SEC)",
    )
    parser.add_argument(
        "--gh-poll-sec",
        type=float,
        default=None,
        help=f"GitHub poll interval (default {DEFAULT_GH_POLL_SEC}, env MINDMAP_GH_POLL_SEC)",
    )
    parser.add_argument(
        "--events-source",
        choices=("gh", "off"),
        default="gh",
        help="gh (data/events via gh api) or off",
    )
    parser.add_argument(
        "--events-poll-sec",
        type=float,
        default=None,
        help=(
            f"Events poll interval (default {DEFAULT_EVENTS_POLL_SEC}, "
            "env MINDMAP_EVENTS_POLL_SEC)"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    if ensure_python_version() != 0:
        return 1

    parser = build_arg_parser()
    args = parser.parse_args(argv)

    ledger_poll = args.ledger_poll_sec
    if ledger_poll is None:
        ledger_poll = _env_float("MINDMAP_LEDGER_POLL_SEC", DEFAULT_LEDGER_POLL_SEC)
    gh_poll = args.gh_poll_sec
    if gh_poll is None:
        gh_poll = _env_float("MINDMAP_GH_POLL_SEC", DEFAULT_GH_POLL_SEC)
    events_poll = args.events_poll_sec
    if events_poll is None:
        events_poll = _env_float("MINDMAP_EVENTS_POLL_SEC", DEFAULT_EVENTS_POLL_SEC)

    try:
        source, ledger_path, ledger_url = resolve_live_ledger(
            ledger_source=args.ledger_source,
            ledger_path=args.ledger,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if source == "path" and (ledger_path is None or not ledger_path.is_file()):
        print(f"ledger not found: {ledger_path}", file=sys.stderr)
        return 1

    with args.bots.open(encoding="utf-8") as f:
        bots = json.load(f)["bots"]

    lock_path = process_lock_path(args.activity_out)
    try:
        process_lock = ProcessSingletonLock(lock_path)
        process_lock.acquire()
    except SingletonLockError:
        print(
            f"error: another mindmap live instance is already running (lock: {lock_path})",
            file=sys.stderr,
        )
        return 1

    daemon = LiveDaemon(
        ledger_source=source,
        ledger_path=ledger_path,
        ledger_source_url=ledger_url,
        activity_path=args.activity_out,
        static_dir=args.static_dir,
        cache_dir=args.cache_dir,
        bots=bots,
        ledger_poll_sec=ledger_poll,
        gh_poll_sec=gh_poll,
        events_source=args.events_source,
        events_poll_sec=events_poll,
    )
    daemon._load_activity_from_disk()
    daemon.run_poll_cycle()
    daemon.start_polling()

    try:
        httpd = create_http_server(daemon, port=args.port)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    def shutdown(signum: int, _frame: Any) -> None:
        daemon.stop_polling()
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    host, port = httpd.server_address
    ledger_desc = ledger_path if ledger_path else "gh:data/ledger"
    events_desc = "gh:data/events" if args.events_source == "gh" else "off"
    print(
        f"mindmap live on http://{host}:{port} "
        f"(ledger={ledger_desc}, events={events_desc})",
        file=sys.stderr,
    )
    try:
        httpd.serve_forever(poll_interval=0.5)
    finally:
        daemon.stop_polling()
        httpd.server_close()
        process_lock.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
