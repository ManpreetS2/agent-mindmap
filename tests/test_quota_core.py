import json
import math
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from tools.quota import api, normalize as N, store
from tools.quota.collectors import manual
from tools.quota.models import POOL_ORDER, QuotaError

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schema/observability.schema.json").read_text())
NOW = datetime(2026, 10, 24, 7, 0, tzinfo=UTC)


def validate_pool(pool):
    Draft202012Validator({**SCHEMA["definitions"]["pool"], "definitions": SCHEMA["definitions"]},
                         format_checker=Draft202012Validator.FORMAT_CHECKER).validate(pool)


def live(alias="codex", kind="codex-app-server", observed=NOW, windows=None, **kw):
    windows = windows if windows is not None else [
        N.make_window("session", "5-hour", 300, 10, NOW + timedelta(hours=3)),
        N.make_window("weekly", "7-day", 10080, 30, NOW + timedelta(days=3))]
    return N.make_reading(alias, kind, "m", observed, windows=windows, **kw)


def test_parse_and_epoch_rules():
    assert N.parse_ts("2026-10-24T07:00:00Z") == NOW
    for bad in ("2026-10-24T07:00:00", "garbage", 5, None, "", "x" * 50):
        assert N.parse_ts(bad) is None
    assert N.epoch_to_dt(1_792_000_000).tzinfo is not None
    for bad in (True, math.nan, math.inf, -1, 0, 10**12, "5", None):
        assert N.epoch_to_dt(bad) is None


@pytest.mark.parametrize("bad", [-1, 100.1, math.nan, math.inf, True, "5", None])
def test_pct_rejects_out_of_range(bad):
    assert N.pct(bad) is None
    with pytest.raises(QuotaError):
        N.make_window("session", "x", 300, bad, None)


def test_duplicate_windows_rejected():
    w = N.make_window("session", "5-hour", 300, 1, None)
    with pytest.raises(QuotaError):
        N.make_reading("codex", "codex-app-server", "m", NOW, windows=[w, dict(w)])


def test_fresh_verified_then_stale_then_dropped(tmp_path):
    store.write("codex", live(), "live", tmp_path)
    p = api.pools(NOW + timedelta(minutes=5), tmp_path)[4]
    validate_pool(p)
    assert p["status"] == "VERIFIED" and p["expires_at"] == "2026-10-24T07:15:00+00:00"
    assert p["windows"][0]["remaining_pct"] == 90
    s = api.pools(NOW + timedelta(minutes=16), tmp_path)[4]
    validate_pool(s)
    assert s["status"] == "STALE" and len(s["windows"]) == 2  # kept as history
    after = api.pools(NOW + timedelta(hours=4), tmp_path)[4]
    assert after["status"] == "STALE" and [w["type"] for w in after["windows"]] == ["weekly"]  # session reset: dropped


def test_expiry_clamped_to_resets_at(tmp_path):
    r = live(windows=[N.make_window("session", "5-hour", 300, 1, NOW + timedelta(minutes=5))])
    store.write("codex", r, "live", tmp_path)
    p = api.pools(NOW, tmp_path)[4]
    assert p["expires_at"] == "2026-10-24T07:05:00+00:00"
    assert api.pools(NOW + timedelta(minutes=6), tmp_path)[4]["status"] == "STALE"


def test_future_observed_at_rejected(tmp_path):
    store.write("codex", live(observed=NOW + timedelta(minutes=10)), "live", tmp_path)
    p = api.pools(NOW, tmp_path)[4]
    assert p["status"] == "UNKNOWN" and p["windows"] == []
    store.write("codex", live(observed=NOW + timedelta(seconds=30)), "live", tmp_path)
    assert api.pools(NOW, tmp_path)[4]["status"] == "VERIFIED"


def test_malformed_stored_reading_is_unknown(tmp_path):
    path = store.write("codex", live(), "live", tmp_path)
    data = json.loads(path.read_text())
    data["windows"][0]["used_pct"] = 500
    path.write_text(json.dumps(data))
    p = api.pools(NOW, tmp_path)[4]
    validate_pool(p)
    assert p["status"] == "UNKNOWN" and "rejected" in p["reason"]
    data["windows"][0]["used_pct"] = 5
    data["observed_at"] = "not a time"
    path.write_text(json.dumps(data))
    assert api.pools(NOW, tmp_path)[4]["status"] == "UNKNOWN"
    path.write_text("{not json")
    assert api.pools(NOW, tmp_path)[4]["status"] == "UNKNOWN"


def test_exactly_five_pools_in_order_all_states_validate(tmp_path):
    pools = api.pools(NOW, tmp_path)
    assert [p["id"] for p in pools] == list(POOL_ORDER)
    store.write("codex", N.make_reading("codex", "codex-app-server", "m", NOW, "error", reason="boom"), "live", tmp_path)
    store.write("cursor-premium", N.make_reading("cursor-premium", "cursor-cli", "m", NOW, "unsupported",
                                                 plan="Premium", reason="ui only"), "live", tmp_path)
    store.write("claude-1", live("claude-1", "claude-statusline"), "live", tmp_path)
    pools = api.pools(NOW, tmp_path)
    for p in pools:
        validate_pool(p)
    by = {p["id"]: p for p in pools}
    assert by["codex"]["status"] == "ERROR" and by["codex"]["windows"] == []
    assert by["cursor-premium"]["status"] == "UNSUPPORTED" and by["cursor-premium"]["plan"] == "premium"
    assert by["claude-1"]["status"] == "VERIFIED" and by["claude-2"]["status"] == "UNKNOWN"


