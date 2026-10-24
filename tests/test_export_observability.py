"""Regression tests for the private, opt-in observability export."""
import json
from datetime import UTC, datetime
from pathlib import Path

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
    assert "Quota: UNSUPPORTED" in summary
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
