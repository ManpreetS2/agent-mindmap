"""/automation.json: read-only taskbot job records with truthful states, redaction, and demo/real separation.

The SQLite files are built here from Agent Control's table shapes (bin/agentlib.py events, bin/taskbot tickets/runs),
filled with synthetic rows. Nothing reads a real state directory, a network, or a model.
"""
import json
import re
import sqlite3
import threading
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from jsonschema import Draft7Validator

from ingest.live import MindmapHandler
from tools import taskbot_activity as ta

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schema/automation.schema.json").read_text())
NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
REPO = "example/demo-app"
PRIVATE = re.compile(r"/Users/|/home/|\.t3|\.config|@[A-Za-z0-9.-]+\.[a-z]{2,}|Bearer |sk-[A-Za-z0-9]|gh[pousr]_", re.I)

# Mirrors of Agent Control's DDL. If the real columns change, this and the reader change together.
EVENTS_DDL = """CREATE TABLE events(id INTEGER PRIMARY KEY, time TEXT NOT NULL, bot TEXT NOT NULL, run_id TEXT, repo TEXT,
  item TEXT, type TEXT NOT NULL, severity TEXT NOT NULL DEFAULT 'info', account TEXT, message TEXT, url TEXT)"""
TASKBOT_DDL = """
CREATE TABLE tickets(key TEXT PRIMARY KEY, repo TEXT, number INTEGER, title TEXT, status TEXT, attempts INTEGER DEFAULT 0,
  infra_retries INTEGER DEFAULT 0, last_model TEXT, wait_until TEXT, branch TEXT, pr_url TEXT, worktree TEXT, note TEXT,
  updated_at TEXT, pr_fixes INTEGER DEFAULT 0, fix_kind TEXT, stack_base TEXT, assigned TEXT);
CREATE TABLE runs(id INTEGER PRIMARY KEY AUTOINCREMENT, ticket TEXT, started TEXT, ended TEXT, account TEXT, model TEXT,
  effort TEXT, outcome TEXT, detail TEXT, log_path TEXT, counted INTEGER DEFAULT 0, agent_seconds REAL, usage_json TEXT,
  run_id TEXT)"""


def valid(doc):
    errors = list(Draft7Validator(SCHEMA).iter_errors(doc))
    assert not errors, errors[0].message
    assert not PRIVATE.search(json.dumps(doc))


def iso(minutes_ago: float) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).isoformat(timespec="seconds")


