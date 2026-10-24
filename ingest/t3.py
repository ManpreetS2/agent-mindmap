"""Read-only T3 MCP projection. No messages, tool output or credentials in activity.json."""

from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import html
import json
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote_plus

READ_TOOLS = frozenset(
    {
        "t3_environment_read",
        "t3_project_list",
        "orchestrator_capabilities",
        "t3_thread_list",
        "t3_thread_read",
    }
)
STATUS = {
    "idle": "IDLE",
    "queued": "BLOCKED",
    "running": "IN_PROGRESS",
    "preparing": "IN_PROGRESS",
    "starting": "IN_PROGRESS",
    "waiting": "BLOCKED",
    "completed": "DONE",
    "failed": "FAILED",
}


REDACTED = "[redacted]"
REDACTED_PATH = "[redacted path]"

# Fail-closed credential detection. Anything suspicious replaces the WHOLE value;
# we never publish a partially scrubbed string. Titles/branches are untrusted input.
_SUSPICIOUS = re.compile(
    r"""(?ix)
      \b(?:proxy-)?authorization\s*[:=]
    | \bbearer\s+[\w+/=.~-]{3,}
    | \b(?:basic|digest|negotiate)\s+(?=[\w+/=.~-]*(?:\d|[+/=]|(?-i:[a-z][A-Z])))[\w+/=.~-]{8,}
    | \bxox[abeoprs]-[\w-]{6,}
    | \bxapp-[\w-]{6,}
    | \b(?:sk|pk|rk)[-_](?:live|test|ant|proj|or)?[-_]?[\w-]{12,}
    | \bsk-[\w-]{16,}
    | \bgh[pousr]_[\w]{16,}
    | \bgithub_pat_[\w]{16,}
    | \bglpat-[\w-]{12,}
    | \bnpm_[\w]{20,}
    | \b(?:AKIA|ASIA|AGPA|AIDA|AROA)[A-Z0-9]{12,}
    | \bAIza[\w-]{20,}
    | \bya29\.[\w.-]{10,}
    | \beyJ[\w-]{8,}\.[\w-]{8,}(?:\.[\w-]*)?
    | -----BEGIN[ A-Z]*(?:PRIVATE KEY|CERTIFICATE|PGP)
    | \b[a-z][a-z0-9+.-]*://[^\s/@:]+:[^\s/@]+@
    | (?:token|secret|passw(?:or)?d|passwd|pwd|api[_-]?key|apikey|credential|private[_-]?key|cookie|session[_-]?id|access[_-]?key)[\w-]*\s*[:=]
    | [?&](?:token|key|secret|sig|signature|password|access_token|api_key)=
    """
)
_LONG_BLOB = re.compile(r"[A-Za-z0-9_+/=.-]{24,}")


def _looks_sensitive(text: str, *, blobs: bool = True) -> bool:
    if _SUSPICIOUS.search(text):
        return True
    if not blobs:
        return False
    for blob in _LONG_BLOB.findall(text):
        compact = blob.strip("-_.=/+")
        has_digit = any(c.isdigit() for c in compact)
        if re.fullmatch(r"[0-9a-fA-F]{32,}", compact):
            return True
        if (
            len(compact) >= 24
            and has_digit
            and any(c.islower() for c in compact)
            and any(c.isupper() for c in compact)
        ):
            return True
    return False


_SLASHES = str.maketrans({"\u2215": "/", "\u2044": "/", "\u29f8": "/", "\uff0f": "/", "\u2216": "\\", "\u29f5": "\\", "\uff3c": "\\"})


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_SLASHES)
    text = "".join(" " if c.isspace() else c for c in text if unicodedata.category(c)[0] != "C" or c.isspace())
    return " ".join(text.split())


_MAX_DECODE_PASSES = 6
# Only the first SCAN_LIMIT characters are ever inspected or published (output is far shorter),
# which also bounds the work done on hostile input.
SCAN_LIMIT = 1000
_ESCAPES = re.compile(r"\\u([0-9a-fA-F]{4})|\\x([0-9a-fA-F]{2})")
_B64 = re.compile(r"[A-Za-z0-9+/]{16,}={0,2}")


