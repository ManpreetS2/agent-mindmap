"""Private feed: per-session account label, additive machine/publisher objects, privacy."""
import copy
from datetime import UTC, datetime

from ingest.t3 import T3Projection, read_demo
from tools.export_observability import make_feed

NOW = datetime(2026, 10, 22, 20, 0, 5, tzinfo=UTC)


def _live_activity(accounts):
    raw = read_demo()
    base = raw["threads"][0]
    raw["providers"] = [{"providerInstanceId": i, "driverKind": "claudeAgent", "displayName": l} for i, l in accounts.items()]
    raw["threads"] = [{**copy.deepcopy(base), "threadId": f"thread-{n}", "providerInstanceId": i, "parentThreadId": None}
                      for n, i in enumerate(accounts)]
    activity = T3Projection("local", demo=False).snapshot(raw, int(NOW.timestamp()))
    return activity


def test_sessions_carry_account_labels_so_two_claudes_are_distinguishable():
    feed, summary = make_feed(_live_activity({"claudeAgent": "Claude", "claudeAgent_2": "Claude2"}), now=NOW, quota_pools={})
    assert {s["account"] for s in feed["sessions"]} == {"Claude", "Claude2"}
    assert {s["provider"] for s in feed["sessions"]} == {"Claude Code"}


def test_missing_account_is_unknown_not_guessed():
    activity = _live_activity({"claudeAgent": "Claude"})
    activity["nodes"][0]["session"]["account"] = None
    feed, _ = make_feed(activity, now=NOW, quota_pools={})
    assert feed["sessions"][0]["account"] == "UNKNOWN"


def test_machine_and_publisher_are_additive_and_sanitised():
    machine = {"id": "mac-3f9a21c4", "label": "Mac B", "role": "publisher", "hostname": "JsMacbookpro", "user": "manpreet"}
    publisher = {"machine_id": "mac-3f9a21c4", "label": "Mac B", "epoch": 3, "lease_expires_at": NOW.isoformat(), "state": "active"}
    feed, summary = make_feed(_live_activity({"claudeAgent": "Claude"}), now=NOW, quota_pools={}, machine=machine, publisher=publisher)
    assert feed["machine"] == {"id": "mac-3f9a21c4", "label": "Mac B", "role": "publisher"}  # extra keys dropped
    assert feed["publisher"]["epoch"] == 3
    text = str(feed) + summary
    assert "JsMacbookpro" not in text and "manpreet" not in text
    plain, _ = make_feed(_live_activity({"claudeAgent": "Claude"}), now=NOW, quota_pools={})
    assert "machine" not in plain and "publisher" not in plain  # the existing feed contract is unchanged when not supplied
    assert feed["format"] == "agent-mindmap-private-feed/v1"
