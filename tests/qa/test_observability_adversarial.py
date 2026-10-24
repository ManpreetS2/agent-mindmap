"""Fail-soft composition and demo isolation under poisoned diagnostics sources."""
import json
import sys
import types

import pytest
from jsonschema import Draft7Validator

from conftest import NOW, ROOT

obs = pytest.importorskip('tools.observability_doc')


def activity(mode='live'):
    return {'meta': {'t3': {'mode': mode, 'connection': 'connected', 'stale_after_sec': 300}}}


def test_demo_does_not_consult_any_real_source(monkeypatch):
    called = []
    def forbidden(*args, **kwargs):
        called.append(True)
        raise AssertionError('real state touched')
    for name, fn in [('tools.machine_identity', 'load_identity'),
                     ('tools.publisher_ownership', 'feed_health'), ('tools.quota.api', 'pools')]:
        module = types.ModuleType(name)
        setattr(module, fn, forbidden)
        monkeypatch.setitem(sys.modules, name, module)
    doc = obs.build_observability(activity('demo'), {}, now=NOW)
    assert not called
    assert doc['mode'] == 'demo'
    assert all(p['status'] != 'VERIFIED' for p in doc['quota']['pools'])


def test_crashing_diagnostics_degrade_without_exception_text(monkeypatch):
    def crash(*args, **kwargs):
        raise RuntimeError('/Users/qa/private Bearer syntheticcredential123 qa@example.invalid')
    for name, fn in [('tools.machine_identity', 'load_identity'),
                     ('tools.publisher_ownership', 'feed_health'), ('tools.quota.api', 'pools')]:
        module = types.ModuleType(name)
        setattr(module, fn, crash)
        monkeypatch.setitem(sys.modules, name, module)
    doc = obs.build_observability(activity(), {}, now=NOW)
    assert doc['machine']['role'] == 'reader'
    assert doc['feed']['status'] == 'unknown'
    assert all(p['status'] == 'UNKNOWN' for p in doc['quota']['pools'])
    assert 'syntheticcredential123' not in json.dumps(doc)
    assert '/Users/qa' not in json.dumps(doc)


@pytest.mark.xfail(strict=True, raises=AssertionError, reason='QA-010: five matching IDs bypass quota shape validation')
def test_five_ids_without_evidence_degrade_to_valid_unknown(monkeypatch):
    quota = pytest.importorskip('tools.quota.api')
    monkeypatch.setattr(quota, 'pools', lambda **kw: [{'id': pid} for pid in obs.POOL_IDS])
    doc = obs.build_observability(activity(), {}, now=NOW)
    schema = json.loads((ROOT / 'schema/observability.schema.json').read_text())
    assert not list(Draft7Validator(schema).iter_errors(doc))
    assert all(p['status'] == 'UNKNOWN' for p in doc['quota']['pools'])
