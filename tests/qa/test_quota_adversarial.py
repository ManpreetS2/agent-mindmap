"""Quota attacks use synthetic readings; no provider executable is invoked."""
import copy
import json
import stat
from datetime import timedelta
from types import SimpleNamespace

import pytest

from conftest import NOW

api = pytest.importorskip('tools.quota.api')
N = pytest.importorskip('tools.quota.normalize')
store = pytest.importorskip('tools.quota.store')
manual = pytest.importorskip('tools.quota.collectors.manual')
claude = pytest.importorskip('tools.quota.collectors.claude_statusline')
codex = pytest.importorskip('tools.quota.collectors.codex_app_server')
cursor = pytest.importorskip('tools.quota.collectors.cursor_cli')
allow = pytest.importorskip('tools.quota.collectors._allow')
models = pytest.importorskip('tools.quota.models')


def reading(alias='codex', kind='codex-app-server', observed=NOW):
    return N.make_reading(alias, kind, 'Synthetic quota probe', observed, windows=[
        N.make_window('session', '5-hour', 300, 23, NOW + timedelta(days=2))])


def test_alias_mismatch_cannot_write_or_be_read(tmp_path):
    with pytest.raises(models.QuotaError):
        store.write('claude-2', reading('claude-1', 'claude-statusline'), state_dir=tmp_path)
    assert not list(tmp_path.glob('*.json'))
    p = store.write('claude-1', reading('claude-1', 'claude-statusline'), state_dir=tmp_path)
    p.rename(tmp_path / 'claude-2.json')
    assert api.pools(NOW, tmp_path)[1]['status'] == 'UNKNOWN'


@pytest.mark.parametrize('seconds,status', [(899, 'VERIFIED'), (900, 'STALE'), (901, 'STALE')])
def test_live_expiry_exact_boundary(tmp_path, seconds, status):
    store.write('codex', reading(), state_dir=tmp_path)
    assert api.pools(NOW + timedelta(seconds=seconds), tmp_path)[4]['status'] == status


@pytest.mark.parametrize('seconds,status', [(86399, 'MANUAL'), (86400, 'STALE'), (86401, 'STALE')])
def test_manual_expiry_exact_boundary(tmp_path, seconds, status):
    manual.set_window('devin-free', 'weekly', 23, None, 'Synthetic UI', NOW.isoformat(), state_dir=tmp_path, now=NOW)
    assert api.pools(NOW + timedelta(seconds=seconds), tmp_path)[3]['status'] == status


def test_reset_at_now_drops_window_and_cannot_remain_verified(tmp_path):
    r = reading()
    r['windows'][0]['resets_at'] = NOW.isoformat()
    store.write('codex', r, state_dir=tmp_path)
    pool = api.pools(NOW, tmp_path)[4]
    assert pool['status'] == 'STALE' and pool['windows'] == []


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), -0.1, 100.1, True, '25'])
def test_invalid_percentages_cannot_become_verified(bad):
    r = reading()
    r['windows'][0]['used_pct'] = bad
    pool = N.evaluate('codex', r, NOW)
    assert pool['status'] == 'UNKNOWN' and pool['windows'] == []


@pytest.mark.parametrize('bad', ['not a timestamp', NOW.replace(tzinfo=None).isoformat(),
                               (NOW + timedelta(seconds=61)).isoformat(), None])
def test_invalid_or_future_observation_is_not_evidence(tmp_path, bad):
    r = reading()
    r['observed_at'] = bad
    store.write('codex', r, state_dir=tmp_path)
    assert api.pools(NOW, tmp_path)[4]['status'] == 'UNKNOWN'


def test_duplicate_windows_are_rejected_without_overwriting_success(tmp_path):
    old = store.write('codex', reading(), state_dir=tmp_path).read_bytes()
    r = reading()
    with pytest.raises(models.QuotaError):
        N.make_reading('codex', 'codex-app-server', 'Synthetic', NOW, windows=r['windows'] * 2)
    assert (tmp_path / 'codex.json').read_bytes() == old
    r['windows'] *= 2
    store.write('codex', r, state_dir=tmp_path)
    assert api.pools(NOW, tmp_path)[4]['status'] == 'UNKNOWN'


@pytest.mark.parametrize('argv', [['claude', '-p', 'x'], ['codex', 'exec', 'x'],
                                  ['cursor-agent', 'about', '--format', 'json', '--extra'],
                                  ['sh', '-c', 'codex app-server']])
def test_model_commands_cannot_pass_allowlist(argv):
    with pytest.raises(models.QuotaError):
        allow.check_argv(argv)


@pytest.mark.parametrize('method', ['thread/start', 'turn/start', 'chat/completions', 'account/login/start'])
def test_mutating_rpc_methods_cannot_pass_allowlist(method):
    with pytest.raises(models.QuotaError):
        allow.check_method(method)


