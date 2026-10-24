"""Runtime/ownership attacks. Optional modules skip cleanly before integration."""
import copy
import json
import stat
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import NOW, snapshot

mi = pytest.importorskip('tools.machine_identity')
own = pytest.importorskip('tools.publisher_ownership')
md = pytest.importorskip('tools.machine_doctor')
bootstrap = pytest.importorskip('tools.bootstrap_mac')
from tools import publish_observability as pub


def machine(tmp_path, name, role='publisher'):
    config = tmp_path / f'{name} config with spaces'
    identity = mi.init_identity(name, role, config)
    return SimpleNamespace(config=config, identity=identity, state=tmp_path / f'{name} state with spaces')


def go(world, mac, now=NOW):
    return pub.publish(world.src, pub.DESTINATION, for_real=True, config_dir=mac.config, state_dir=mac.state, now=now)


def owner_feed(identity, epoch=1, now=NOW, state='active'):
    return {'exported_at': now.isoformat(), 'publisher': own.publisher_object(identity, epoch, now, state)}


def test_reader_never_checks_destination_or_writes_remote(world, tmp_path):
    reader = machine(tmp_path, 'Mac Reader', 'reader')
    assert go(world, reader).startswith('SKIPPED')
    assert not world.calls and world.head() is None and not reader.state.exists()


@pytest.mark.parametrize('age,action', [(1199, 'refuse'), (1200, 'claim_required'), (1201, 'claim_required'), (-1, 'refuse')])
def test_legacy_feed_exact_lease_boundary(tmp_path, age, action):
    mac = machine(tmp_path, 'Mac A')
    legacy = {'exported_at': (NOW - timedelta(seconds=age)).isoformat()}
    assert own.decide(legacy, mac.identity, NOW).action == action


@pytest.mark.parametrize('field,value', [('epoch', True), ('epoch', -1), ('lease_expires_at', 'soon'),
                                       ('lease_expires_at', '2026-10-24T07:00:00'), ('state', 'resurrected')])
def test_malformed_owner_never_authorizes_publication(tmp_path, field, value):
    mac = machine(tmp_path, 'Mac A')
    feed = owner_feed(mac.identity)
    feed['publisher'][field] = value
    assert own.decide(feed, mac.identity, NOW).action == 'refuse'


def test_claim_takeover_requires_current_owner_confirmation(world, tmp_path):
    a, b = machine(tmp_path, 'Mac A'), machine(tmp_path, 'Mac B', 'reader')
    go(world, a)
    before = world.head()
    for force, token in [(False, None), (True, 'wrong-owner')]:
        with pytest.raises(own.OwnershipError):
            own.claim(pub.DESTINATION, config_dir=b.config, state_dir=b.state, now=NOW,
                      force_takeover=force, confirm=token)
        assert world.head() == before
    own.claim(pub.DESTINATION, config_dir=b.config, state_dir=b.state, now=NOW,
              force_takeover=True, confirm=a.identity.id)
    remote = json.loads(world.read('latest.json'))['publisher']
    assert remote['machine_id'] == b.identity.id and remote['epoch'] == 2
    with pytest.raises(pub.OwnershipRefusal):
        go(world, a, NOW + timedelta(minutes=4))
    assert pub.load_state(a.state)['ownership']['state'] == 'superseded'


def test_release_marker_requires_reclaim_even_from_former_owner(world, tmp_path):
    a, b = machine(tmp_path, 'Mac A'), machine(tmp_path, 'Mac B', 'reader')
    go(world, a)
    own.release(pub.DESTINATION, config_dir=a.config, state_dir=a.state, now=NOW)
    released = json.loads(world.read('latest.json'))['publisher']
    assert released['state'] == 'released'
    assert mi.load_identity(a.config).role == 'reader'
    assert own.decide({'publisher': released}, a.identity, NOW).action == 'claim_required'
    own.claim(pub.DESTINATION, config_dir=b.config, state_dir=b.state, now=NOW)
    claimed = json.loads(world.read('latest.json'))['publisher']
    assert claimed['machine_id'] == b.identity.id and claimed['epoch'] == released['epoch'] + 1


def test_push_rejection_redecides_ownership_against_real_remote(world, tmp_path, monkeypatch):
    a, b = machine(tmp_path, 'Mac A'), machine(tmp_path, 'Mac B', 'reader')
    go(world, a)
    later = NOW + timedelta(minutes=4)
    activity = snapshot(later)
    activity['nodes'][0]['current_task'] = 'Synthetic ownership race'
    world.src.write_text(json.dumps(activity))
    real = pub.cmd
    raced = []

    def racing(args, **kwargs):
        if 'push' in args and not raced:
            raced.append(True)
            own.claim(pub.DESTINATION, config_dir=b.config, state_dir=b.state, now=later,
                      force_takeover=True, confirm=a.identity.id)
        return real(args, **kwargs)

    monkeypatch.setattr(pub, 'cmd', racing)
    with pytest.raises(pub.OwnershipRefusal):
        go(world, a, later)
    assert raced
    latest = json.loads(world.read('latest.json'))['publisher']
    assert latest['machine_id'] == b.identity.id and latest['epoch'] == 2
    assert pub.load_state(a.state)['ownership']['state'] == 'superseded'


