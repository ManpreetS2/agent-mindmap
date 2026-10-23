"""Read-only T3 MCP projection. No messages, tool output or credentials in activity.json."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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


def safe_text(value: Any, limit: int = 160) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    # Titles are metadata but can still contain pasted credentials. Never publish prompts.
    text = re.sub(
        r"(?i)(?:bearer\s+\S+|(?:sk-|ghp_|github_pat_|sk-ant-)[\w-]+)",
        "[redacted]",
        value,
    )
    text = re.sub(
        r"(?i)\b(?:[\w-]*(?:token|secret|password|api[_-]?key)[\w-]*)\s*[:=]\s*\S+",
        "[redacted]",
        text,
    )
    return " ".join(text.split())[:limit]


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
            }
            for p in providers
        ],
        "threads": threads,
    }


class T3Projection:
    def __init__(self, source: str, *, demo: bool = False, stale_after: float = 300):
        self.source = source
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
        rows = {t["threadId"]: t for t in raw["threads"]}
        nodes, events, edges = [], [], []
        for thread_id, t in sorted(rows.items()):
            nid = stable_id(self.source, thread_id)
            slot = self.slots.setdefault(nid, len(self.slots))
            ts = timestamp(t.get("updatedAt"))
            age = now - datetime.fromisoformat(ts).timestamp() if ts else float("inf")
            reported = safe_text(t.get("status")) or "unknown"
            stale = not connected or (
                reported in {"running", "queued", "waiting", "preparing", "starting"}
                and (age > self.stale_after or age < -60)
            )
            driver = providers.get(t.get("providerInstanceId"))
            provider = {"codex": "Codex", "claudeAgent": "Claude Code"}.get(
                driver, safe_text(driver)
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
                        "raw": "T3 reported thread status: " + reported,
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
                            "raw": "T3 reported subagent lineage",
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
                    "server_version": safe_text(
                        raw["environment"].get("serverVersion")
                    ),
                    "stale_after_sec": self.stale_after,
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