class State:
    """A throwaway Agent Control state directory."""

    def __init__(self, tmp: Path):
        self.dir = tmp / "state"
        self.dir.mkdir()
        self.tb = sqlite3.connect(self.dir / "taskbot.sqlite")
        self.ev = sqlite3.connect(self.dir / "events.sqlite")
        self.tb.executescript(TASKBOT_DDL)
        self.ev.execute(EVENTS_DDL)

    def ticket(self, number, status, *, updated=5, title="Fix the example", pr_url=None, wait_until=None, note=None, attempts=0):
        self.tb.execute("INSERT INTO tickets(key,repo,number,title,status,attempts,wait_until,pr_url,note,updated_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (f"{REPO}#{number}", REPO, number, title, status, attempts, wait_until, pr_url, note, iso(updated)))

    def event(self, number, type, minutes_ago, *, run_id="taskbot-20261025-110000-aaaaaa", severity="info", message="",
              account="personal", bot="taskbot"):
        self.ev.execute("INSERT INTO events(time,bot,run_id,repo,item,type,severity,account,message) VALUES(?,?,?,?,?,?,?,?,?)",
                        (iso(minutes_ago), bot, run_id, REPO, f"#{number}", type, severity, account, message))

    def run_record(self, number, minutes_ago, model="gpt-6-luna", effort="low", outcome=None,
                   run_id="taskbot-20261025-110000-aaaaaa"):
        self.tb.execute("INSERT INTO runs(ticket,started,account,model,effort,outcome,run_id) VALUES(?,?,?,?,?,?,?)",
                        (f"{REPO}#{number}", iso(minutes_ago), "personal", model, effort, outcome, run_id))

    def commit(self):
        self.tb.commit(); self.ev.commit()
        self.tb.close(); self.ev.close()
        return self.dir


@pytest.fixture
def st(tmp_path):
    return State(tmp_path)


def build(state: State, now=NOW):
    doc = ta.build_automation(state.commit(), now)
    valid(doc)
    return doc


def only(doc):
    assert len(doc["tasks"]) == 1
    return doc["tasks"][0]


# ---- source availability ------------------------------------------------------------------------------------------

def test_unconfigured_is_none_and_never_guessed():
    assert ta.build_automation(None, NOW) is None
    assert ta.state_dir_from_env({}) is None
    assert ta.state_dir_from_env({ta.ENV_STATE_DIR: "/somewhere"}) == Path("/somewhere")


def test_missing_databases_are_absent_not_empty_success(tmp_path):
    doc = ta.build_automation(tmp_path, NOW)
    valid(doc)
    assert doc["source"]["status"] == "absent" and doc["tasks"] == []
    assert list(tmp_path.iterdir()) == []  # nothing was created


def test_unreadable_and_unsupported_schema_are_reported(tmp_path):
    (tmp_path / "taskbot.sqlite").write_bytes(b"not a database at all, just text" * 10)
    (tmp_path / "events.sqlite").write_bytes(b"not a database at all, just text" * 10)
    doc = ta.build_automation(tmp_path, NOW)
    valid(doc)
    assert doc["source"]["status"] in ("unreadable", "unsupported_schema") and doc["tasks"] == []
    other = tmp_path / "x"
    other.mkdir()
    sqlite3.connect(other / "taskbot.sqlite").close()
    sqlite3.connect(other / "events.sqlite").close()
    doc = ta.build_automation(other, NOW)
    assert doc["source"]["status"] == "unsupported_schema"


def test_tickets_with_no_events_table_yet_are_queued_not_unsupported(st, tmp_path):
    st.ticket(1, "queued")
    d = st.dir
    st.tb.commit(); st.tb.close()
    st.ev.execute("DROP TABLE events"); st.ev.commit(); st.ev.close()  # events.sqlite exists but is still empty
    doc = ta.build_automation(d, NOW)
    valid(doc)
    assert doc["source"]["status"] == "connected" and doc["source"]["last_event_at"] is None
    assert only(doc)["state"] == "queued"


def test_reading_never_modifies_the_databases(st):
    st.ticket(1, "queued")
    st.event(1, "run_start", 3, message="job (attempt 1) with m low: t")
    d = st.commit()
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in d.iterdir()}
    ta.build_automation(d, NOW)
    assert {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in d.iterdir()} == before
    con = ta._open_ro(d / "taskbot.sqlite")
    with pytest.raises(sqlite3.OperationalError):
        con.execute("DELETE FROM tickets")
    con.close()


# ---- state mapping ------------------------------------------------------------------------------------------------

def test_queued_has_no_assignment_and_no_run(st):
    st.ticket(1, "queued")
    t = only(build(st))
    assert t["state"] == "queued" and t["current_run"] is None
    assert t["assignment"] == {"account": None, "model": None, "effort": None, "known": False, "source": "none"}


def test_running_requires_a_recent_run_start_without_run_end(st):
    st.ticket(1, "running")
    st.event(1, "run_start", 2, message="job (attempt 1) with gpt-6-luna low: Fix the example")
    st.run_record(1, 1.9, model="gpt-6-luna")
    t = only(build(st))
    assert t["state"] == "running" and "last event" in t["state_basis"]
    assert t["current_run"]["run_id"] == "taskbot-20261025-110000-aaaaaa" and t["current_run"]["ended_at"] is None
    assert t["assignment"] == {"account": "personal", "model": "gpt-6-luna", "effort": "low", "known": True, "source": "run_record"}