def _unescape(text: str) -> str:
    return _ESCAPES.sub(lambda m: chr(int(m.group(1) or m.group(2), 16)), text)


def _utf7(text: str) -> str:
    if "+" not in text:
        return text
    try:
        return text.encode("ascii", "ignore").decode("utf-7", "ignore")
    except (UnicodeError, ValueError):
        return text


def _base64_payloads(text: str) -> list[str]:
    out = []
    for blob in _B64.findall(text)[:8]:
        if len(blob) % 4:
            continue
        try:
            raw = base64.b64decode(blob, validate=True)
        except (ValueError, binascii.Error):
            continue
        decoded = raw.decode("utf-8", "ignore")
        if decoded and all(c.isprintable() for c in decoded):
            out.append(decoded)
    return out


def _sensitive_any(text: str, *, blobs: bool = True) -> bool:
    """True if the text, or any bounded percent/HTML/escape/UTF-7-decoded + NFKC-normalized
    form (or a base64 payload inside it), looks like a credential. Fails closed if decoding
    never settles (deep nesting)."""
    variant = _normalize(text[: SCAN_LIMIT * 4])[:SCAN_LIMIT]
    for _ in range(_MAX_DECODE_PASSES + 1):
        squashed = re.sub(r"[\s\u200b-\u200f]+", "", variant)
        if _looks_sensitive(variant, blobs=blobs) or _looks_sensitive(squashed, blobs=False):
            return True
        if any(_looks_sensitive(p, blobs=False) for p in _base64_payloads(squashed)):
            return True
        if "+" in variant and _looks_sensitive(_normalize(_utf7(variant)), blobs=False):
            return True  # UTF-7 must be checked before unquote_plus turns "+" into a space
        decoded = _normalize(_utf7(_unescape(html.unescape(unquote_plus(variant)))))[:SCAN_LIMIT]
        if decoded == variant:
            return False
        variant = decoded
    return True


# Private filesystem locations (home dirs, worktrees, temp dirs, UNC/drive paths) must not reach
# the browser even though they are not credentials. A single leading-slash word such as a slash
# command ("/usage-limits") and ordinary branch names ("feature/x") are not paths.
_PATH_ROOTS = (
    "users", "home", "volumes", "private", "var", "tmp", "etc", "opt", "root", "mnt", "srv",
    "library", "applications", "system", "usr", "proc", "dev", "nix", "snap",
)
_PATHLIKE = re.compile(
    r"""(?ix)
      (?:^|[^a-z0-9])                       # path roots may follow any punctuation, not only spaces
      (?:
          ~[\w.-]*[\\/]                      # ~/x  ~user/x
        | \.{1,2}[\\/][^\s]                   # ./x  ../x
        | [a-z]:[\\/]                          # C:\x  C:/x
        | \\\\[^\s\\/]+[\\/]                 # \\server\share, \\wsl$\distro
        | file:/{1,3}[^\s]
        | /(?:""" + "|".join(_PATH_ROOTS) + r""")(?![\w.-])   # /Users  /tmp  [/Users]
        | /[\w.@+-]+/[\w.@+-]                  # any absolute path with 2+ segments
      )
    """
)
# Unambiguous macOS/home roots count even when glued to a word ("prefix/Users/me").
_EMBEDDED_ROOT = re.compile(r"(?i)/(?:users|volumes|private)/[^/\s]")
_URL = re.compile(r"(?i)\bhttps?://[^\s]+")
_WIN_HOME = re.compile(r"(?i)[\\/](?:users|home)[\\/][^\\/\s]+[\\/]")
_WORKTREE = re.compile(r"(?i)\.(?:t3|claude|codex|config|ssh|aws|gnupg)[\\/]")


def _looks_like_path(text: str) -> bool:
    # Public http(s) URLs are not filesystem paths (https://github.com/Users/x/repo stays visible).
    text = _URL.sub(" ", text)
    return bool(
        _PATHLIKE.search(text)
        or _EMBEDDED_ROOT.search(text)
        or _WIN_HOME.search(text)
        or _WORKTREE.search(text)
    )