def test_two_claude_accounts_do_not_contaminate(tmp_path):
    a = live("claude-1", "claude-statusline", windows=[N.make_window("session", "5-hour", 300, 11, None)])
    b = live("claude-2", "claude-statusline", windows=[N.make_window("session", "5-hour", 300, 77, None)])
    store.write("claude-1", a, "live", tmp_path)
    store.write("claude-2", b, "live", tmp_path)
    by = {p["id"]: p for p in api.pools(NOW, tmp_path)}
    assert by["claude-1"]["windows"][0]["used_pct"] == 11 and by["claude-2"]["windows"][0]["used_pct"] == 77
    assert {f.name for f in tmp_path.iterdir()} == {"claude-1.json", "claude-2.json"}


def test_alias_mismatch_rejected_on_write_and_read(tmp_path):
    with pytest.raises(QuotaError):
        store.write("claude-2", live("claude-1", "claude-statusline"), "live", tmp_path)
    assert not list(tmp_path.iterdir())
    store.write("claude-1", live("claude-1", "claude-statusline"), "live", tmp_path)
    (tmp_path / "claude-1.json").rename(tmp_path / "claude-2.json")  # file swapped between accounts
    assert store.read("claude-2", "live", tmp_path) is None
    assert api.pools(NOW, tmp_path)[1]["status"] == "UNKNOWN"


def test_store_permissions_and_secret_stripping_with_spaces(tmp_path):
    d = tmp_path / "state dir with spaces"
    r = live()
    r["accountId"] = "acct-secret"
    r["email"] = "x@example.com"
    r["windows"][0]["token"] = "t"
    path = store.write("codex", r, "live", d)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(d).st_mode) == 0o700
    text = path.read_text()
    assert "acct-secret" not in text and "example.com" not in text and '"token"' not in text
    assert not [f for f in d.iterdir() if f.name.startswith(".")]  # no temp leftovers


def test_env_state_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_MINDMAP_QUOTA_DIR", str(tmp_path / "e"))
    store.write("codex", live(), "live")
    assert (tmp_path / "e" / "codex.json").exists()
    assert api.pools(NOW)[4]["status"] == "VERIFIED"


def test_manual_validation_and_ttl(tmp_path):
    kw = dict(source="Devin UI", observed_at="2026-10-24T06:00:00Z", state_dir=tmp_path, now=NOW)
    manual.set_window("devin-free", "weekly", 20, "2026-10-30T00:00:00Z", **kw)
    p = api.pools(NOW, tmp_path)[3]
    validate_pool(p)
    assert p["status"] == "MANUAL" and p["windows"][0]["used_pct"] == 20 and p["source"]["kind"] == "manual"
    assert api.pools(NOW + timedelta(hours=25), tmp_path)[3]["status"] == "STALE"
    for bad in (dict(used_pct="abc"), dict(used_pct=101), dict(used_pct="nan"), dict(used_pct=-1),
                dict(resets_at="2020-01-01T00:00:00Z"), dict(resets_at="soon"), dict(source=""),
                dict(source="[fill me]"), dict(observed_at="2026-10-25T00:00:00Z"), dict(observed_at="yesterday"),
                dict(window="daily"), dict(pool="nope")):
        args = dict(pool="devin-free", window="weekly", used_pct=5, resets_at=None, **kw)
        args.update(bad)
        pool, window, used = args.pop("pool"), args.pop("window"), args.pop("used_pct")
        resets = args.pop("resets_at")
        with pytest.raises(QuotaError):
            manual.set_window(pool, window, used, resets, args.pop("source"), args.pop("observed_at"), **args)


def test_manual_windows_merge_oldest_governs_and_clear(tmp_path):
    kw = dict(source="UI", state_dir=tmp_path, now=NOW)
    manual.set_window("devin-free", "weekly", 20, None, observed_at="2026-10-23T08:00:00Z", **kw)
    manual.set_window("devin-free", "session", 5, None, observed_at="2026-10-24T06:30:00Z", **kw)
    p = api.pools(NOW, tmp_path)[3]
    assert {w["type"] for w in p["windows"]} == {"session", "weekly"}
    assert p["expires_at"] == "2026-10-24T08:00:00+00:00"  # weekly entry is 23h old
    assert manual.clear("devin-free", tmp_path) and api.pools(NOW, tmp_path)[3]["status"] == "UNKNOWN"


def test_manual_beats_unsupported_cursor_and_keeps_plan(tmp_path):
    store.write("cursor-premium", N.make_reading("cursor-premium", "cursor-cli", "m", NOW, "unsupported",
                                                 plan="Premium", reason="ui only"), "live", tmp_path)
    manual.set_window("cursor-premium", "monthly", 40, None, "Cursor UI", "2026-10-24T06:00:00Z",
                      state_dir=tmp_path, now=NOW)
    p = api.pools(NOW, tmp_path)[2]
    validate_pool(p)
    assert p["status"] == "MANUAL" and p["plan"] == "premium" and p["windows"][0]["type"] == "monthly"


def test_to_feed_pools_backward_compatible(tmp_path):
    store.write("codex", live(), "live", tmp_path)
    feed = api.to_feed_pools(api.pools(NOW, tmp_path))
    assert list(feed) == list(POOL_ORDER)
    c = feed["codex"]
    assert c["five_hour_used_pct"] == 10 and c["weekly_used_pct"] == 30 and c["status"] == "VERIFIED"
    assert {"source", "observed_at", "note", "windows"} <= set(c)
    assert "five_hour_used_pct" not in feed["claude-1"] and feed["claude-1"]["status"] == "UNKNOWN"
    json.dumps(feed)


def test_fixture_pools_validate():
    for f in (ROOT / "fixtures/observability").glob("*.json"):
        for p in json.loads(f.read_text())["quota"]["pools"]:
            validate_pool(p)
