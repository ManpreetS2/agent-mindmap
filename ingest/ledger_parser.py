"""
Parse `build/task-ledger.md` into Tasks and Events (MM-002).

Stdlib only (Python 3.12). No network. Times are America/Los_Angeles.
Output fields match schema/activity.schema.json ($defs/task, $defs/event).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Los_Angeles")
UNDATED_SOURCE_TIME = "1970-01-01T00:00:00-08:00"

# Exact MM-001 task-id patterns (schema $defs/taskId).
TASK_ID_STANDARD = re.compile(r"^[A-Z]{2,}-[0-9]{3}[A-Za-z0-9]*(-[0-9]+)?$")
TASK_ID_BACKLOG = re.compile(r"^[A-Z]{2,}-[A-Z]{2}[0-9]{3}(-[0-9]+)?$")
TASK_ID_ANY = re.compile(
    r"(?:[A-Z]{2,}-[0-9]{3}[A-Za-z0-9]*(?:-[0-9]+)?|[A-Z]{2,}-[A-Z]{2}[0-9]{3}(?:-[0-9]+)?)"
)

# Architecture §4.1 — tolerant free-text note line.
NOTE_RE = re.compile(
    r"""
    ^-\s*
    (?P<date>\d{4}-\d{2}-\d{2})\s+
    (?P<time>\d{1,2}:\d{2}(?:\s*[AP]M)?)\s*
    P[DS]T
    [,:]?\s*
    (?:
        (?P<actor>[A-Za-z0-9 /&]+?)
        (?:\s+CORRECTION)?
        \s*:
    )?
    \s*(?P<text>.+)$
    """,
    re.VERBOSE | re.IGNORECASE,
)

# Structured (Director ADOPTED): ISO form
#   - <ISO ts with offset> | <actor> | <type> | <task> | <text>
STRUCTURED_ISO_RE = re.compile(
    r"""
    ^-\s*
    (?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:[+-]\d{2}:\d{2}|Z))\s*
    \|\s*(?P<actor>[^|]+?)\s*
    \|\s*(?P<etype>[^|]+?)\s*
    \|\s*(?P<task>[^|]+?)\s*
    \|\s*(?P<text>.+)$
    """,
    re.VERBOSE,
)

# Structured ledger handoff form observed in the real ledger:
#   - YYYY-MM-DD HH:MM PDT | actor | handoff | TASK | text
# Also accepts optional seconds and optional AM/PM.
STRUCTURED_PDT_RE = re.compile(
    r"""
    ^-\s*
    (?P<date>\d{4}-\d{2}-\d{2})\s+
    (?P<time>\d{1,2}:\d{2}(?::\d{2})?(?:\s*[AP]M)?)\s*
    P[DS]T\s*
    \|\s*(?P<actor>[^|]+?)\s*
    \|\s*(?P<etype>[^|]+?)\s*
    \|\s*(?P<task>[^|]+?)\s*
    \|\s*(?P<text>.+)$
    """,
    re.VERBOSE | re.IGNORECASE,
)

# Table row: id cell must be a schema-valid task id.
TABLE_ROW_RE = re.compile(
    r"""
    ^\|\s*
    (?P<id>[^|]+?)\s*\|\s*
    (?P<title>[^|]+?)\s*\|\s*
    (?P<owner>[^|]+?)\s*\|\s*
    (?P<mode>[^|]*?)\s*\|\s*
    (?P<model>[^|]*?)\s*\|\s*
    (?P<status>[^|]*?)\s*\|\s*
    (?P<evidence>[^|]*?)\s*
    \|\s*$
    """,
    re.VERBOSE,
)

TABLE_SEP_RE = re.compile(r"^\|[\s:|-]+\|\s*$")
HEADING_RE = re.compile(r"^#{1,6}\s+")
PR_RE = re.compile(r"PR\s*#\s*(\d+)", re.IGNORECASE)
SHA_RE = re.compile(
    r"(?:squash-)?merged\s+as\s+([0-9a-f]{7,40})",
    re.IGNORECASE,
)
HANDOFF_RE = re.compile(
    r"(?:GO\s+for|assigned\s+to|handed\s+to)\s+([A-Za-z0-9 /&]+?)(?:\s+for\b|\s+on\b|[.;,]|$)",
    re.IGNORECASE,
)
VERDICT_RE = re.compile(r"\b(PASS|FAIL|CHANGES)\b", re.IGNORECASE)
BLOCKED_RE = re.compile(r"\bBLOCKED\w*\b", re.IGNORECASE)

STATUS_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bBLOCKED\w*\b", re.I), "BLOCKED"),
    (re.compile(r"\bIN_REVIEW\b", re.I), "IN_REVIEW"),
    (re.compile(r"\bIN_PROGRESS\b", re.I), "IN_PROGRESS"),
    (re.compile(r"\b(?:DONE|MERGED)\b", re.I), "DONE"),
    (re.compile(r"\b(?:PLANNED|GO)\b", re.I), "IDLE"),
]

EVENT_TYPES = frozenset(
    {
        "assigned",
        "handoff",
        "pr_opened",
        "pr_updated",
        "verdict",
        "merged",
        "blocker",
        "ci",
        "note",
        "unparsed",
    }
)

# Back-compat alias used by tests.
STRUCTURED_RE = STRUCTURED_ISO_RE


@dataclass
class LedgerParseResult:
    """Partial activity payload from the ledger (tasks + events + unparsed)."""

    tasks: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    unparsed: list[dict[str, Any]] = field(default_factory=list)
    input_lines: list[str] = field(default_factory=list)
    parsed_lines: list[str] = field(default_factory=list)
    unparsed_lines: list[str] = field(default_factory=list)
    # Parallel to unparsed_lines / unparsed events: human reasons (not in schema).
    unparsed_reasons: list[str] = field(default_factory=list)
    source_url: str = "build/task-ledger.md"


def is_valid_task_id(value: str) -> bool:
    return bool(TASK_ID_STANDARD.fullmatch(value) or TASK_ID_BACKLOG.fullmatch(value))


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_bots_config(path: Path | None = None) -> list[dict[str, Any]]:
    cfg_path = path or (_repo_root() / "config" / "bots.json")
    with cfg_path.open(encoding="utf-8") as f:
        data = json.load(f)
    return list(data["bots"])


def _alias_map(bots: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Longest-alias-first map of lowercased alias → bot id."""
    pairs: list[tuple[str, str]] = []
    for bot in bots:
        candidates = {bot["display_name"], bot["id"], *bot.get("aliases", [])}
        for alias in candidates:
            cleaned = alias.lstrip("~").strip()
            if cleaned:
                pairs.append((cleaned.lower(), bot["id"]))
    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    return pairs


