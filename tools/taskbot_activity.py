"""Read-only view of Agent Control's taskbot activity, served as /automation.json.

Sources, both opened read-only and never created or written:
  <state>/taskbot.sqlite   tickets (queued / running / pr_open / failed ...) and runs (account, model, effort, outcome)
  <state>/events.sqlite    run_start / run_end / pr_opened / agent_failed ... with the run_id that is also the
                           `Bot-Run:` trailer on the bot's commits

Truthfulness rules (each has a test):
  * A taskbot task is a job record, NOT a T3 session. An issue -> PR link is taskbot's own bookkeeping, not
    model-to-model delegation; this document has no edges.
  * "running" needs a run_start without a run_end and a recent event. A ticket that says running with no recent
    event is reported "unknown" (crashed, asleep or pruned), never "running".
  * Model/effort are reported only when a run record or the run_start event states them; otherwise null.
  * Raw event messages (which can carry test output) are never exported. Only a short, redacted, single-line
    summary of an error event is, and prompts are not stored by taskbot at all.

    python -m tools.taskbot_activity --state-dir <agent-control state dir>      # prints the document
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ingest.t3 import safe_ident, safe_text

SCHEMA = "agent-mindmap-automation/v1"
ROOT = Path(__file__).resolve().parents[1]
DEMO_FIXTURE = ROOT / "fixtures" / "automation" / "demo.json"
ENV_STATE_DIR = "AGENT_MINDMAP_TASKBOT_STATE"
MAX_TASKS = 50
RECENT_DAYS = 14
RUNNING_STALE_AFTER = timedelta(minutes=30)
ERROR_EVENT_TYPES = ("agent_failed", "stuck", "preflight_blocked", "no_account", "infra_retry", "fix_limit")
STATES = ("queued", "running", "blocked", "failed", "completed", "skipped", "unknown")
RUN_START_MODEL = re.compile(r"^(?:job|investigation|CI fix|conflict fix) \(attempt \d+\) with (\S+) (\S+): ")
GITHUB_URL = re.compile(r"^https://github\.com/[\w.-]+/[\w.-]+/(?:pull|issues)/\d+$")

NOTES = [
    "Taskbot tasks are Agent Control job records, not T3 sessions; nothing here is a T3 session.",
    "An issue-to-PR link is taskbot's own bookkeeping. It does not show that one model delegated to another.",
    "A missing or old event is not evidence that taskbot is healthy or idle; the scheduler may simply be off.",
]


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.astimezone()


def _iso(t: datetime | None) -> str | None:
    return t.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z") if t else None


def _open_ro(path: Path) -> sqlite3.Connection:
    # mode=ro never creates a missing file; query_only is a second guard against any write.
    con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    return con


def state_dir_from_env(env: dict[str, str] | None = None) -> Path | None:
    """The Agent Control state directory, only when explicitly configured. Never guessed."""
    raw = (env if env is not None else os.environ).get(ENV_STATE_DIR)
    return Path(raw).expanduser() if raw else None


def _doc(now: datetime, mode: str, status: str, reason: str | None, last_event: datetime | None, tasks: list) -> dict:
    return {
        "schema": SCHEMA,
        "generated_at": _iso(now),
        "mode": mode,
        "source": {
            "kind": "agent-control-taskbot",
            "status": status,
            "last_event_at": _iso(last_event),
            "reason": safe_text(reason, 200) if reason else None,
        },
        "tasks": tasks,
        "notes": list(NOTES),
    }


def _summary(message: str | None) -> str | None:
    """First line only, redacted or cut. Never the raw message."""
    if not message:
        return None
    first = next((ln.strip() for ln in message.splitlines() if ln.strip()), "")
    return safe_text(first, 200)


def build_automation(state_dir: Path | None, now: datetime | None = None) -> dict | None:
    """The automation document, or None when no state directory is configured (the route answers 404)."""
    if state_dir is None:
        return None
    now = now or datetime.now(UTC)
    tb, ev = state_dir / "taskbot.sqlite", state_dir / "events.sqlite"
    if not tb.is_file() or not ev.is_file():
        return _doc(now, "live", "absent", "taskbot.sqlite or events.sqlite not found in the configured state directory", None, [])
    try:
        with _open_ro(tb) as tcon, _open_ro(ev) as econ:
            return _build(tcon, econ, now)
    except sqlite3.DatabaseError as exc:
        kind = "unsupported_schema" if "no such" in str(exc) else "unreadable"
        return _doc(now, "live", kind, f"{type(exc).__name__}: {exc}", None, [])


def _build(tcon: sqlite3.Connection, econ: sqlite3.Connection, now: datetime) -> dict:
    # events.sqlite is created lazily; a file with no events table yet means "no events", not a bad schema.
    has_events = econ.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='events'").fetchone()
    events = [dict(r) for r in econ.execute(
        "SELECT * FROM events WHERE bot='taskbot' ORDER BY id DESC LIMIT 5000")] if has_events else []
    last_event = max((_parse(e["time"]) for e in events if _parse(e["time"])), default=None)
    tickets = [dict(r) for r in tcon.execute("SELECT * FROM tickets")]
    runs = [dict(r) for r in tcon.execute("SELECT * FROM runs ORDER BY id")]

    cutoff = now - timedelta(days=RECENT_DAYS)
    active = {"queued", "fix_queued", "running", "fixing"}
    keep = [t for t in tickets if t["status"] in active or (_parse(t["updated_at"]) or cutoff) >= cutoff]
    tasks = [_task(t, events, runs, now) for t in keep]
    order = {s: i for i, s in enumerate(("running", "blocked", "queued", "failed", "unknown", "completed", "skipped"))}
    tasks.sort(key=lambda x: (order[x["state"]], _neg_ts(x["state_observed_at"])))
    return _doc(now, "live", "connected", None, last_event, tasks[:MAX_TASKS])


def _neg_ts(iso: str | None) -> float:
    t = _parse(iso)
    return -t.timestamp() if t else 0.0


def _task(t: dict, events: list[dict], runs: list[dict], now: datetime) -> dict:
    repo, number = t["repo"], t["number"]
    item = f"#{number}"
    mine = [e for e in events if e["repo"] == repo and e["item"] == item]  # newest first
    starts = [e for e in mine if e["type"] == "run_start"]
    latest_start = starts[0] if starts else None

    current_run = None
    assignment = {"account": None, "model": None, "effort": None, "known": False, "source": "none"}
    if latest_start:
        rid = latest_start["run_id"]
        of_run = [e for e in mine if e["run_id"] == rid]
        end = next((e for e in of_run if e["type"] == "run_end"), None)
        started, ended = _parse(latest_start["time"]), _parse(end["time"]) if end else None
        current_run = {
            "run_id": safe_ident(rid),
            "started_at": _iso(started),
            "ended_at": _iso(ended),
            "outcome": safe_ident(end["message"]) if end else None,
            "duration_sec": int((ended - started).total_seconds()) if ended and started else None,
        }
        assignment = _assignment(t, latest_start, runs)

    state, basis, completed_url = _classify(t, mine, latest_start, current_run, now)
    pr_url = t.get("pr_url") if completed_url and GITHUB_URL.match(t.get("pr_url") or "") else None
    errors = [e for e in mine if e["type"] in ERROR_EVENT_TYPES and e["severity"] in ("warning", "error")]
    err = errors[0] if errors else None
    evidence = None
    if state in ("failed", "blocked", "unknown") and (err or t.get("note")):
        evidence = {
            "type": safe_ident(err["type"]) if err else "ticket_note",
            "time": _iso(_parse(err["time"])) if err else None,
            "severity": err["severity"] if err else "warning",
            "summary": _summary(err["message"]) if err else _summary(t.get("note")),
        }
    wait = _parse(t.get("wait_until"))
    return {
        "id": f"taskbot:{repo}#{number}",
        "repo": safe_text(repo, 100),
        "issue": {
            "number": number,
            "title": safe_text(t["title"], 160),
            "url": f"https://github.com/{repo}/issues/{number}" if re.fullmatch(r"[\w.-]+/[\w.-]+", repo or "") else None,
        },
        "state": state,
        "state_basis": basis,
        "state_observed_at": _iso(_parse(t["updated_at"])),
        "attempts": t["attempts"] if isinstance(t["attempts"], int) else None,
        "assignment": assignment,
        "pull_request_url": pr_url,
        "current_run": current_run,
        "next_attempt_after": _iso(wait) if state == "blocked" and wait else None,
        "error_evidence": evidence,
        "recent_events": [
            {"time": _iso(_parse(e["time"])), "type": safe_ident(e["type"]), "severity": e["severity"],
             "run_id": safe_ident(e["run_id"])}
            for e in mine[:6]
        ],
    }


def _classify(t: dict, mine: list[dict], start: dict | None, run: dict | None, now: datetime):
    """(state, basis, show_pr). Every branch says why, so the UI can show it."""
    status = t["status"]
    if status in ("running", "fixing"):
        if not start or not run:
            return "unknown", f"ticket says '{status}' but no run_start event exists for it (events pruned or from another machine)", False
        if run["ended_at"]:
            return "unknown", f"ticket says '{status}' but its latest run already ended ({run['outcome'] or 'no outcome'})", False
        last = max((_parse(e["time"]) for e in mine if e["run_id"] == start["run_id"] and _parse(e["time"])), default=None)
        age = now - last if last else None
        if age is None or age > RUNNING_STALE_AFTER:
            mins = int(age.total_seconds() // 60) if age else None
            return "unknown", (f"ticket says '{status}' but there is no run_end and no event for "
                               f"{mins if mins is not None else '?'} min; the job may have crashed or the machine slept"), False
        return "running", f"run_start without run_end; last event {int(age.total_seconds())}s ago", False
    if status in ("queued", "fix_queued"):
        wait = _parse(t.get("wait_until"))
        if wait and wait > now:
            return "blocked", f"waiting until {_iso(wait)}" + (f": {_summary(t.get('note'))}" if t.get("note") else ""), False
        return "queued", f"ticket status '{status}'", False
    if status == "pr_open":
        return "completed", "taskbot opened a draft PR; awaiting human review, not merged", True
    if status == "merged":
        return "completed", "the PR was merged", True
    if status == "done":
        return "completed", "findings posted on the issue", False
    if status == "dry_run_done":
        return "completed", "dry run only: verified in a worktree, nothing was pushed", False
    if status == "failed":
        return "failed", "taskbot gave up after its attempt limit", False
    if status in ("skipped", "ignored", "gone", "superseded", "pr_closed"):
        return "skipped", f"ticket status '{status}'", False
    return "unknown", f"unrecognized ticket status '{safe_ident(status) or '?'}'", False


def _assignment(t: dict, start: dict, runs: list[dict]) -> dict:
    """Account from the event; model/effort from the run record with the same run_id, else the run_start text,
    else null. Never matched by time or by ticket alone, so an earlier attempt's model can't be attributed here."""
    account = safe_ident(start.get("account"))
    key = f"{t['repo']}#{t['number']}"
    rec = next((r for r in runs if r.get("run_id") and r["run_id"] == start["run_id"] and r["ticket"] == key), None)
    if rec and rec.get("model"):
        return {"account": account or safe_ident(rec.get("account")), "model": safe_ident(rec["model"]),
                "effort": safe_ident(rec.get("effort")), "known": True, "source": "run_record"}
    m = RUN_START_MODEL.match(start.get("message") or "")
    if m and safe_ident(m.group(1)):
        return {"account": account, "model": safe_ident(m.group(1)), "effort": safe_ident(m.group(2)),
                "known": True, "source": "event_message"}
    return {"account": account, "model": None, "effort": None, "known": False, "source": "none"}


def demo_automation(now: datetime) -> dict:
    """The synthetic fixture shifted to now. Always mode "demo"; never reads any state directory."""
    from tools.observability_doc import shift_times

    doc = json.loads(DEMO_FIXTURE.read_text(encoding="utf-8"))
    fixed = _parse(doc["generated_at"]) or now
    return shift_times(doc, now - fixed)


def automation_for_activity(activity: dict | None, now: datetime | None = None, env: dict[str, str] | None = None) -> dict | None:
    """What /automation.json serves for the daemon's current snapshot. None means 404.

    Demo/replay snapshots get the synthetic fixture and NEVER touch real state, even if the env var is set.
    The legacy ledger source has no T3 metadata and nothing to report here."""
    now = now or datetime.now(UTC)
    t3 = ((activity or {}).get("meta") or {}).get("t3")
    if not isinstance(t3, dict):
        return None
    if t3.get("mode") == "demo":
        return demo_automation(now)
    return build_automation(state_dir_from_env(env), now)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Print the automation document for an Agent Control state directory (read-only).")
    ap.add_argument("--state-dir", type=Path, default=state_dir_from_env())
    args = ap.parse_args(argv)
    doc = build_automation(args.state_dir)
    if doc is None:
        print(f"no state directory: pass --state-dir or set {ENV_STATE_DIR}", file=sys.stderr)
        return 2
    print(json.dumps(doc, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