def test_an_earlier_attempts_run_record_is_never_attributed_to_the_latest_run(st):
    st.ticket(1, "running")
    st.run_record(1, 90, model="old-model", run_id="taskbot-OLD")                 # attempt 1, different run id
    st.event(1, "run_start", 2, run_id="taskbot-NEW", message="something this reader does not recognise")
    a = only(build(st))["assignment"]
    assert a["model"] is None and a["known"] is False and a["source"] == "none"


def test_model_falls_back_to_run_start_text_then_to_unknown(st):
    st.ticket(1, "running"); st.ticket(2, "running")
    st.event(1, "run_start", 2, run_id="r1", message="job (attempt 1) with gpt-6-luna low: Fix the example")
    st.event(2, "run_start", 2, run_id="r2", message="something this reader does not recognise")
    by = {t["issue"]["number"]: t for t in build(st)["tasks"]}
    assert by[1]["assignment"]["source"] == "event_message" and by[1]["assignment"]["model"] == "gpt-6-luna"
    assert by[2]["assignment"] == {"account": "personal", "model": None, "effort": None, "known": False, "source": "none"}


def test_a_running_ticket_with_an_old_last_event_is_unknown_not_running(st):
    st.ticket(1, "running")
    st.event(1, "run_start", 47)
    t = only(build(st))
    assert t["state"] == "unknown" and "47 min" in t["state_basis"] and "crashed" in t["state_basis"]


def test_a_running_ticket_whose_run_already_ended_is_unknown(st):
    st.ticket(1, "running")
    st.event(1, "run_start", 6); st.event(1, "run_end", 1, message="verify_failed", severity="warning")
    t = only(build(st))
    assert t["state"] == "unknown" and "already ended" in t["state_basis"]


def test_a_running_ticket_with_no_events_at_all_is_unknown(st):
    st.ticket(1, "running")
    t = only(build(st))
    assert t["state"] == "unknown" and t["current_run"] is None and t["assignment"]["known"] is False


def test_future_wait_is_blocked_and_past_wait_is_queued(st):
    st.ticket(1, "queued", wait_until=(NOW + timedelta(hours=1)).isoformat(), note="no usable account")
    st.ticket(2, "queued", wait_until=(NOW - timedelta(hours=1)).isoformat())
    by = {t["issue"]["number"]: t for t in build(st)["tasks"]}
    assert by[1]["state"] == "blocked" and by[1]["next_attempt_after"] and "no usable account" in by[1]["state_basis"]
    assert by[2]["state"] == "queued" and by[2]["next_attempt_after"] is None


def test_pr_open_is_completed_with_the_draft_pr_link_and_not_merged(st):
    st.ticket(1, "pr_open", pr_url=f"https://github.com/{REPO}/pull/21", attempts=1)
    st.event(1, "run_start", 20, message="job (attempt 1) with gpt-6-luna low: t")
    st.event(1, "pr_opened", 10)
    st.event(1, "run_end", 10, message="pr_opened")
    t = only(build(st))
    assert t["state"] == "completed" and t["pull_request_url"] == f"https://github.com/{REPO}/pull/21"
    assert "not merged" in t["state_basis"] and t["current_run"]["outcome"] == "pr_opened"
    assert t["current_run"]["duration_sec"] == 600


def test_non_github_pr_urls_are_dropped(st):
    st.ticket(1, "pr_open", pr_url="javascript:alert(1)")
    st.ticket(2, "pr_open", pr_url="https://evil.example/pull/1")
    assert all(t["pull_request_url"] is None for t in build(st)["tasks"])