def resolve_actor(name: str | None, alias_pairs: list[tuple[str, str]]) -> str | None:
    if not name:
        return None
    key = name.lstrip("~").strip().lower()
    if not key:
        return None
    for alias, bot_id in alias_pairs:
        if key == alias or key.startswith(alias + " "):
            return bot_id
    return None


def event_id(source: str, locator: str) -> str:
    """Stable id: sha1(source + locator), hex digest."""
    return hashlib.sha1(f"{source}{locator}".encode("utf-8")).hexdigest()


def normalize_status(status_raw: str) -> str:
    """Last keyword match wins (scan left-to-right; later rules overwrite)."""
    found: list[tuple[int, str]] = []
    for pattern, status in STATUS_RULES:
        for m in pattern.finditer(status_raw):
            found.append((m.start(), status))
    if not found:
        return "UNKNOWN"
    found.sort(key=lambda t: t[0])
    return found[-1][1]


def extract_prs(*texts: str) -> list[int]:
    nums: list[int] = []
    seen: set[int] = set()
    for text in texts:
        for m in PR_RE.finditer(text):
            n = int(m.group(1))
            if n not in seen:
                seen.add(n)
                nums.append(n)
    return nums


def extract_task_id(text: str) -> str | None:
    m = TASK_ID_ANY.search(text)
    return m.group(0) if m else None