def _pathlike_any(text: str) -> bool:
    """Path check on the text and its bounded percent/HTML-decoded forms."""
    variant = text[:SCAN_LIMIT]
    for _ in range(_MAX_DECODE_PASSES + 1):
        if _looks_like_path(variant):
            return True
        decoded = _normalize(html.unescape(unquote_plus(variant)))[:SCAN_LIMIT]
        if decoded == variant:
            return False
        variant = decoded
    return True


def safe_text(value: Any, limit: int = 160) -> str | None:
    """Sanitize untrusted display metadata; suspicious values are fully replaced."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = _normalize(value)
    if not text:
        return None
    if _sensitive_any(text):
        return REDACTED
    if _pathlike_any(text):
        return REDACTED_PATH
    return text[:limit]


_IDENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@%+-]{0,119}")
_THREAD_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@%+-]{0,299}")


_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)


_DELEGATED_ID = re.compile(
    r"thread:delegated-task:command:mcp:(?P<uuid>" + _UUID.pattern + r"):delegate-task:(?P<rid>[^:]+)",
    re.IGNORECASE,
)


def safe_thread_id(value: Any) -> bool:
    """Plain IDs only. UUIDs pass. The known T3 delegated-task composite is parsed; its
    agent-chosen request ID gets credential-signature/encoded-form checks but not the opaque
    blob heuristic (legitimate IDs may be long and mixed-case). Any other shape gets the full
    check on every non-UUID segment."""
    if not isinstance(value, str) or not _THREAD_ID.fullmatch(value):
        return False
    if _UUID.fullmatch(value):
        return True
    if _sensitive_any(value, blobs=False):
        return False
    decoded = unquote_plus(value)
    known = _DELEGATED_ID.fullmatch(decoded)
    if known:
        return not _sensitive_any(known["rid"], blobs=False)
    return not any(
        _sensitive_any(seg) for seg in decoded.split(":") if seg and not _UUID.fullmatch(seg)
    )


def safe_ident(value: Any) -> str | None:
    """Strict allowlist for machine-ish fields (status, model, version, ids)."""
    if (
        isinstance(value, str)
        and _IDENT.fullmatch(value)
        and not _looks_sensitive(value)
        and not _pathlike_any(value)
    ):
        return value
    return None


def timestamp(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value)
        return dt.astimezone(UTC).isoformat() if dt.tzinfo else None
    except ValueError:
        return None


def stable_id(source: str, thread: str) -> str:
    return "t3-" + hashlib.sha256(f"{source}\0{thread}".encode()).hexdigest()[:24]


async def collect(session: Any, cache: dict | None = None) -> dict:
    """Discover the public tool contract; bounded pagination, never dispatch a mutation."""
    cache = cache if cache is not None else {}
    next_cache = {}
    available = {}
    cursor = None
    for _ in range(10):
        page = await session.list_tools(cursor=cursor)
        available.update({tool.name: tool for tool in page.tools})
        cursor = page.nextCursor
        if not cursor:
            break
    required = {"t3_project_list", "t3_thread_list", "t3_thread_read"}
    if not required <= available.keys():
        raise ValueError("unsupported T3 read interface")
    props = available["t3_thread_list"].inputSchema.get("properties", {})
    if "includeSubagents" not in props:
        raise ValueError("T3 cannot list delegated threads")

    async def call(name, args):
        if name not in READ_TOOLS:
            raise ValueError("read-only adapter")
        result = await session.call_tool(name, args)
        if result.isError:
            raise ValueError("T3 read failed")
        payload = result.structuredContent
        if payload is None:
            payload = json.loads(
                next(c.text for c in result.content if c.type == "text")
            )
        if not isinstance(payload, dict) or "error" in payload:
            raise ValueError("invalid T3 result")
        return payload

    async def pages(name, key, args):
        result, cursor, seen = [], 0, set()
        for _ in range(10):
            if cursor in seen:
                raise ValueError("repeated cursor")
            seen.add(cursor)
            page = await call(name, {**args, "cursor": cursor, "limit": 100})
            rows = page[key]
            if not isinstance(rows, list):
                raise TypeError("invalid T3 page")
            result.extend(rows)
            cursor = page.get("nextCursor")
            if cursor is None:
                return result
        raise ValueError("T3 snapshot exceeds 1000 item bound")

    environment = (
        await call("t3_environment_read", {})
        if "t3_environment_read" in available
        else {}
    )
    providers = (
        (await call("orchestrator_capabilities", {})).get("providers", [])
        if "orchestrator_capabilities" in available
        else []
    )
    projects = await pages("t3_project_list", "projects", {})
    if len(projects) > 50:
        raise ValueError("T3 snapshot exceeds 50 project bound")
    threads = []
    for project in projects:
        listed = await pages(
            "t3_thread_list",
            "threads",
            {"projectId": project["id"], "includeSubagents": True},
        )
        for row in listed:
            key = row["threadId"]
            fingerprint = json.dumps(row, sort_keys=True)
            cached = cache.get(key)
            if cached and cached[0] == fingerprint:
                thread = cached[1]
            else:
                # Read minimal activity to obtain branch and last verified source timestamp.
                detail = await call(
                    "t3_thread_read",
                    {
                        "threadId": row["threadId"],
                        "view": "activity",
                        "limit": 1,
                        "runLimit": 1,
                        "maxCharsPerItem": 1,
                    },
                )
                thread = dict(detail["thread"])
                runs = detail.get("recentRuns", [])
                latest = next(
                    (r for r in runs if r.get("runId") == thread.get("latestRunId")),
                    None,
                )
                # A thread's selected model is not proof of the model used by a run.
                thread["model"] = latest.get("model") if latest else None
                thread["providerInstanceId"] = (
                    latest.get("providerInstanceId")
                    if latest
                    else thread.get("providerInstanceId")
                )
            next_cache[key] = (fingerprint, thread)
            threads.append(
                {**thread, "projectTitle": project.get("title", project["id"])}
            )
            if len(threads) > 500:
                raise ValueError("T3 snapshot exceeds 500 thread bound")
    cache.clear()
    cache.update(next_cache)
    # Everything else (including timeline text and environment preferences) is dropped.
    return {
        "environment": {"serverVersion": environment.get("serverVersion")},
        "providers": [
            {
                "providerInstanceId": p.get("providerInstanceId"),
                "driverKind": p.get("driverKind"),
                "displayName": p.get("displayName") if isinstance(p.get("displayName"), str) else None,
            }
            for p in providers
        ],
        "threads": threads,
    }


class T3Projection:
    def __init__(
        self, source: str, *, demo: bool = False, stale_after: float = 300, poll_sec: float | None = None
    ):
        self.source = source
        self.poll_sec = poll_sec  # producer cadence; lets clients bound "continuous observation"
        self.demo = demo
        self.stale_after = stale_after
        self.last: dict | None = None
        self.slots: dict[str, int] = {}

    def snapshot(self, raw: dict | None, now: float) -> dict:
        connected = raw is not None
        incoming = raw
        raw = raw if connected else self.last
        raw = raw or {"threads": [], "providers": [], "environment": {}}
        providers = {
            p.get("providerInstanceId"): p.get("driverKind") for p in raw["providers"]
        }
        display_names = {
            p.get("providerInstanceId"): safe_text(p.get("displayName"), 40) for p in raw["providers"]
        }
        # Thread IDs reach node IDs, source URLs and the browser: drop any that are not plain IDs
        # or that look like credentials (real IDs are UUIDs / `thread:...` forms).
        rows = {
            t["threadId"]: t
            for t in raw["threads"]
            if safe_thread_id(t["threadId"])
        }
        nodes, events, edges = [], [], []
        for thread_id, t in sorted(rows.items()):
            nid = stable_id(self.source, thread_id)
            slot = self.slots.setdefault(nid, len(self.slots))
            ts = timestamp(t.get("updatedAt"))
            age = now - datetime.fromisoformat(ts).timestamp() if ts else float("inf")
            reported = safe_ident(t.get("status")) or "unknown"
            stale = not connected or (
                reported in {"running", "queued", "waiting", "preparing", "starting"}
                and (age > self.stale_after or age < -60)
            )
            driver = providers.get(t.get("providerInstanceId"))
            # Which T3 provider instance ran the thread: the only honest way to tell two Claude memberships apart.
            instance = safe_ident(t.get("providerInstanceId"))
            account = (
                {"id": instance, "label": display_names.get(t.get("providerInstanceId")) or instance}
                if instance and len(instance) <= 64 and re.fullmatch(r"[A-Za-z0-9_.-]+", instance)
                else None
            )
            provider = {"codex": "Codex", "claudeAgent": "Claude Code"}.get(
                driver, safe_ident(driver)
            )
            links = []
            pr = t.get("linkedPullRequest") or {}
            url = pr.get("url", "")
            if re.fullmatch(r"https://github\.com/[\w.-]+/[\w.-]+/pull/[1-9]\d*", url):
                links.append(url)
            node = {
                "id": nid,
                "label": safe_text(t.get("title")) or "Untitled session",
                "group": "sessions",
                "status": "STALE" if stale else STATUS.get(reported, "UNKNOWN"),
                "current_task": safe_text(t.get("title")) or "Unknown task",
                "agent_links": [],
                "layout": {"x": (slot % 4) * 300, "y": (slot // 4) * 200},
                "session": {
                    "source": self.source,
                    "thread_id": thread_id,
                    "project": safe_text(t.get("projectTitle")) or "Unknown project",
                    "provider": provider,
                    "account": account,
                    "model": safe_text(t.get("model")),
                    "reported_status": reported,
                    "branch": safe_text(t.get("branch")),
                    "source_links": links,
                    "stale": stale,
                },
            }
            if ts:
                node["last_activity_ts"] = ts
            nodes.append(node)
            if ts:
                event_id = (
                    "state-"
                    + hashlib.sha256(f"{nid}:{ts}:{reported}".encode()).hexdigest()[:24]
                )
                events.append(
                    {
                        "id": event_id,
                        "type": "note",
                        "actor": nid,
                        "target": None,
                        "task_id": None,
                        "attribution": {"method": "unknown"},
                        "source_url": "t3-thread://v1/" + thread_id,
                        "source_time": ts,
                        "raw": ("Simulated thread status: " if self.demo else "T3 reported thread status: ") + reported,
                    }
                )
            parent = t.get("parentThreadId")
            if (
                parent in rows
                and parent != thread_id
                and t.get("relationshipToParent") == "subagent"
            ):
                eid = "delegation-" + nid
                created = timestamp(t.get("createdAt"))
                if created:
                    events.append(
                        {
                            "id": eid,
                            "type": "note",
                            "actor": stable_id(self.source, parent),
                            "target": nid,
                            "task_id": None,
                            "attribution": {"method": "unknown"},
                            "source_url": "t3-thread://v1/" + thread_id,
                            "source_time": created,
                            "raw": "Simulated subagent lineage" if self.demo else "T3 reported subagent lineage",
                        }
                    )
                    edges.append(
                        {
                            "id": eid,
                            "source": stable_id(self.source, parent),
                            "target": nid,
                            "type": "delegation",
                            "count": 1,
                            "event_ids": [eid],
                        }
                    )
        activity = {
            "schema_version": "1.0.0",
            "generated_at": datetime.fromtimestamp(now, UTC).isoformat(),
            "project": "T3 Code",
            "meta": {
                "github": "skipped",
                "ledger": "skipped",
                "t3": {
                    "source": self.source,
                    "mode": "demo" if self.demo else "live",
                    "connection": "connected" if connected else "unavailable",
                    "server_version": safe_ident(
                        raw["environment"].get("serverVersion")
                    ),
                    "stale_after_sec": self.stale_after,
                    **({"poll_sec": self.poll_sec} if self.poll_sec else {}),
                },
            },
            "nodes": nodes,
            "tasks": [],
            "events": events,
            "edges": edges,
            "unparsed": [],
        }
        from .build import validate_activity

        validate_activity(activity)
        if connected:
            self.last = copy.deepcopy(incoming)
        return activity


def read_demo() -> dict:
    return json.loads(
        (Path(__file__).resolve().parents[1] / "fixtures/t3-demo.json").read_text()
    )


# Fixed synthetic scenario: no discovery, provider calls or wall-clock timestamps.
DEMO_REPLAY_EPOCH = 1792699200
DEMO_REPLAY_STAGES = (
    ("Agents idle", "idle", "idle"),
    ("Minecraft navigation task assigned", "idle", "idle"),
    ("Codex plans a safe route to the village", "running", "idle"),
    ("Codex delegates navigation tests to Claude", "running", "queued"),
    (
        "Route implementation and navigation tests run concurrently",
        "running",
        "running",
    ),
    ("Codex waits for the chunk-map dependency", "waiting", "running"),
    ("Claude's simulated obstacle test fails", "waiting", "failed"),
    ("Dependency ready; implementation and test retry begin", "running", "running"),
    ("Navigation implementation and tests complete", "completed", "completed"),
    ("Replay resets: tasks and delegation cleared", "idle", "idle"),
)


def demo_replay(elapsed: float, step_sec: float = 5) -> tuple[dict, dict, float]:
    """Pure, seekable replay. Identical elapsed time always produces identical data."""
    import math

    if not math.isfinite(step_sec) or not 2 <= step_sec <= 300:
        raise ValueError("Demo replay step must be 2–300 seconds")
    if not math.isfinite(elapsed):
        raise ValueError("Demo replay elapsed time must be finite")
    tick = math.floor(max(0, elapsed) / step_sec)
    cycle, stage = divmod(tick, len(DEMO_REPLAY_STAGES))
    label, codex_status, claude_status = DEMO_REPLAY_STAGES[stage]
    observed = DEMO_REPLAY_EPOCH + tick * step_sec
    ts = datetime.fromtimestamp(observed, UTC).isoformat()
    delegated_at = datetime.fromtimestamp(
        DEMO_REPLAY_EPOCH + (cycle * len(DEMO_REPLAY_STAGES) + 3) * step_sec, UTC
    ).isoformat()
    delegated = 3 <= stage <= 8
    assigned = 1 <= stage <= 8
    raw = {
        "environment": {"serverVersion": "SYNTHETIC REPLAY"},
        "providers": [
            {"providerInstanceId": "demo-codex", "driverKind": "codex"},
            {"providerInstanceId": "demo-claude", "driverKind": "claudeAgent"},
        ],
        "threads": [],
    }
    for agent, status, title, model in (
        (
            "codex",
            codex_status,
            "Navigate Minecraft safely to the village"
            if assigned
            else "Codex · awaiting a demo task",
            "GPT-5-Codex (simulated)",
        ),
        (
            "claude",
            claude_status,
            "Retry obstacle and safe-path tests"
            if stage == 7
            else "Test Minecraft obstacle avoidance"
            if delegated
            else "Claude · awaiting a demo task",
            "Claude Sonnet (simulated)",
        ),
    ):
        raw["threads"].append(
            {
                "threadId": "demo-replay-" + agent,
                "projectTitle": "BlockForge · Minecraft Navigation (synthetic)",
                "title": "[SIMULATED] " + title,
                "status": status,
                "providerInstanceId": "demo-" + agent,
                "model": model,
                "updatedAt": ts,
                "createdAt": delegated_at if agent == "claude" and delegated else ts,
                "branch": "demo/minecraft-navigation" if assigned else None,
                "linkedPullRequest": None,
                "parentThreadId": "demo-replay-codex"
                if agent == "claude" and delegated
                else None,
                "relationshipToParent": "subagent"
                if agent == "claude" and delegated
                else None,
            }
        )
    return (
        raw,
        {
            "stage": stage,
            "stage_count": len(DEMO_REPLAY_STAGES),
            "cycle": cycle,
            "step_sec": step_sec,
            "label": label,
        },
        observed,
    )
