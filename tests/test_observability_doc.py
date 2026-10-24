"""Composition of /observability.json: fail-soft sources, demo isolation, schema validity, privacy, HTTP route."""
import json
import re
import sys
import threading
import types
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from jsonschema import Draft7Validator

from ingest.live import MindmapHandler
from tools.observability_doc import POOL_IDS, build_observability, demo_document, shift_times, unknown_pools

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schema/observability.schema.json").read_text())
NOW = datetime(2026, 10, 24, 7, 0, tzinfo=UTC)
PRIVATE = re.compile(r"/Users/|/home/|\.t3|\.config|\.claude|@[A-Za-z0-9.-]+\.[a-z]{2,}|Bearer |sk-[A-Za-z0-9]|gh[pousr]_", re.I)


def activity(mode="live", connection="connected", stale_after=300):
    return {"meta": {"t3": {"mode": mode, "connection": connection, "stale_after_sec": stale_after}}}


def valid(doc):
    errors = list(Draft7Validator(SCHEMA).iter_errors(doc))
    assert not errors, errors[0].message
    assert not PRIVATE.search(json.dumps(doc))


@pytest.fixture(autouse=True)
def no_sibling_modules(monkeypatch):
    """Default: the runtime/quota modules are 'not installed' so tests pin each fallback explicitly."""
    for name in ("tools.machine_identity", "tools.publisher_ownership", "tools.quota", "tools.quota.api"):
        monkeypatch.setitem(sys.modules, name, None)


def test_legacy_source_has_nothing_to_report():
    assert build_observability({"meta": {"github": "ok"}}, {}, now=NOW) is None
    assert build_observability(None, {}, now=NOW) is None


def test_live_with_no_sibling_modules_is_honest_unknown():
    doc = build_observability(activity(), {"last_t3_poll": (NOW - timedelta(seconds=20)).isoformat()}, now=NOW)
    valid(doc)
    assert doc["mode"] == "live" and doc["collector"]["status"] == "connected"
    assert [p["id"] for p in doc["quota"]["pools"]] == list(POOL_IDS)
    assert all(p["status"] == "UNKNOWN" and p["windows"] == [] for p in doc["quota"]["pools"])
    assert doc["machine"]["role"] == "reader" and doc["feed"]["status"] == "unknown"
    assert any("not installed" in n for n in doc["notes"])


def test_collector_unavailable_and_stale_poll_are_not_reported_as_connected():
    down = build_observability(activity(connection="unavailable"), {"last_t3_poll": None}, now=NOW)
    assert down["collector"]["status"] == "unavailable" and down["collector"]["reason"]
    old = build_observability(activity(), {"last_t3_poll": (NOW - timedelta(minutes=30)).isoformat()}, now=NOW)
    assert old["collector"]["status"] == "unavailable"  # the snapshot says connected but T3 has not answered recently
    valid(down), valid(old)


def test_sibling_modules_are_composed(monkeypatch):
    pools = unknown_pools("x")
    pools[4].update(status="VERIFIED", observed_at=NOW.isoformat(), expires_at=(NOW + timedelta(minutes=15)).isoformat(),
                    plan="plus", reason=None, source={"kind": "codex-app-server", "method": "m", "supported_programmatically": True},
                    windows=[{"type": "weekly", "label": "7-day", "window_minutes": 10080, "used_pct": 30, "remaining_pct": 70,
                              "resets_at": (NOW + timedelta(days=3)).isoformat()}])
    ident = types.ModuleType("tools.machine_identity")
    ident.load_identity = lambda *a, **k: NS(id="mac-3f9a21c4", label="Mac B", role="publisher")
    own = types.ModuleType("tools.publisher_ownership")
    own.feed_health = lambda **k: {"status": "fresh", "last_published_at": NOW.isoformat(), "last_observed_at": NOW.isoformat(),
                                   "trusted_until": (NOW + timedelta(minutes=15)).isoformat(),
                                   "owner": {"machine_id": "mac-3f9a21c4", "label": "Mac B", "epoch": 2},
                                   "owned_by_this_machine": True, "last_error": None}
    quota = types.ModuleType("tools.quota")
    api = types.ModuleType("tools.quota.api")
    api.pools = lambda **k: pools
    for name, mod in (("tools.machine_identity", ident), ("tools.publisher_ownership", own), ("tools.quota", quota), ("tools.quota.api", api)):
        monkeypatch.setitem(sys.modules, name, mod)
    doc = build_observability(activity(), {"last_t3_poll": NOW.isoformat()}, now=NOW)
    valid(doc)
    assert doc["machine"]["id"] == "mac-3f9a21c4" and doc["machine"]["role"] == "publisher"
    assert doc["feed"]["owned_by_this_machine"] is True
    assert doc["quota"]["pools"][4]["status"] == "VERIFIED" and doc["quota"]["collected_at"] == NOW.isoformat()