def parse_ledger_datetime(date_s: str, time_s: str) -> str:
    """
    Parse ledger date+time (12h or 24h) as America/Los_Angeles → ISO offset.

    Raises ValueError for malformed combinations such as '13:00 PM'.
    """
    time_s = re.sub(r"\s+", " ", time_s.strip())
    has_ampm = bool(re.search(r"[AP]M", time_s, re.IGNORECASE))
    # Reject impossible 12h clocks early (e.g. 13:00 PM).
    if has_ampm:
        hour_m = re.match(r"(\d{1,2}):", time_s)
        if hour_m and not (1 <= int(hour_m.group(1)) <= 12):
            raise ValueError(f"malformed_time: {date_s} {time_s}")
    formats = (
        ("%Y-%m-%d %I:%M %p", True),
        ("%Y-%m-%d %I:%M:%S %p", True),
        ("%Y-%m-%d %H:%M", False),
        ("%Y-%m-%d %H:%M:%S", False),
    )
    for fmt, wants_ampm in formats:
        if wants_ampm != has_ampm:
            continue
        try:
            dt = datetime.strptime(f"{date_s} {time_s}", fmt)
            return dt.replace(tzinfo=TZ).isoformat()
        except ValueError:
            continue
    raise ValueError(f"malformed_time: {date_s} {time_s}")


def classify_note_text(
    text: str,
    actor_id: str | None,
    alias_pairs: list[tuple[str, str]],
) -> tuple[str, str | None, dict[str, Any]]:
    """
    Ordered classifiers from architecture §4.1.
    Returns (event_type, target_bot_id, extra_fields).
    """
    extra: dict[str, Any] = {}
    task_id = extract_task_id(text)
    if task_id:
        extra["task_id"] = task_id

    prs = extract_prs(text)
    if prs:
        extra["pr"] = prs[0]

    sha_m = SHA_RE.search(text)
    if sha_m:
        extra["sha"] = sha_m.group(1).lower()
        return "merged", actor_id, extra

    verdict_m = VERDICT_RE.search(text)
    if verdict_m and actor_id:
        extra["verdict"] = verdict_m.group(1).upper()
        return "verdict", None, extra

    if BLOCKED_RE.search(text):
        return "blocker", None, extra

    handoff_m = HANDOFF_RE.search(text)
    if handoff_m:
        target = resolve_actor(handoff_m.group(1).strip(), alias_pairs)
        phrase = handoff_m.group(0).lower()
        etype = "handoff" if "handed" in phrase else "assigned"
        return etype, target, extra

    return "note", None, extra


def _resolve_handoff_target(
    text: str,
    alias_pairs: list[tuple[str, str]],
) -> str | None:
    handoff_m = HANDOFF_RE.search(text)
    if handoff_m:
        return resolve_actor(handoff_m.group(1).strip(), alias_pairs)
    # Structured body often: "to Architect for MM-001 …"
    m = re.search(
        r"\bto\s+([A-Za-z0-9 /&]+?)(?:\s+for\b|\s+on\b|[.;,]|$)",
        text,
        re.IGNORECASE,
    )
    if m:
        return resolve_actor(m.group(1).strip(), alias_pairs)
    return None


def _is_structural(line: str) -> bool:
    s = line.strip()
    if not s:
        return True
    if HEADING_RE.match(s):
        return True
    if TABLE_SEP_RE.match(s):
        return True
    if s.startswith("|") and s.endswith("|"):
        cells = [c.strip() for c in s.strip("|").split("|")]
        if cells and cells[0].upper() in {"ID", "TASK", "TASK ID"}:
            return True
    return False


