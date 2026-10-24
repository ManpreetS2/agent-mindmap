"""Summary text for quota pools: numbers only when measured; expired readings are labelled; legacy shape still works."""
from tools.export_observability import quota_line


def test_unknown_has_no_numbers():
    assert quota_line("claude-1", {"status": "UNKNOWN", "note": "x"}) == "- claude-1: UNKNOWN"


def test_unsupported_and_error_never_print_question_mark_percentages():
    line = quota_line("cursor-premium", {"status": "UNSUPPORTED", "note": "usage visible in UI only", "source": "cursor-agent about"})
    assert "?%" not in line and "no usage values" in line
    assert "?%" not in quota_line("claude-2", {"status": "ERROR", "note": "not signed in"})


def test_verified_windows_and_stale_label():
    pool = {"status": "VERIFIED", "windows": [{"type": "session", "label": "5-hour", "used_pct": 18.0},
                                               {"type": "weekly", "label": "7-day", "used_pct": 33.0}],
            "source": "codex app-server", "observed_at": "2026-10-24T06:51:07+00:00"}
    line = quota_line("codex", pool)
    assert "5-hour 18% used" in line and "7-day 33% used" in line and "EXPIRED" not in line
    assert "EXPIRED reading" in quota_line("codex", {**pool, "status": "STALE"})


def test_legacy_manual_shape_still_renders():
    line = quota_line("claude-1", {"status": "MANUAL", "five_hour_used_pct": 40.0, "weekly_used_pct": 12.0, "source": "manual"})
    assert "5h 40% used" in line and "weekly 12% used" in line