def test_collectors_execute_only_allowlisted_argv_and_fail_honestly(tmp_path, monkeypatch):
    store.write('codex', reading(), state_dir=tmp_path)
    invoked = []

    def missing(argv, **kwargs):
        invoked.append(argv)
        raise FileNotFoundError('synthetic binary unavailable')

    error = codex.collect(now=NOW, popen=missing)
    store.write('codex', error, state_dir=tmp_path)
    pool = api.pools(NOW, tmp_path)[4]
    assert invoked == [['codex', 'app-server']]
    assert pool['status'] == 'ERROR' and pool['windows'] == []
    invoked.clear()
    result = cursor.collect(now=NOW, run=missing)
    assert invoked == [['cursor-agent', 'about', '--format', 'json']]
    assert result['outcome'] == 'error'


def test_claude_wrong_config_dir_cannot_overwrite_other_account(tmp_path):
    payload = json.dumps({'rate_limits': {'five_hour': {'used_percentage': 90,
                         'resets_at': (NOW + timedelta(hours=2)).timestamp()}}})
    store.write('claude-2', reading('claude-2', 'claude-statusline'), state_dir=tmp_path)
    before = (tmp_path / 'claude-2.json').read_bytes()
    assert claude.run('claude-2', payload, state_dir=tmp_path,
                      expect_config_dir=str(tmp_path / 'account two'),
                      env={'CLAUDE_CONFIG_DIR': str(tmp_path / 'account one')}, now=NOW) == 'quota n/a'
    assert (tmp_path / 'claude-2.json').read_bytes() == before


def test_permissions_and_allowlisted_fields_with_spaces(tmp_path):
    state = tmp_path / 'quota state with spaces'
    r = reading()
    r.update(accountId='PRIVATE_ACCOUNT_CANARY', email='qa@example.invalid', token='PRIVATE_TOKEN_CANARY')
    r['windows'][0]['secret'] = 'PRIVATE_WINDOW_CANARY'
    p = store.write('codex', r, state_dir=state)
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    assert stat.S_IMODE(state.stat().st_mode) == 0o700
    assert 'CANARY' not in p.read_text() and 'qa@example.invalid' not in p.read_text()


@pytest.mark.parametrize('collector', ['codex', 'claude'])
@pytest.mark.parametrize('bad', ['not-an-epoch', -1, float('nan'), True])
def test_malformed_provider_reset_cannot_become_verified(collector, bad):
    if collector == 'codex':
        r = codex.map_rate_limits({'rateLimits': {'primary': {
            'usedPercent': 23, 'windowDurationMins': 300, 'resetsAt': bad}}}, NOW)
        alias = 'codex'
    else:
        r = claude.extract({'rate_limits': {'five_hour': {'used_percentage': 23, 'resets_at': bad}}}, 'claude-1', NOW)
        alias = 'claude-1'
    assert r is None or N.evaluate(alias, r, NOW)['status'] != 'VERIFIED'


@pytest.mark.parametrize('private', ['/Users/qa/private', 'qa@example.invalid', 'Bearer syntheticcredential123'])
def test_manual_source_never_reaches_public_observability(tmp_path, private):
    """QA-009 (fixed): a path/email/credential-shaped manual --source is rejected outright; nothing is stored or served."""
    doc = pytest.importorskip('tools.observability_doc')
    with pytest.raises(manual.QuotaError):
        manual.set_window('devin-free', 'weekly', 23, None, private, NOW.isoformat(), state_dir=tmp_path, now=NOW)
    result = doc.build_observability({'meta': {'t3': {'mode': 'live'}}}, {}, now=NOW, quota_dir=tmp_path)
    assert private not in json.dumps(result)
    assert all(p['status'] == 'UNKNOWN' for p in result['quota']['pools'] if p['id'] == 'devin-free')


def test_feed_adapter_and_summary_cover_all_status_shapes(tmp_path):
    export = pytest.importorskip('tools.export_observability')
    store.write('codex', reading(), state_dir=tmp_path)
    store.write('cursor-premium', N.make_reading('cursor-premium', 'cursor-cli', 'Synthetic', NOW,
                'unsupported', reason='No usage endpoint'), state_dir=tmp_path)
    for at in (NOW, NOW + timedelta(hours=1)):
        feed = api.to_feed_pools(api.pools(at, tmp_path))
        assert list(feed) == list(models.POOL_ORDER)
        for name, pool in feed.items():
            line = export.quota_line(name, pool)
            assert '?%' not in line
            if pool['status'] in {'UNKNOWN', 'ERROR', 'UNSUPPORTED'}:
                assert '% used' not in line
            if pool['status'] == 'STALE' and pool['windows']:
                assert 'EXPIRED' in line