def test_a_long_mixed_case_repo_name_is_not_mistaken_for_a_credential(st, monkeypatch):
    """Real shape from the first Mac dry-run: owner/repo with 24+ characters, mixed case and a digit looked like a token
    to the generic blob heuristic and was shown as "[redacted]"."""
    repo = "ManpreetS2/agent-mindmap"
    monkeypatch.setitem(globals(), "REPO", repo)
    st.ticket(42, "queued", attempts=1, note="agent_cannot: the required web test suite still fails")
    st.event(42, "run_start", 6, message="job (attempt 1) with gpt-6-luna low: Fix the example")
    st.event(42, "run_end", 3, severity="warning", message="agent_cannot")
    st.run_record(42, 6, outcome="agent_cannot")
    t = only(build(st))
    assert t["repo"] == repo and t["id"] == f"taskbot:{repo}#42"
    assert t["issue"]["url"] == f"https://github.com/{repo}/issues/42"
    # An attempt that ended agent_cannot and was re-queued is a queued job with a finished attempt, not a completed one.
    assert t["state"] == "queued" and t["pull_request_url"] is None
    assert t["current_run"]["outcome"] == "agent_cannot" and t["current_run"]["ended_at"] is not None
    assert t["assignment"]["model"] == "gpt-6-luna" and t["assignment"]["source"] == "run_record"


def test_dry_run_is_completed_without_a_pr(st):
    st.ticket(1, "dry_run_done", pr_url=f"https://github.com/{REPO}/pull/9")
    t = only(build(st))
    assert t["state"] == "completed" and t["pull_request_url"] is None and "nothing was pushed" in t["state_basis"]


def test_failed_carries_redacted_one_line_error_evidence_never_the_raw_message(st):
    st.ticket(1, "failed", attempts=2)
    leak = "ghp_" + "a" * 36  # assembled so no token-shaped literal is committed
    st.event(1, "agent_failed", 3, severity="error",
             message=f"gave up after 2 attempts. Last: verify_failed with m: `npm test` failed:\nTOKEN={leak}\n/Users/someone/work/app/file.ts:1")
    t = only(build(st))
    assert t["state"] == "failed" and t["error_evidence"]["severity"] == "error"
    assert "gave up after 2 attempts" in t["error_evidence"]["summary"]
    assert "\n" not in t["error_evidence"]["summary"]
    dumped = json.dumps(t)
    assert leak not in dumped and "/Users/someone" not in dumped and "TOKEN=" not in dumped


def test_credential_or_path_in_the_first_line_is_replaced_entirely(st):
    st.ticket(1, "failed", note="x")
    st.event(1, "agent_failed", 3, severity="error", message="failed in /Users/someone/work/app")
    ev = only(build(st))["error_evidence"]
    assert ev["summary"] == "[redacted path]"


def test_issue_titles_are_redacted_like_t3_titles(st):
    st.ticket(1, "queued", title="Fix /Users/someone/private/thing")
    assert only(build(st))["issue"]["title"] == "[redacted path]"


def test_unrecognised_status_is_unknown(st):
    st.ticket(1, "teleporting")
    t = only(build(st))
    assert t["state"] == "unknown" and "unrecognized" in t["state_basis"]


def test_other_bots_events_and_other_tickets_do_not_leak_into_a_task(st):
    st.ticket(1, "running"); st.ticket(2, "queued")
    st.event(1, "run_start", 2, run_id="r1")
    st.event(2, "run_start", 1, run_id="rX", bot="depbot")  # depbot is not taskbot
    by = {t["issue"]["number"]: t for t in build(st)["tasks"]}
    assert by[2]["current_run"] is None and by[1]["current_run"]["run_id"] == "r1"


def test_old_terminal_tickets_are_dropped_and_active_ones_first(st):
    st.ticket(1, "pr_open", updated=60 * 24 * 30)      # a month old: dropped
    st.ticket(2, "completed_like", updated=5)           # unknown-status recent
    st.ticket(3, "queued", updated=60 * 24 * 30)        # old but still active: kept
    st.ticket(4, "failed", updated=10)
    st.ticket(5, "running", updated=1); st.event(5, "run_start", 1)
    order = [t["issue"]["number"] for t in build(st)["tasks"]]
    assert 1 not in order and order == [5, 3, 4, 2]


