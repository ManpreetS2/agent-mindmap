"""Schema validation must reject dishonest evidence, not only validate curated fixtures."""
import copy
import json

import pytest
from jsonschema import Draft7Validator, FormatChecker

from conftest import ROOT


@pytest.fixture
def validator():
    schema = json.loads((ROOT / 'schema/observability.schema.json').read_text())
    Draft7Validator.check_schema(schema)
    return Draft7Validator(schema, format_checker=FormatChecker())


@pytest.fixture
def doc():
    return json.loads((ROOT / 'fixtures/observability/live-mixed.json').read_text())


@pytest.mark.parametrize('path', sorted((ROOT / 'fixtures/observability').glob('*.json')), ids=lambda p: p.stem)
def test_all_observability_fixtures_validate(path, validator):
    validator.validate(json.loads(path.read_text()))


@pytest.mark.parametrize('where', ['root', 'machine', 'collector', 'feed', 'quota', 'pool', 'source', 'window'])
def test_extra_fields_rejected(doc, validator, where):
    pool = doc['quota']['pools'][0]
    target = {'root': doc, 'pool': pool, 'source': pool['source'], 'window': pool['windows'][0]}.get(where)
    if target is None:
        target = doc[where]
    target['private_unexpected'] = 'synthetic-marker'
    assert not validator.is_valid(doc)


def test_six_pools_rejected(doc, validator):
    doc['quota']['pools'].append(copy.deepcopy(doc['quota']['pools'][0]))
    assert not validator.is_valid(doc)


def test_duplicate_ids_rejected(doc, validator):
    doc['quota']['pools'][1]['id'] = doc['quota']['pools'][0]['id']
    assert not validator.is_valid(doc)


@pytest.mark.parametrize('key', ['used_pct', 'remaining_pct'])
@pytest.mark.parametrize('value', [-0.01, 100.01, True, '50'])
def test_invalid_percentages_rejected(doc, validator, key, value):
    doc['quota']['pools'][0]['windows'][0][key] = value
    assert not validator.is_valid(doc)


def test_verified_missing_expiry_field_rejected(doc, validator):
    del doc['quota']['pools'][0]['expires_at']
    assert not validator.is_valid(doc)


@pytest.mark.parametrize('key', ['expires_at', 'observed_at'])
def test_verified_null_evidence_rejected(doc, validator, key):
    doc['quota']['pools'][0][key] = None
    assert not validator.is_valid(doc)