@pytest.mark.xfail(strict=True, raises=AssertionError, reason='QA-011: older local epoch can publish after same identity reclaims')
def test_resurrected_generation_of_same_machine_is_fenced(world, tmp_path):
    a = machine(tmp_path, 'Mac A')
    go(world, a)
    remote = json.loads(world.read('latest.json'))
    remote['publisher'] = own.publisher_object(a.identity, 3, NOW)
    before = world.seed({'latest.json': json.dumps(remote)})
    # The resurrected process still carries epoch 1 from before the intervening handovers.
    later = NOW + timedelta(minutes=4)
    activity = snapshot(later)
    activity['nodes'][0]['current_task'] = 'Old generation must not publish'
    world.src.write_text(json.dumps(activity))
    try:
        go(world, a, later)
    except pub.OwnershipRefusal:
        pass
    assert world.head() == before, 'Stale epoch 1 adopted remote epoch 3 and overwrote it'


def test_unreachable_remote_cannot_demote_or_claim_reader(world, tmp_path, monkeypatch):
    b = machine(tmp_path, 'Mac B', 'reader')
    real = pub.cmd
    def outage(args, **kwargs):
        if 'clone' in args:
            raise pub.PublishError('Synthetic GitHub outage')
        return real(args, **kwargs)
    monkeypatch.setattr(pub, 'cmd', outage)
    with pytest.raises(pub.PublishError):
        own.claim(pub.DESTINATION, config_dir=b.config, state_dir=b.state, now=NOW)
    assert mi.load_identity(b.config).role == 'reader'
    assert world.head() is None


def test_bootstrap_is_reader_only_and_never_calls_real_build(tmp_path):
    config, collector, publisher, runtime = [tmp_path / name for name in
                                            ('config with spaces', 'collector state', 'publisher state', 'runtime')]
    calls = []
    def fake_build(repo, runtime, python):
        calls.append((repo, runtime, python))
        return 'a' * 40
    bootstrap.install(label='Mac QA', config_dir=config, collector_state=collector, publisher_state=publisher,
                      runtime=runtime, repo=tmp_path, python='/synthetic/python with spaces', build_fn=fake_build)
    assert mi.load_identity(config).role == 'reader' and len(calls) == 1
    assert stat.S_IMODE((config / 'machine.json').stat().st_mode) == 0o600
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o700 for p in (config, collector, publisher))
    assert not (tmp_path / 'Library/LaunchAgents').exists()


@pytest.mark.parametrize('private', ['ghp_' + 'a' * 30, 'Bearer syntheticcredential123', 'qa@example.invalid'])
def test_doctor_render_and_json_redact_common_private_strings(private):
    check = md.Check('synthetic', md.WARN, private, private)
    assert private not in md.render([check])
    assert private not in json.dumps(check.as_dict())


@pytest.mark.xfail(strict=True, raises=AssertionError, reason='QA-012: doctor sanitizer misses common credential forms')
@pytest.mark.parametrize('private', ['password=syntheticsecret', 'xoxb-1234567890-abcdefghijk',
                                    'Authorization: Basic dXNlcjpwYXNzd29yZA=='])
def test_doctor_does_not_print_other_credential_forms(private):
    identity = mi.MachineIdentity('mac-0000000a', 'Mac A', 'reader', 'synthetic')
    feed = owner_feed(identity)
    feed['publisher']['label'] = private
    feed['trusted_until'] = (NOW + timedelta(minutes=15)).isoformat()
    ctx = md.Context(runner=lambda *args: (0, json.dumps(feed), ''), now=NOW,
                     which_fn=lambda name: '/synthetic/gh')
    checks = md.check_feed(ctx, None)
    assert private not in md.render(checks)
    assert private not in json.dumps([check.as_dict() for check in checks])


@pytest.mark.parametrize('payload', ['null', '[]', '42', '"text"', '{}'])
def test_runtime_rejects_all_original_qa004_remote_shapes(world, tmp_path, payload):
    a = machine(tmp_path, 'Mac A')
    before = world.seed({'latest.json': payload})
    with pytest.raises(pub.PublishError):
        go(world, a)
    assert world.head() == before
    assert pub.load_state(a.state)['consecutive_failures'] == 1
