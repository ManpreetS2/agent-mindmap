"""Exercise real local git pushes, corrupt disk state, clocks and process locks."""
import copy
import json
import multiprocessing
import stat
from datetime import timedelta
from pathlib import Path

import pytest

from conftest import NOW, git, snapshot
from tools import publish_observability as pub


def test_only_two_files_written_and_private_modes(world):
    assert world.publish().startswith('PUBLISHED')
    assert world.read('latest.json')
    assert git('--git-dir', world.bare, 'ls-tree', '-r', '--name-only', 'main').splitlines() == ['latest.json', 'summary.md']
    assert stat.S_IMODE(world.state.stat().st_mode) == 0o700
    assert stat.S_IMODE((world.state / 'state.json').stat().st_mode) == 0o600


@pytest.mark.parametrize('name', ['latest.json', 'summary.md'])
def test_remote_symlink_rejected_without_touching_target(world, tmp_path, name):
    target = tmp_path / 'untouched'
    target.write_text('SYNTHETIC PRIVATE CANARY')
    before = world.seed({name: target})
    with pytest.raises(pub.PublishError, match='symlink'):
        world.publish()
    assert world.head() == before
    assert target.read_text() == 'SYNTHETIC PRIVATE CANARY'


@pytest.mark.parametrize('payload', ['{broken', '{"unterminated": '])
def test_malformed_remote_json_is_clean_failure(world, payload):
    before = world.seed({'latest.json': payload})
    with pytest.raises(pub.PublishError, match='malformed'):
        world.publish()
    assert world.head() == before
    assert pub.load_state(world.state)['consecutive_failures'] == 1


@pytest.mark.parametrize('payload', ['null', '[]', '42', '"text"', '{}'])
def test_non_feed_json_remote_is_rejected(world, payload):
    before = world.seed({'latest.json': payload})
    try:
        world.publish()
    except (pub.PublishError, TypeError, AttributeError) as exc:
        assert isinstance(exc, pub.PublishError), 'Remote shape escaped failure accounting'
    assert world.head() == before, 'Malformed remote feed was replaced instead of refused'
    assert pub.load_state(world.state)['consecutive_failures'] == 1


@pytest.mark.xfail(strict=True, reason='QA-005: remote latest.json has no size bound', raises=AssertionError)
def test_oversized_remote_feed_rejected(world):
    feed, _, _ = pub.build(snapshot(), NOW)
    if world.identity is not None:
        from tools import publisher_ownership
        feed['publisher'] = publisher_ownership.publisher_object(world.identity, 1, NOW)
    feed['padding'] = 'x' * (pub.MAX_SOURCE_BYTES + 1)
    before = world.seed({'latest.json': json.dumps(feed)})
    try:
        world.publish()
    except pub.PublishError:
        pass
    assert world.head() == before, 'Oversized remote was parsed and replaced'
    assert pub.load_state(world.state)['consecutive_failures'] == 1


def test_push_race_reclones_and_preserves_concurrent_commit(world, monkeypatch):
    world.publish()
    later = NOW + timedelta(seconds=pub.MIN_INTERVAL_SEC)
    activity = snapshot(later)
    activity['nodes'][0]['current_task'] = 'Changed by synthetic QA'
    world.src.write_text(json.dumps(activity))
    real = pub.cmd
    races = []

    def racing(args, **kwargs):
        if 'push' in args and not races:
            races.append(world.seed({'concurrent-note.txt': 'Other writer owns this'}))
        return real(args, **kwargs)

    monkeypatch.setattr(pub, 'cmd', racing)
    assert world.publish(later).startswith('PUBLISHED')
    assert len([call for call, _ in world.calls if 'clone' in call]) == 3
    assert world.read('concurrent-note.txt') == 'Other writer owns this'
    git('--git-dir', world.bare, 'merge-base', '--is-ancestor', races[0], 'main')
    changed = git('--git-dir', world.bare, 'diff-tree', '--no-commit-id', '--name-only', '-r', 'main').splitlines()
    assert set(changed) <= set(pub.ALLOWED_FILES)


def test_unreachable_remote_records_backoff_without_leaking_error(world, tmp_path, monkeypatch):
    real = pub.cmd

    def unavailable(args, **kwargs):
        if 'clone' in args:
            # A missing file:// repository models transport failure without external network.
            args = list(args)
            args[-2] = (tmp_path / 'unreachable.git').as_uri()
            return ORIGINAL_CMD(args, **kwargs)
        return real(args, **kwargs)

    monkeypatch.setattr(pub, 'cmd', unavailable)
    with pytest.raises(pub.PublishError, match='clone failed'):
        world.publish()
    state = pub.load_state(world.state)
    assert state['consecutive_failures'] == 1
    assert str(tmp_path) not in state['last_error']
    assert not world.head()
    assert world.publish(NOW + timedelta(seconds=1)).startswith('SKIPPED: backing off')


ORIGINAL_CMD = pub.cmd


