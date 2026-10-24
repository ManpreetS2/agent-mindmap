"""Hermetic adversarial fixtures: synthetic data and file-protocol git only."""
import json
import os
import socket
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

NOW = datetime(2026, 10, 24, 7, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[2]


def git(*args, cwd=None):
    return subprocess.run(
        ['git', '-c', 'core.hooksPath=/dev/null', '-c', 'commit.gpgsign=false',
         '-c', 'user.name=Synthetic QA', '-c', 'user.email=qa@example.invalid', *map(str, args)],
        cwd=cwd, capture_output=True, text=True, check=True, timeout=20,
    ).stdout.strip()


def snapshot(now=NOW):
    from ingest.t3 import T3Projection, read_demo
    raw = read_demo()
    for thread in raw['threads']:
        thread['updatedAt'] = thread['createdAt'] = NOW.isoformat()
    return T3Projection('synthetic-qa', demo=False).snapshot(raw, now.timestamp())


@pytest.fixture(autouse=True)
def isolated_io(tmp_path, monkeypatch):
    """Never consult user quota/config or allow an accidental remote git transport."""
    from tools import export_observability as export
    home = tmp_path / 'isolated home'
    home.mkdir()
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(home / '.config'))
    for key in tuple(os.environ):
        if key.startswith(('GIT_CONFIG_', 'GH_', 'GITHUB_', 'AGENT_MINDMAP_')):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', os.devnull)
    monkeypatch.setenv('GIT_CONFIG_NOSYSTEM', '1')
    monkeypatch.setenv('GIT_ALLOW_PROTOCOL', 'file')
    monkeypatch.setenv('GIT_TERMINAL_PROMPT', '0')
    monkeypatch.setenv('AGENT_MINDMAP_CONFIG_DIR', str(home / 'config'))
    monkeypatch.setenv('AGENT_MINDMAP_QUOTA_DIR', str(home / 'quota'))
    monkeypatch.setattr(export, 'load_quota_pools', lambda **kw: {
        name: {'status': 'UNKNOWN', 'note': 'Synthetic QA: no reading'} for name in export.QUOTA_POOLS
    })
    original_connect = socket.socket.connect

    def guarded_connect(sock, address):
        assert isinstance(address, tuple) and address[0] in {'127.0.0.1', '::1', 'localhost'}
        assert 8961 <= address[1] <= 8969, f'QA refused socket: {address!r}'
        return original_connect(sock, address)

    monkeypatch.setattr(socket.socket, 'connect', guarded_connect)


@pytest.fixture
def world(tmp_path, monkeypatch):
    from tools import publish_observability as pub
    bare = tmp_path / 'local remote.git'
    git('init', '--bare', '-q', '-b', 'main', bare)
    src = tmp_path / 'activity.json'
    src.write_text(json.dumps(snapshot()))
    state = tmp_path / 'publisher state'
    calls = []
    real_cmd = pub.cmd

    def local_cmd(args, **kwargs):
        args = list(args)
        calls.append((args, kwargs.get('what')))
        if args[0] == 'gh':
            assert args[1:3] == ['repo', 'view'], 'No real gh writes permitted'
            return json.dumps({'nameWithOwner': pub.DESTINATION, 'visibility': 'PRIVATE', 'isFork': False})
        assert args[0] == 'git', f'Unapproved executable: {args[0]}'
        if 'clone' in args:
            assert args[-2] == f'https://github.com/{pub.DESTINATION}.git'
            args[-2] = bare.as_uri()
        return real_cmd(args, **kwargs)

    monkeypatch.setattr(pub, 'cmd', local_cmd)

    def publish(now=NOW):
        return pub.publish(src, pub.DESTINATION, for_real=True, state_dir=state, now=now)

    def seed(files):
        checkout = tmp_path / f'seed-{len(list(tmp_path.glob("seed-*")))}'
        git('clone', '-q', bare, checkout)
        for name, content in files.items():
            p = checkout / name
            if p.exists() or p.is_symlink():
                p.unlink()
            if isinstance(content, Path):
                p.symlink_to(content)
            else:
                p.write_text(content)
        git('add', '-A', cwd=checkout)
        git('commit', '-qm', 'synthetic race or remote payload', cwd=checkout)
        git('push', '-q', 'origin', 'HEAD:main', cwd=checkout)
        return git('rev-parse', 'HEAD', cwd=checkout)

    def head():
        result = subprocess.run(['git', '--git-dir', str(bare), 'rev-parse', '--verify', 'main'],
                                capture_output=True, text=True, timeout=10)
        return result.stdout.strip() if result.returncode == 0 else None

    return SimpleNamespace(bare=bare, src=src, state=state, calls=calls, publish=publish,
                           seed=seed, head=head,
                           read=lambda name: git('--git-dir', bare, 'show', f'main:{name}'))
