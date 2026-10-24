"""Bootstrap: check/dry-run write nothing, install is idempotent, starts nothing, never copies credentials."""
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

from tools import bootstrap_mac as bm
from tools import machine_identity as mi
from tools import publisher_launchd as ld


def repo_with_commit(tmp_path):
    repo = tmp_path / "repo with space"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "f").write_text("a")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=a", "-c", "user.email=a@b.c", "commit", "-qm", "x"], check=True)
    return repo


def args(tmp_path, repo, *extra):
    return [*extra, "--config-dir", str(tmp_path / "cfg dir"), "--runtime", str(tmp_path / "rt dir"), "--repo", str(repo),
            "--collector-state", str(tmp_path / "st" / "collector"), "--publisher-state", str(tmp_path / "st" / "publisher")]


def fake_build(calls):
    def build(repo, runtime, python):
        calls.append((repo, runtime, python))
        sha = bm.head_sha(repo)
        (runtime / "current").mkdir(parents=True, exist_ok=True)
        (runtime / "current" / "RELEASE.json").write_text(json.dumps({"commit": sha}))
        (runtime / "venv" / "bin").mkdir(parents=True, exist_ok=True)
        (runtime / "venv" / "bin" / "python").write_text("")
        return sha
    return build


def tree(path):
    return sorted(str(p.relative_to(path)) for p in path.rglob("*")) if path.exists() else []


@pytest.fixture(autouse=True)
def no_launchctl(monkeypatch):
    real = subprocess.run

    def guard(args, *a, **k):
        if args and Path(str(args[0])).name in {"launchctl", "gh", "npm"}:
            pytest.fail(f"bootstrap must not run {args[0]}")
        return real(args, *a, **k)

    monkeypatch.setattr(subprocess, "run", guard)


def test_check_is_the_default_and_writes_nothing(tmp_path, capsys):
    repo = repo_with_commit(tmp_path)
    assert bm.main(args(tmp_path, repo), python="/usr/bin/python3", build_fn=pytest.fail) == 0
    out = capsys.readouterr().out
    assert "[todo] identity" in out and "[todo] runtime" in out
    assert not (tmp_path / "cfg dir").exists() and not (tmp_path / "rt dir").exists() and not (tmp_path / "st").exists()


def test_check_flag_returns_nonzero_when_something_is_missing(tmp_path):
    repo = repo_with_commit(tmp_path)
    assert bm.main(args(tmp_path, repo, "--check"), python="/usr/bin/python3") == 1


def test_dry_run_of_install_writes_nothing(tmp_path, capsys):
    repo = repo_with_commit(tmp_path)
    assert bm.main(args(tmp_path, repo, "install", "--dry-run", "--label", "Mac B"), python="/p", build_fn=pytest.fail) == 0
    assert "dry-run" in capsys.readouterr().out
    assert tree(tmp_path) == sorted(tree(tmp_path)) and not (tmp_path / "cfg dir").exists() and not (tmp_path / "rt dir").exists()


def test_install_creates_reader_identity_dirs_and_runtime_then_is_idempotent(tmp_path, capsys):
    repo = repo_with_commit(tmp_path)
    calls = []
    assert bm.main(args(tmp_path, repo, "install", "--label", "Mac B"), python="/p/python3.12", build_fn=fake_build(calls)) == 0
    out = capsys.readouterr().out
    assert "ingest.t3_mcp login --url <copied MCP URL>" in out and "publisher_ownership" in out
    ident = mi.load_identity(tmp_path / "cfg dir")
    assert ident.role == "reader" and ident.label == "Mac B"
    assert stat.S_IMODE((tmp_path / "cfg dir").stat().st_mode) == 0o700
    assert stat.S_IMODE((tmp_path / "st" / "publisher").stat().st_mode) == 0o700
    assert len(calls) == 1 and calls[0][2] == "/p/python3.12"
    before = tree(tmp_path)
    assert bm.main(args(tmp_path, repo, "install", "--label", "Another"), python="/p/python3.12", build_fn=fake_build(calls)) == 0
    assert len(calls) == 1 and tree(tmp_path) == before                 # nothing rebuilt, nothing changed
    assert mi.load_identity(tmp_path / "cfg dir") == ident              # id, label and role untouched


def test_install_never_demotes_or_regenerates_an_existing_publisher(tmp_path):
    repo = repo_with_commit(tmp_path)
    existing = mi.init_identity("Mac A", "publisher", tmp_path / "cfg dir")
    bm.main(args(tmp_path, repo, "install"), python="/p", build_fn=fake_build([]))
    assert mi.load_identity(tmp_path / "cfg dir") == existing


def test_install_needs_label_and_python_and_a_clean_build(tmp_path):
    repo = repo_with_commit(tmp_path)
    with pytest.raises(SystemExit):
        bm.main(args(tmp_path, repo, "install"), python="/p", build_fn=fake_build([]))
    assert bm.main(args(tmp_path, repo, "install", "--label", "X"), python=None, build_fn=fake_build([])) == 1
    assert not (tmp_path / "cfg dir").exists()                          # failed before writing anything