def test_a_crashing_or_malformed_source_degrades_not_raises(monkeypatch):
    ident = types.ModuleType("tools.machine_identity")
    ident.load_identity = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("secret /Users/me/boom"))
    quota, api = types.ModuleType("tools.quota"), types.ModuleType("tools.quota.api")
    api.pools = lambda **k: [{"id": "claude-1"}]  # wrong shape: must not be trusted
    for name, mod in (("tools.machine_identity", ident), ("tools.quota", quota), ("tools.quota.api", api)):
        monkeypatch.setitem(sys.modules, name, mod)
    doc = build_observability(activity(), {"last_t3_poll": NOW.isoformat()}, now=NOW)
    valid(doc)  # includes the privacy regex: the exception text must not leak
    assert all(p["status"] == "UNKNOWN" for p in doc["quota"]["pools"])


def test_demo_is_the_synthetic_fixture_shifted_to_now_and_never_verified():
    doc = build_observability(activity(mode="demo"), {}, now=NOW)
    valid(doc)
    assert doc["mode"] == "demo" and doc["generated_at"] == NOW.isoformat()
    assert all(p["status"] != "VERIFIED" for p in doc["quota"]["pools"])
    pool = doc["quota"]["pools"][0]
    assert datetime.fromisoformat(pool["expires_at"]) > NOW  # still "fresh" relative to now, so the UI shows the intended demo state
    assert demo_document(NOW) == demo_document(NOW)  # deterministic


def test_demo_never_reads_real_machine_or_quota_state(monkeypatch):
    boom = types.ModuleType("tools.machine_identity")
    boom.load_identity = lambda *a, **k: (_ for _ in ()).throw(AssertionError("demo must not read real identity"))
    monkeypatch.setitem(sys.modules, "tools.machine_identity", boom)
    build_observability(activity(mode="demo"), {}, now=NOW)


def test_shift_times_only_touches_iso_timestamps():
    out = shift_times({"a": "2026-10-24T07:00:00+00:00", "b": "claude-1", "c": ["2026-10-24T07:00:00+00:00", 5]}, timedelta(hours=1))
    assert out == {"a": "2026-10-24T08:00:00+00:00", "b": "claude-1", "c": ["2026-10-24T08:00:00+00:00", 5]}


class FakeDaemon:
    def __init__(self, body, tmp):
        self.body, self.activity_path = body, tmp / "activity.json"

    def activity_body(self):
        return self.body

    def health(self):
        return NS(to_json=lambda: {"last_t3_poll": datetime.now(UTC).isoformat()})


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


def test_http_route_serves_a_valid_document_and_404s_for_legacy(tmp_path):
    server = serve(json.dumps(activity(connection="connected")).encode(), tmp_path)
    try:
        status, headers, body = get(server, "/observability.json")
        assert status == 200 and headers["Cache-Control"] == "no-store"
        valid(json.loads(body))
    finally:
        server.shutdown()
    legacy = serve(json.dumps({"meta": {"github": "ok"}}).encode(), tmp_path)
    try:
        assert get(legacy, "/observability.json")[0] == 404
    finally:
        legacy.shutdown()
    broken = serve(b"{not json", tmp_path)
    try:
        assert get(broken, "/observability.json")[0] == 404
    finally:
        broken.shutdown()