def _make_event(
    *,
    raw: str,
    etype: str,
    actor: str | None,
    target: str | None,
    task_id: str | None,
    source_time: str,
    source_url: str,
    attribution_method: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    eid = event_id("ledger", raw)
    # Drop task_id that would fail schema validation.
    if task_id is not None and not is_valid_task_id(task_id):
        task_id = None
    evt: dict[str, Any] = {
        "id": eid,
        "type": etype,
        "actor": actor,
        "target": target,
        "task_id": task_id,
        "attribution": {"method": attribution_method},
        "source_url": source_url,
        "source_time": source_time,
        "raw": raw,
    }
    if extra:
        for key in ("pr", "sha", "verdict"):
            if key in extra and extra[key] is not None:
                evt[key] = extra[key]
    return evt


def _record_unparsed(
    result: LedgerParseResult,
    seen_event_ids: set[str],
    *,
    stripped: str,
    source_url: str,
    reason: str,
) -> None:
    """Undated / malformed / invalid lines → unparsed bucket + timeline note."""
    evt = _make_event(
        raw=stripped,
        etype="unparsed",
        actor=None,
        target=None,
        task_id=extract_task_id(stripped),
        source_time=UNDATED_SOURCE_TIME,
        source_url=source_url,
        attribution_method="unknown",
    )
    # Encode reason in a parallel timeline note id space; keep event.raw original.
    # Tests assert via result.unparsed_reasons (not schema fields).
    note_evt = _make_event(
        raw=stripped,
        etype="note",
        actor=None,
        target=None,
        task_id=extract_task_id(stripped),
        source_time=UNDATED_SOURCE_TIME,
        source_url=source_url,
        attribution_method="unknown",
    )
    note_evt["id"] = event_id("ledger", f"note:{stripped}")
    # Surface reason in note raw prefix for schema-visible diagnostics without
    # inventing fields (additionalProperties: false on Event).
    note_evt["raw"] = f"[{reason}] {stripped}"
    note_evt["id"] = event_id("ledger", f"note:{note_evt['raw']}")

    result.unparsed_lines.append(stripped)
    result.unparsed_reasons.append(reason)
    if evt["id"] not in seen_event_ids:
        seen_event_ids.add(evt["id"])
        result.unparsed.append(evt)
    if note_evt["id"] not in seen_event_ids:
        seen_event_ids.add(note_evt["id"])
        result.events.append(note_evt)


def _emit_structured_event(
    *,
    stripped: str,
    actor_raw: str,
    etype_raw: str,
    task_raw: str,
    body: str,
    source_time: str,
    source_url: str,
    aliases: list[tuple[str, str]],
    result: LedgerParseResult,
    seen_event_ids: set[str],
) -> None:
    actor_id = resolve_actor(actor_raw, aliases)
    etype_norm = etype_raw.strip().lower()
    etype = etype_norm if etype_norm in EVENT_TYPES else "note"
    task_id = task_raw.strip() if is_valid_task_id(task_raw.strip()) else extract_task_id(task_raw)
    method = "ledger_owner" if actor_id else "unknown"
    classified_type, target, extra = classify_note_text(body, actor_id, aliases)
    if task_id:
        extra.setdefault("task_id", task_id)

    if etype != "note":
        final_type = etype
    else:
        final_type = classified_type

    if final_type == "handoff":
        target = target or _resolve_handoff_target(body, aliases)
    elif final_type == "assigned":
        target = target or _resolve_handoff_target(body, aliases)

    evt = _make_event(
        raw=stripped,
        etype=final_type,
        actor=actor_id,
        target=target,
        task_id=extra.get("task_id", task_id),
        source_time=source_time,
        source_url=source_url,
        attribution_method=method,
        extra=extra,
    )
    result.parsed_lines.append(stripped)
    if evt["id"] not in seen_event_ids:
        seen_event_ids.add(evt["id"])
        result.events.append(evt)


def parse_ledger(
    text: str,
    *,
    source_url: str = "build/task-ledger.md",
    bots: list[dict[str, Any]] | None = None,
) -> LedgerParseResult:
    """Parse full ledger markdown into tasks, events, and unparsed."""
    bot_list = bots if bots is not None else load_bots_config()
    aliases = _alias_map(bot_list)
    result = LedgerParseResult(source_url=source_url)
    seen_event_ids: set[str] = set()

    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n")
        if _is_structural(line):
            continue

        stripped = line.strip()
        result.input_lines.append(stripped)

        # Pass 1: table data rows → Task (id must match schema exactly)
        table_m = TABLE_ROW_RE.match(stripped)
        if table_m:
            task_id = table_m.group("id").strip()
            if not is_valid_task_id(task_id):
                _record_unparsed(
                    result,
                    seen_event_ids,
                    stripped=stripped,
                    source_url=source_url,
                    reason="invalid_task_id",
                )
                continue
            status_raw = table_m.group("status").strip()
            evidence = table_m.group("evidence").strip()
            title = table_m.group("title").strip()
            owner = table_m.group("owner").strip()
            project = "fencepost"
            if ":" in title:
                project = title.split(":", 1)[0].strip().lower() or "fencepost"
            task = {
                "id": task_id,
                "title": title,
                "project": project,
                "owner": owner,
                "status_raw": status_raw,
                "status": normalize_status(status_raw),
                "prs": extract_prs(status_raw, evidence),
                "source_url": f"{source_url}#{task_id}",
            }
            result.tasks.append(task)
            result.parsed_lines.append(stripped)
            continue

        # Pass 2a: structured ISO
        struct_iso = STRUCTURED_ISO_RE.match(stripped)
        if struct_iso:
            ts = struct_iso.group("ts")
            source_time = ts.replace("Z", "+00:00") if ts.endswith("Z") else ts
            _emit_structured_event(
                stripped=stripped,
                actor_raw=struct_iso.group("actor"),
                etype_raw=struct_iso.group("etype"),
                task_raw=struct_iso.group("task"),
                body=struct_iso.group("text").strip(),
                source_time=source_time,
                source_url=source_url,
                aliases=aliases,
                result=result,
                seen_event_ids=seen_event_ids,
            )
            continue

        # Pass 2b: structured PDT (handoff lines from the real ledger)
        struct_pdt = STRUCTURED_PDT_RE.match(stripped)
        if struct_pdt:
            try:
                source_time = parse_ledger_datetime(
                    struct_pdt.group("date"),
                    struct_pdt.group("time"),
                )
            except ValueError:
                _record_unparsed(
                    result,
                    seen_event_ids,
                    stripped=stripped,
                    source_url=source_url,
                    reason="malformed_time",
                )
                continue
            _emit_structured_event(
                stripped=stripped,
                actor_raw=struct_pdt.group("actor"),
                etype_raw=struct_pdt.group("etype"),
                task_raw=struct_pdt.group("task"),
                body=struct_pdt.group("text").strip(),
                source_time=source_time,
                source_url=source_url,
                aliases=aliases,
                result=result,
                seen_event_ids=seen_event_ids,
            )
            continue

        # Pass 2c: free-text dated notes (4 variants)
        note_m = NOTE_RE.match(stripped)
        if note_m:
            try:
                source_time = parse_ledger_datetime(
                    note_m.group("date"),
                    note_m.group("time"),
                )
            except ValueError:
                _record_unparsed(
                    result,
                    seen_event_ids,
                    stripped=stripped,
                    source_url=source_url,
                    reason="malformed_time",
                )
                continue
            actor_raw = note_m.group("actor")
            actor_id = resolve_actor(actor_raw, aliases) if actor_raw else None
            body = note_m.group("text").strip()
            method = "ledger_owner" if actor_id else "unknown"
            etype, target, extra = classify_note_text(body, actor_id, aliases)
            evt = _make_event(
                raw=stripped,
                etype=etype,
                actor=actor_id,
                target=target,
                task_id=extra.get("task_id"),
                source_time=source_time,
                source_url=source_url,
                attribution_method=method,
                extra=extra,
            )
            result.parsed_lines.append(stripped)
            if evt["id"] not in seen_event_ids:
                seen_event_ids.add(evt["id"])
                result.events.append(evt)
            continue

        # Unparsed: undated bullets + prose
        _record_unparsed(
            result,
            seen_event_ids,
            stripped=stripped,
            source_url=source_url,
            reason="undated_or_prose",
        )

    return result


def parse_ledger_file(
    path: Path | str,
    *,
    source_url: str | None = None,
    bots: list[dict[str, Any]] | None = None,
) -> LedgerParseResult:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    url = source_url or str(p).replace("\\", "/")
    return parse_ledger(text, source_url=url, bots=bots)