@pytest.mark.parametrize('kind', ['demo', 'empty', 'invalid', 'oversized'])
def test_unpublishable_source_never_checks_destination(world, kind):
    activity = snapshot()
    if kind == 'demo':
        activity['meta']['t3']['mode'] = 'demo'
    elif kind == 'empty':
        activity['nodes'], activity['edges'] = [], []
    world.src.write_text('not json' if kind == 'invalid' else ' ' * (pub.MAX_SOURCE_BYTES + 1)
                         if kind == 'oversized' else json.dumps(activity))
    with pytest.raises(pub.PublishError):
        world.publish()
    assert not world.calls and not world.head()
    assert not world.state.exists()


@pytest.mark.parametrize('prior_success', [False, True])
@pytest.mark.parametrize('for_real', [False, True])
def test_unavailable_only_after_success_and_explicit_publish(world, monkeypatch, prior_success, for_real):
    if prior_success:
        world.publish()
    before = world.head()

    def down(*args):
        raise pub.CollectorUnavailable('Synthetic collector outage')

    monkeypatch.setattr(pub, 'read_source', down)
    kwargs = dict(for_real=for_real, collector_url='http://127.0.0.1:8961/activity.json',
                  state_dir=world.state, now=NOW + timedelta(minutes=5))
    if prior_success and for_real:
        assert pub.publish(None, pub.DESTINATION, **kwargs).startswith('PUBLISHED')
        feed = json.loads(world.read('latest.json'))
        assert feed['sessions'] == [] and feed['connection'] == 'unavailable'
        assert feed['freshness'] == 'stale'
    else:
        with pytest.raises(pub.CollectorUnavailable):
            pub.publish(None, pub.DESTINATION, **kwargs)
        assert world.head() == before


@pytest.mark.parametrize('raw', ['{broken', 'null', '[]', '42', '{"consecutive_failures":true}',
                                  '{"consecutive_failures":-9}', '{"last_success_at":[]}',
                                  '{"last_success_at":"2999-01-01T00:00:00+00:00"}'])
def test_corrupt_state_is_repaired_by_success(world, raw):
    world.state.mkdir()
    (world.state / 'state.json').write_text(raw)
    assert world.publish().startswith('PUBLISHED')
    state = pub.load_state(world.state)
    assert state['consecutive_failures'] == 0 and state['last_error'] is None


@pytest.mark.parametrize('seconds,blocked', [(-3600, False), (0, True), (179, True), (180, False), (181, False)])
def test_minimum_interval_boundary(seconds, blocked):
    state = {'last_success_at': (NOW - timedelta(seconds=seconds)).isoformat()}
    assert bool(pub.due(state, NOW)) is blocked


@pytest.mark.parametrize('failures,wait', [(1, 60), (2, 180), (3, 600), (4, 1800), (1000, 1800)])
def test_backoff_exact_boundaries(failures, wait):
    for age, blocked in [(-1, False), (0, True), (wait - 1, True), (wait, False)]:
        state = {'consecutive_failures': failures, 'last_attempt_at': (NOW - timedelta(seconds=age)).isoformat()}
        assert bool(pub.due(state, NOW)) is blocked


@pytest.mark.parametrize('seconds,expected', [(539, False), (540, True), (541, True)])
def test_heartbeat_exact_boundary(seconds, expected):
    feed, _, _ = pub.build(snapshot(), NOW)
    previous = copy.deepcopy(feed)
    previous['exported_at'] = (NOW - timedelta(seconds=seconds)).isoformat()
    assert pub.should_publish(previous, feed, now=NOW) is expected


def test_future_remote_timestamp_cannot_suspend_heartbeat():
    feed, _, _ = pub.build(snapshot(), NOW)
    previous = copy.deepcopy(feed)
    previous['exported_at'] = (NOW + timedelta(days=365)).isoformat()
    assert pub.should_publish(previous, feed, now=NOW)


def test_naive_state_clocks_do_not_crash_or_block():
    stamp = NOW.replace(tzinfo=None).isoformat()
    assert pub.due({'last_success_at': stamp, 'last_attempt_at': stamp, 'consecutive_failures': 2}, NOW) is None
    feed, _, _ = pub.build(snapshot(), NOW)
    previous = dict(feed, exported_at=stamp)
    assert pub.should_publish(previous, feed, now=NOW)


def _lock_process(state_dir, ready, release, output):
    try:
        with pub.Lock(Path(state_dir)):
            output.put('acquired')
            ready.set()
            if not release.wait(10):
                raise RuntimeError('Parent did not release lock worker')
    except pub.PublishError:
        output.put('refused')
        ready.set()


def test_lock_contends_between_two_spawned_processes_then_recovers(tmp_path):
    context = multiprocessing.get_context('spawn')
    release = context.Event()
    ready_a, ready_b = context.Event(), context.Event()
    output = context.Queue()
    state = str(tmp_path / 'process locks')
    first = context.Process(target=_lock_process, args=(state, ready_a, release, output))
    second = context.Process(target=_lock_process, args=(state, ready_b, release, output))
    try:
        first.start()
        assert ready_a.wait(8) and output.get(timeout=2) == 'acquired'
        second.start()
        assert ready_b.wait(8) and output.get(timeout=2) == 'refused'
    finally:
        release.set()
        for process in (first, second):
            if process.pid:
                process.join(timeout=5)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=3)
        output.close()
        output.join_thread()
    assert first.exitcode == second.exitcode == 0
    with pub.Lock(Path(state)):
        pass
