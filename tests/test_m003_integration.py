"""Real runtime + quota modules composed by /observability.json (temp dirs only; no real state, no network)."""
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from jsonschema import Draft7Validator

from tools import machine_identity as mi
from tools.observability_doc import build_observability

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schema/observability.schema.json").read_text())
NOW = datetime(2026, 10, 24, 7, 0, tzinfo=UTC)
ACTIVITY = {"meta": {"t3": {"mode": "live", "connection": "connected", "stale_after_sec": 300}}}
PRIVATE = re.compile(r"/Users/|/home/|\.t3|\.config|\.claude|@[A-Za-z0-9.-]+\.[a-z]{2,}|JsMacbookpro", re.I)


def test_initialised_publisher_identity_and_empty_quota_compose_into_a_valid_document(tmp_path):
    cfg = tmp_path / "config dir with spaces"
    ident = mi.init_identity("Mac B", role="publisher", config_dir_=cfg)
    doc = build_observability(ACTIVITY, {"last_t3_poll": NOW.isoformat()}, now=NOW, config_dir=cfg,
                              state_dir=tmp_path / "pub-state", quota_dir=tmp_path / "quota")
    assert not list(Draft7Validator(SCHEMA).iter_errors(doc))
    assert doc["machine"] == {"id": ident.id, "label": "Mac B", "role": "publisher", "platform": doc["machine"]["platform"]}
    assert re.fullmatch(r"mac-[0-9a-f]{8}", doc["machine"]["id"])
    assert all(p["status"] == "UNKNOWN" for p in doc["quota"]["pools"])  # empty quota dir: never a guessed number
    assert not PRIVATE.search(json.dumps(doc))


def test_reader_machine_is_reported_as_reader_and_never_as_owner(tmp_path):
    cfg = tmp_path / "cfg"
    mi.init_identity("Mac C", role="reader", config_dir_=cfg)
    doc = build_observability(ACTIVITY, {"last_t3_poll": NOW.isoformat()}, now=NOW, config_dir=cfg,
                              state_dir=tmp_path / "s", quota_dir=tmp_path / "q")
    assert doc["machine"]["role"] == "reader" and doc["feed"]["owned_by_this_machine"] is not True
