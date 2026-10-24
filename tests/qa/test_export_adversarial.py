"""Synthetic attacks at the last JSON/Markdown boundary before upload."""
import json
import re
import unicodedata
from datetime import timedelta

import pytest

from conftest import NOW, snapshot
from ingest.t3 import T3Projection, read_demo
from tools import publish_observability as pub

SECRETS = [
    '/Users/qa/private', '~/.t3/private', '∕Users∕qa∕private', '／Users／qa／private',
    '/U\u200bsers/qa/private', 'ghp_' + 'a' * 32, 'Bearer abcdefghijklmnop123',
    'Authorization: Basic dXNlcjpwYXNzd29yZA==', 'token=syntheticsecretvalue123',
    'gh\u200bp_' + 'a' * 32,
]


@pytest.mark.parametrize('field', ['task', 'provider', 'model', 'project', 'branch'])
@pytest.mark.parametrize('payload', SECRETS)
def test_sensitive_display_fields_never_leave_in_either_artifact(field, payload):
    activity = snapshot()
    node = activity['nodes'][0]
    if field == 'task':
        node['current_task'] = payload
    else:
        node['session'][field] = payload
    feed, body, summary = pub.build(activity, NOW)
    exported = next(s for s in feed['sessions'] if s['id'] == node['id'])
    assert exported[field].startswith('[redacted')
    assert payload not in body and payload not in summary


@pytest.mark.xfail(strict=True, reason='QA-003: email display metadata is published verbatim', raises=AssertionError)
@pytest.mark.parametrize('field', ['task', 'provider', 'model', 'project', 'branch'])
def test_email_never_leaves_in_either_artifact(field):
    activity = snapshot()
    node = activity['nodes'][0]
    payload = 'qa.person@example.invalid'
    if field == 'task':
        node['current_task'] = payload
    else:
        node['session'][field] = payload
    _, body, summary = pub.build(activity, NOW)
    assert payload not in body and payload not in summary


@pytest.mark.parametrize('title', ['alpha | injected\n| row |', 'alpha\r\n# heading\x00\x1b[31m', 'word ' * 100_000])
def test_titles_are_bounded_and_cannot_add_markdown_rows(title):
    raw = read_demo()
    raw['threads'][0]['title'] = title
    activity = T3Projection('qa', demo=False).snapshot(raw, NOW.timestamp())
    feed, _, summary = pub.build(activity, NOW)
    for session in feed['sessions']:
        assert len(session['task']) <= 160
        assert not any(unicodedata.category(c).startswith('C') for c in session['task'])
    rows = [line for line in summary.splitlines() if line.startswith('|')]
    assert len(rows) == len(feed['sessions']) + 2
    assert all(len(re.findall(r'(?<!\\)\|', row)) == 8 for row in rows)


@pytest.mark.parametrize('delta, fresh', [(-121, False), (-120, True), (-1, True), (60, True)])
def test_observation_trust_boundaries(delta, fresh):
    feed, _, _ = pub.build(snapshot(NOW + timedelta(seconds=delta)), NOW)
    assert (feed['freshness'] == 'fresh') is fresh
    if not fresh:
        assert all(s['stale'] for s in feed['sessions'])
        assert feed['trusted_until'] <= NOW.isoformat()


@pytest.mark.parametrize('stamp', [(NOW + timedelta(seconds=61)).isoformat(), '2026-10-24T07:00:00', 'invalid'])
def test_future_naive_invalid_observation_rejected(stamp):
    activity = snapshot()
    activity['generated_at'] = stamp
    with pytest.raises(pub.PublishError):
        pub.build(activity, NOW)


@pytest.mark.xfail(strict=True, reason='QA-007: safe_ident does not decode credential-shaped IDs', raises=AssertionError)
@pytest.mark.parametrize('payload', ['password%3Dsyntheticsecret', 'token%253Dsyntheticsecret'])
def test_encoded_credentials_in_ids_are_not_exported(payload):
    activity = snapshot()
    activity['nodes'][0]['id'] = payload
    _, body, summary = pub.build(activity, NOW)
    assert payload not in body and payload not in summary
