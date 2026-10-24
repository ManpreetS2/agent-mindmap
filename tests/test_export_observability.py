"""Regression tests for the private, opt-in observability export."""
import json
from datetime import UTC, datetime

import pytest

from ingest.t3 import T3Projection, read_demo
from tools.export_observability import ROOT, make_feed, write_private


def live_snapshot(now):
    raw = read_demo()
    for thread in raw["threads"]:
        thread["updatedAt"] = now.isoformat()
        thread["createdAt"] = now.isoformat()
    return T3Projection("test-source", demo=False).snapshot(raw, now.timestamp())


def test_live_export_is_allowlisted_and_has_honest_quota_state():
    now = datetime(2026, 10, 23, 20, 0, tzinfo=UTC)
    feed, summary = make_feed(live_snapshot(now), now=now)
    assert feed["freshness"] == "fresh"
    assert feed["quota"]["status"] == "unsupported"
    assert feed["sessions"]
    assert any(edge["from"] != edge["to"] for edge in feed["delegations"])
    assert "T3 exposes no usage" in summary
    assert all(p["status"] == "UNKNOWN" for p in feed["quota"]["pools"].values())
    assert "thread_id" not in json.dumps(feed)
    assert "source_links" not in json.dumps(feed)
    assert "T3 read-only metadata" == feed["source"]


def test_demo_is_rejected_and_disconnection_is_stale():
    now = datetime(2026, 10, 23, 20, 0, tzinfo=UTC)
    snapshot = live_snapshot(now)
    snapshot["meta"]["t3"]["mode"] = "demo"
    with pytest.raises(ValueError, match="Only real T3"):
        make_feed(snapshot, now=now)
    snapshot["meta"]["t3"]["mode"] = "live"
    snapshot["meta"]["t3"]["connection"] = "unavailable"
    feed, _ = make_feed(snapshot, now=now)
    assert feed["freshness"] == "stale"
    assert all(s["stale"] for s in feed["sessions"])


def test_sensitive_titles_do_not_escape():
    now = datetime(2026, 10, 23, 20, 0, tzinfo=UTC)
    raw = read_demo()
    raw["threads"][0]["title"] = "Authorization: Bearer abc123xyz456SECRET"
    for thread in raw["threads"]:
        thread["updatedAt"] = now.isoformat()
    snapshot = T3Projection("test-source", demo=False).snapshot(raw, now.timestamp())
    feed, summary = make_feed(snapshot, now=now)
    assert "abc123xyz456SECRET" not in json.dumps(feed)
    assert "abc123xyz456SECRET" not in summary
    assert "[redacted]" in summary


def test_export_is_private_and_never_written_to_public_repository(tmp_path):
    directory = tmp_path / "snapshots"
    write_private(directory, "summary.md", "test\n")
    assert (directory / "summary.md").read_text() == "test\n"
    assert directory.stat().st_mode & 0o077 == 0
    assert (directory / "summary.md").stat().st_mode & 0o077 == 0
    with pytest.raises(ValueError, match="PUBLIC"):
        write_private(ROOT, "must-not-exist.md", "secret")
    assert not (ROOT / "must-not-exist.md").exists()


def test_quota_pools_are_separate_sourced_and_never_invented(tmp_path):
    from tools.export_observability import load_quota_pools
    now = datetime(2026, 10, 23, 20, 0, tzinfo=UTC)
    assert {p["status"] for p in load_quota_pools(tmp_path / "missing.json", now=now).values()} == {"UNKNOWN"}
    f = tmp_path / "q.json"
    f.write_text(json.dumps({"pools": {
        "claude-1": {"source": "manual: claude.ai usage page", "observed_at": "2026-10-23T19:00:00+00:00",
                     "five_hour_used_pct": 40, "weekly_used_pct": 12.5},
        "claude-2": {"source": "manual", "observed_at": "2026-10-20T19:00:00+00:00", "weekly_used_pct": 90},
        "codex": {"source": "manual", "observed_at": "2026-10-23T19:00:00+00:00", "five_hour_used_pct": 140},
        "cursor-premium": {"observed_at": "2026-10-23T19:00:00+00:00", "weekly_used_pct": 5},
        "devin-free": {"source": "manual", "observed_at": "2027-01-01T00:00:00+00:00", "weekly_used_pct": 5},
        "unlisted": {"source": "manual", "observed_at": "2026-10-23T19:00:00+00:00", "weekly_used_pct": 1},
    }}))
    pools = load_quota_pools(f, now=now)
    assert pools["claude-1"]["status"] == "MANUAL" and pools["claude-1"]["weekly_used_pct"] == 12.5
    assert pools["claude-2"]["status"] == "STALE_MANUAL"
    assert pools["claude-1"] != pools["claude-2"] and "combined" not in json.dumps(pools)
    assert pools["codex"]["status"] == "UNKNOWN"            # out-of-range percentage
    assert pools["cursor-premium"]["status"] == "UNKNOWN"   # no source
    assert pools["devin-free"]["status"] == "UNKNOWN"       # timestamp from the future
    assert "unlisted" not in pools