def test_no_edges_and_notes_state_the_provenance_limits(st):
    st.ticket(1, "pr_open", pr_url=f"https://github.com/{REPO}/pull/21")
    doc = build(st)
    assert "edges" not in doc and "delegations" not in doc
    text = " ".join(doc["notes"])
    assert "not T3 sessions" in text and "does not show that one model delegated" in text


# ---- demo / real separation + HTTP --------------------------------------------------------------------------------

def test_demo_fixture_is_valid_demo_and_shifted_to_now():
    doc = ta.demo_automation(NOW)
    valid(doc)
    assert doc["mode"] == "demo" and doc["generated_at"].startswith("2026-10-25T12:00")
    assert {t["state"] for t in doc["tasks"]} >= {"running", "queued", "blocked", "failed", "completed", "unknown"}
    assert any("SYNTHETIC" in n for n in doc["notes"])


def test_demo_snapshot_never_reads_real_state_even_when_configured(st):
    st.ticket(1, "queued", title="REAL TICKET")
    d = st.commit()
    doc = ta.automation_for_activity({"meta": {"t3": {"mode": "demo"}}}, NOW, env={ta.ENV_STATE_DIR: str(d)})
    assert doc["mode"] == "demo" and "REAL TICKET" not in json.dumps(doc)


def test_live_snapshot_reads_configured_state_and_legacy_source_has_nothing(st):
    st.ticket(1, "queued", title="Real ticket")
    d = st.commit()
    live = ta.automation_for_activity({"meta": {"t3": {"mode": "live"}}}, NOW, env={ta.ENV_STATE_DIR: str(d)})
    assert live["mode"] == "live" and live["tasks"][0]["issue"]["title"] == "Real ticket"
    assert ta.automation_for_activity({"meta": {"t3": {"mode": "live"}}}, NOW, env={}) is None
    assert ta.automation_for_activity({"meta": {"github": "ok"}}, NOW, env={ta.ENV_STATE_DIR: str(d)}) is None
    assert ta.automation_for_activity(None, NOW, env={ta.ENV_STATE_DIR: str(d)}) is None


class FakeDaemon:
    def __init__(self, body, tmp):
        self.body, self.activity_path = body, tmp / "activity.json"

    def activity_body(self):
        return self.body

    def health(self):
        return NS(to_json=lambda: {})


def serve(body, tmp_path):
    handler = type("H", (MindmapHandler,), {"daemon": FakeDaemon(body, tmp_path), "static_dir": tmp_path})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def get(server, path):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}{path}", timeout=5) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, b""


def test_http_route(tmp_path, monkeypatch, st):
    st.ticket(1, "queued")
    d = st.commit()
    monkeypatch.delenv(ta.ENV_STATE_DIR, raising=False)
    live = serve(json.dumps({"meta": {"t3": {"mode": "live"}}}).encode(), tmp_path)
    demo = serve(json.dumps({"meta": {"t3": {"mode": "demo"}}}).encode(), tmp_path)
    try:
        assert get(live, "/automation.json")[0] == 404  # not configured -> nothing claimed
        monkeypatch.setenv(ta.ENV_STATE_DIR, str(d))
        status, headers, body = get(live, "/automation.json")
        assert status == 200 and headers["Cache-Control"] == "no-store"
        doc = json.loads(body); valid(doc)
        assert doc["mode"] == "live" and doc["tasks"][0]["state"] == "queued"
        status, _h, body = get(demo, "/automation.json")
        assert status == 200 and json.loads(body)["mode"] == "demo"
    finally:
        live.shutdown(); demo.shutdown()


def test_open_ro_never_creates_a_missing_database(tmp_path):
    with pytest.raises(sqlite3.OperationalError):
        ta._open_ro(tmp_path / "nope.sqlite")
    assert list(tmp_path.iterdir()) == []