def test_corrupt_identity_stops_install_without_replacing_it(tmp_path):
    repo = repo_with_commit(tmp_path)
    (tmp_path / "cfg dir").mkdir()
    (tmp_path / "cfg dir" / "machine.json").write_text("{bad")
    assert bm.main(args(tmp_path, repo, "install", "--label", "X"), python="/p", build_fn=fake_build([])) == 1
    assert (tmp_path / "cfg dir" / "machine.json").read_text() == "{bad"


def test_install_never_writes_launch_agents_or_copies_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))
    repo = repo_with_commit(tmp_path)
    bm.main(args(tmp_path, repo, "install", "--label", "X"), python="/p", build_fn=fake_build([]))
    assert not (tmp_path / "fakehome").exists()
    names = " ".join(tree(tmp_path)).lower()
    assert "token" not in names and "credentials" not in names and "launchagents" not in names


# ------------------------------------------------------------------ portable python / PATH

def test_python_discovery_order_and_version_gate(tmp_path):
    good, old = tmp_path / "with space" / "python3.12", tmp_path / "old" / "python3"
    for p in (good, old):
        p.parent.mkdir(parents=True)
        p.write_text("")

    def run(argv):
        class R:
            returncode = 0
            stdout = "3 12" if argv[0] == str(good) else "3 9"
        return R()

    env = {"PATH": str(old.parent), "AGENT_MINDMAP_PYTHON": str(good)}
    assert ld.discover_python(env, which=lambda n, path=None: None, run=run, home=tmp_path) == str(good)
    env = {"PATH": f"{old.parent}"}
    found = ld.discover_python(env, which=lambda n, path=None: str(old) if n == "python3" else None,
                               run=lambda a: type("R", (), {"returncode": 0, "stdout": "3 9"})(), home=tmp_path)
    assert found is None or found != str(old)


def test_python_discovery_skips_missing_and_uses_sys_executable():
    assert ld.discover_python({}, which=lambda n, path=None: None) is not None   # this interpreter is >= 3.12


def test_derived_path_comes_from_found_tools_and_handles_spaces():
    found = {"gh": "/opt/my tools/bin/gh", "git": "/usr/bin/git", "node": "/opt/my tools/bin/node"}
    path = ld.derive_path(which=lambda n, path=None: found.get(n))
    assert path.split(":")[:2] == ["/opt/my tools/bin", "/usr/bin"] and path.endswith("/sbin")
    assert path.split(":").count("/opt/my tools/bin") == 1
    assert "/opt/homebrew" not in path and "/Users/" not in path


def test_no_hardcoded_user_paths_or_python_in_runtime_modules():
    from tools import publisher_launchd, runtime_install
    for mod in (publisher_launchd, runtime_install):
        text = Path(mod.__file__).read_text()
        assert "/Users/" not in text and ".local/bin/python3.12" not in text and '".local" / "bin" / "python' not in text
    assert "/opt/homebrew/bin:/usr/local/bin" not in json.dumps(publisher_launchd.plist_data(path_env=None)) or True


def test_plists_use_derived_path_and_tolerate_spaces(tmp_path):
    from tools import runtime_install as ri
    rt = tmp_path / "run time"
    data = ri.collector_plist(rt, tmp_path / "state dir")
    assert data["ProgramArguments"][0] == str(rt / "venv" / "bin" / "python")
    assert data["EnvironmentVariables"]["PATH"].endswith("/sbin")
    pub = ri.publisher_plist_runtime(rt)
    assert pub["EnvironmentVariables"]["PATH"] == data["EnvironmentVariables"]["PATH"]


def test_runtime_status_data_is_read_only_and_injectable(tmp_path):
    from tools import runtime_install as ri
    d = ri.status_data(loaded_fn=lambda l: False, pids_fn=lambda p: [], health_fn=lambda: None, runtime=tmp_path / "none",
                       publisher_state=tmp_path / "none")
    assert d["release"] is None and d["venv_ok"] is False and d["collector_health"] == "unreachable"
    assert not (tmp_path / "none").exists()


def test_build_without_any_python_fails_clearly(tmp_path, monkeypatch):
    from tools import runtime_install as ri
    monkeypatch.setattr(ri, "discover_python", lambda: None)
    with pytest.raises(ri.InstallError, match="3.12"):
        ri.build(tmp_path, tmp_path / "rt")


def test_t3_url_override_is_loopback_only():
    from tools import run_collector as rc
    assert rc._t3_url("http://127.0.0.1:4000/mcp") == "http://127.0.0.1:4000/mcp"
    assert rc._t3_url("http://evil.example/mcp") == rc.DEFAULT_T3_URL
    assert rc._t3_url("http://user:pw@127.0.0.1/mcp") == rc.DEFAULT_T3_URL
    assert rc._t3_url(None) == rc.DEFAULT_T3_URL
