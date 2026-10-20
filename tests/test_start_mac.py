"""MM-020-OPS: scripts/start-mac.sh and install-launchagent.sh."""

from __future__ import annotations

import http.client
import importlib.util
import json
import os
import platform
import plistlib
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

_RENDER_MOD = importlib.util.module_from_spec(
    importlib.util.spec_from_file_location(
        "render_launchagent_plist",
        Path(__file__).resolve().parents[1] / "scripts" / "render_launchagent_plist.py",
    )
)
assert _RENDER_MOD.__spec__ and _RENDER_MOD.__spec__.loader
_RENDER_MOD.__spec__.loader.exec_module(_RENDER_MOD)
render_plist = _RENDER_MOD.render_plist
write_plist = _RENDER_MOD.write_plist

ROOT = Path(__file__).resolve().parents[1]
START_MAC = ROOT / "scripts" / "start-mac.sh"
INSTALL_LA = ROOT / "scripts" / "install-launchagent.sh"
LEDGER_FIXTURE = ROOT / "tests" / "fixtures" / "ledger-sample.md"


def _run_start_mac(
    *args: str,
    env: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        ["/bin/bash", str(START_MAC), *args],
        cwd=ROOT,
        env=merged,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _fake_gh_bin(tmp_path: Path) -> Path:
    """Directory to prepend to PATH; contains a `gh` that serves fixture API responses."""
    gh = tmp_path / "gh"
    interpreter = shutil.which("python3") or sys.executable
    mock = ROOT / "tests" / "fixtures" / "gh_mock_cli.py"
    gh.write_text(
        f"#!{interpreter}\nimport runpy\nrunpy.run_path({str(mock)!r}, run_name='__main__')\n",
        encoding="utf-8",
    )
    gh.chmod(0o755)
    return tmp_path


def _ensure_min_web_dist() -> None:
    dist = ROOT / "web" / "dist"
    dist.mkdir(parents=True, exist_ok=True)
    index = dist / "index.html"
    if not index.is_file():
        index.write_text("<!doctype html><html><body>ok</body></html>", encoding="utf-8")


@pytest.fixture
def venv_backup() -> None:
    venv = ROOT / ".venv"
    backup = ROOT / ".venv.start_mac_test_bak"
    had = venv.exists()
    if had:
        if backup.exists():
            shutil.rmtree(backup)
        shutil.move(venv, backup)
    yield
    if venv.exists():
        shutil.rmtree(venv)
    if had and backup.exists():
        shutil.move(backup, venv)


def test_start_mac_help() -> None:
    proc = _run_start_mac("--help")
    assert proc.returncode == 0
    assert "MINDMAP_LEDGER" in proc.stdout
    assert "8787" in proc.stdout


def test_start_mac_demo_skips_gh_auth() -> None:
    text = START_MAC.read_text(encoding="utf-8")
    assert "apply_demo_flag" in text
    assert "LIVE_ARGS+=(--demo)" in text
    assert "not yet supported (MM-020i)" not in text
    after_apply = text.split("apply_demo_flag", 1)[1]
    assert 'if [[ "$DEMO_MODE" != true ]]; then' in after_apply
    assert "require_gh_auth" in after_apply


def _path_without_python_interpreters() -> str:
    keep: list[str] = []
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not entry:
            continue
        directory = Path(entry)
        if not directory.is_dir():
            continue
        if any((directory / name).exists() for name in ("python3.13", "python3.12", "python3", "python")):
            continue
        keep.append(entry)
    return os.pathsep.join(keep) if keep else "/bin"


def test_start_mac_missing_python(venv_backup: None) -> None:
    env = {"PATH": _path_without_python_interpreters()}
    proc = _run_start_mac(env=env, timeout=60.0)
    assert proc.returncode == 1
    assert "brew install python@3.12" in proc.stderr


def test_start_mac_nonexistent_ledger(tmp_path: Path) -> None:
    _ensure_min_web_dist()
    fake_gh = _fake_gh_bin(tmp_path)
    env = {
        "PATH": f"{fake_gh}{os.pathsep}{os.environ.get('PATH', '')}",
        "MINDMAP_LEDGER": str(tmp_path / "missing-ledger.md"),
    }
    proc = _run_start_mac(env=env)
    assert proc.returncode == 1
    assert "MINDMAP_LEDGER file not found" in proc.stderr


def test_start_mac_busy_port(tmp_path: Path) -> None:
    _ensure_min_web_dist()
    fake_gh = _fake_gh_bin(tmp_path)
    port = 38787
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", port))
    sock.listen(1)
    try:
        env = {
            "PATH": f"{fake_gh}{os.pathsep}{os.environ.get('PATH', '')}",
            "MINDMAP_LEDGER": str(LEDGER_FIXTURE),
            "MINDMAP_PORT": str(port),
        }
        proc = _run_start_mac(env=env)
        assert proc.returncode == 1
        assert "is already in use" in proc.stderr
    finally:
        sock.close()


def test_start_mac_gh_auth_failure(tmp_path: Path) -> None:
    _ensure_min_web_dist()
    gh = tmp_path / "gh"
    gh.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    gh.chmod(0o755)
    env = {
        "PATH": f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}",
        "MINDMAP_LEDGER": str(LEDGER_FIXTURE),
    }
    proc = _run_start_mac(env=env)
    assert proc.returncode == 1
    assert "gh is not authenticated" in proc.stderr


def test_plist_invokes_start_mac_script() -> None:
    text = (ROOT / "ops" / "com.manpreet.mindmap.plist").read_text(encoding="utf-8")
    assert "/bin/bash" in text
    assert "REPLACE_WITH_AGENT_MINDMAP_REPO_ROOT/scripts/start-mac.sh" in text
    assert "SuccessfulExit" in text
    assert "ThrottleInterval" in text


def test_start_mac_uses_hash_locked_venv_install() -> None:
    text = START_MAC.read_text(encoding="utf-8")
    assert "--require-hashes" in text
    assert "requirements-dev.txt" in text
    assert "--no-deps" in text
    assert "-e" in text and "REPO_ROOT" in text


def test_start_mac_wires_events_source_env() -> None:
    text = START_MAC.read_text(encoding="utf-8")
    assert "MINDMAP_EVENTS_SOURCE" in text
    assert "--events-source" in text
    assert 'LIVE_ARGS+=(--events-source "$EVENTS_SOURCE")' in text


def test_start_mac_demo_uses_events_source_off_not_gh() -> None:
    text = START_MAC.read_text(encoding="utf-8")
    assert 'if [[ "$DEMO_MODE" == true ]]; then' in text
    assert "LIVE_ARGS+=(--events-source off)" in text
    assert 'LIVE_ARGS+=(--events-source "$EVENTS_SOURCE")' in text


def test_start_mac_demo_smoke_healthz(tmp_path: Path) -> None:
    """--demo must start despite default MINDMAP_EVENTS_SOURCE=gh (ingest rejects demo+gh)."""
    _ensure_project_venv()
    _ensure_min_web_dist()
    fake_gh = _fake_gh_bin(tmp_path)
    port = 38789
    env = os.environ.copy()
    env["PATH"] = f"{fake_gh}{os.pathsep}{env.get('PATH', '')}"
    env["MINDMAP_PORT"] = str(port)
    env["MINDMAP_EVENTS_SOURCE"] = "gh"

    proc = subprocess.Popen(
        ["/bin/bash", str(START_MAC), "--demo"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 45.0
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    break
            except OSError:
                if proc.poll() is not None:
                    stderr = proc.stderr.read() if proc.stderr else ""
                    raise AssertionError(f"start-mac --demo exited early: {stderr}")
                time.sleep(0.2)
        else:
            raise TimeoutError("demo server did not listen on 127.0.0.1")

        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5.0)
        conn.request("GET", "/healthz")
        resp = conn.getresponse()
        body = json.loads(resp.read().decode())
        conn.close()
        assert resp.status == 200
        assert body.get("mode") == "demo"
    finally:
        proc.send_signal(15)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def test_python_yml_path_filters_include_ops_and_scripts() -> None:
    workflow = (ROOT / ".github/workflows/python.yml").read_text(encoding="utf-8")
    assert workflow.count('"ops/**"') >= 2
    assert workflow.count('"scripts/**"') >= 2


def test_render_launchagent_plist_round_trip(tmp_path: Path) -> None:
    template = ROOT / "ops" / "com.manpreet.mindmap.plist"
    log_dir = tmp_path / "logs"
    out = tmp_path / "out.plist"
    data = render_plist(
        template,
        repo_root=ROOT,
        ledger_path=LEDGER_FIXTURE,
        log_dir=log_dir,
    )
    write_plist(data, out)
    with out.open("rb") as f:
        loaded = plistlib.load(f)
    assert loaded == data
    args = loaded["ProgramArguments"]
    assert args[0] == "/bin/bash"
    assert str(ROOT) in args[1]
    assert "start-mac.sh" in args[1]
    assert loaded["EnvironmentVariables"]["MINDMAP_LEDGER"] == str(LEDGER_FIXTURE.resolve())
    assert "REPLACE_WITH_" not in out.read_text(encoding="utf-8")


def test_broken_venv_triggers_reinstall(tmp_path: Path) -> None:
    _ensure_min_web_dist()
    fake_gh = _fake_gh_bin(tmp_path)
    venv = ROOT / ".venv"
    backup = ROOT / ".venv.broken_test_bak"
    if venv.exists():
        if backup.exists():
            shutil.rmtree(backup)
        shutil.move(venv, backup)
    try:
        venv_python = Path(sys.executable)
        bootstrap_py = (
            str(venv_python)
            if venv_python.is_file()
            else (shutil.which("python3") or "python3")
        )
        subprocess.run([bootstrap_py, "-m", "venv", str(venv)], cwd=ROOT, check=True)
        port = 38786
        env = {
            "PATH": f"{fake_gh}{os.pathsep}{os.environ.get('PATH', '')}",
            "MINDMAP_LEDGER": str(LEDGER_FIXTURE),
            "MINDMAP_PORT": str(port),
            "MINDMAP_EVENTS_SOURCE": "off",
        }
        proc = subprocess.Popen(
            ["/bin/bash", str(START_MAC)],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            deadline = time.monotonic() + 90.0
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    break
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                        break
                except OSError:
                    time.sleep(0.3)
            venv_py = ROOT / ".venv" / "bin" / "python"
            assert venv_py.is_file()
            subprocess.run(
                [str(venv_py), "-c", "import ingest, jsonschema"],
                check=True,
            )
        finally:
            if proc.poll() is None:
                proc.send_signal(15)
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()
    finally:
        if venv.exists():
            shutil.rmtree(venv)
        if backup.exists():
            shutil.move(backup, venv)


def test_busy_port_without_lsof(tmp_path: Path) -> None:
    _ensure_project_venv()
    _ensure_min_web_dist()
    fake_gh = _fake_gh_bin(tmp_path)
    port = 38785
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", port))
    sock.listen(1)
    minimal_path = f"{fake_gh}{os.pathsep}/bin"
    try:
        env = {
            "PATH": minimal_path,
            "MINDMAP_LEDGER": str(LEDGER_FIXTURE),
            "MINDMAP_PORT": str(port),
        }
        proc = _run_start_mac(env=env, timeout=120.0)
        assert proc.returncode == 1
        assert "is already in use" in proc.stderr
    finally:
        sock.close()


def test_install_launchagent_renders_plist_linux(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("MINDMAP_LEDGER", str(LEDGER_FIXTURE))
    proc = subprocess.run(
        ["/bin/bash", str(INSTALL_LA)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    dest = home / "Library" / "LaunchAgents" / "com.manpreet.mindmap.plist"
    with dest.open("rb") as f:
        plistlib.load(f)
    assert "launchctl bootstrap" in proc.stdout


@pytest.mark.skipif(platform.system() != "Darwin", reason="plutil is macOS-only")
def test_install_launchagent_renders_plist_macos(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if not shutil.which("plutil"):
        pytest.skip("plutil not installed")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    ledger = LEDGER_FIXTURE
    monkeypatch.setenv("MINDMAP_LEDGER", str(ledger))
    proc = subprocess.run(
        ["/bin/bash", str(INSTALL_LA)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    dest = home / "Library" / "LaunchAgents" / "com.manpreet.mindmap.plist"
    assert dest.is_file()
    body = dest.read_text(encoding="utf-8")
    assert str(ROOT) in body
    assert str(ledger) in body
    assert "start-mac.sh" in body
    assert "launchctl bootstrap" in proc.stdout


def _ensure_project_venv() -> Path:
    vpy = ROOT / ".venv" / "bin" / "python"
    if not vpy.is_file() or subprocess.run(
        [str(vpy), "-c", "import ingest, jsonschema"],
        capture_output=True,
    ).returncode != 0:
        if (ROOT / ".venv").exists():
            shutil.rmtree(ROOT / ".venv")
        subprocess.run([sys.executable, "-m", "venv", str(ROOT / ".venv")], cwd=ROOT, check=True)
        subprocess.run(
            [str(vpy), "-m", "pip", "install", "-q", "--require-hashes", "-r", "requirements-dev.txt"],
            cwd=ROOT,
            check=True,
        )
        subprocess.run(
            [str(vpy), "-m", "pip", "install", "-q", "--no-deps", "-e", "."],
            cwd=ROOT,
            check=True,
        )
    return vpy


def test_start_mac_smoke_fixture_ledger(tmp_path: Path) -> None:
    """Linux VM smoke: real server, curl health + Host guard (requires built web/dist)."""
    _ensure_project_venv()

    dist = ROOT / "web" / "dist" / "index.html"
    if not dist.is_file():
        if not shutil.which("npm"):
            pytest.skip("npm required to build web/dist for smoke test")
        subprocess.run(["npm", "ci"], cwd=ROOT / "web", check=True)
        subprocess.run(["npm", "run", "build"], cwd=ROOT / "web", check=True)

    fake_gh = _fake_gh_bin(tmp_path)
    port = 38788
    env = os.environ.copy()
    env["PATH"] = f"{fake_gh}{os.pathsep}{env.get('PATH', '')}"
    env["MINDMAP_LEDGER"] = str(LEDGER_FIXTURE)
    env["MINDMAP_PORT"] = str(port)

    proc = subprocess.Popen(
        ["/bin/bash", str(START_MAC)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 45.0
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    break
            except OSError:
                if proc.poll() is not None:
                    raise AssertionError(
                        f"start-mac exited early: {proc.stderr.read() if proc.stderr else ''}"
                    )
                time.sleep(0.2)
        else:
            raise TimeoutError("server did not listen")

        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5.0)
        conn.request("GET", "/healthz")
        resp = conn.getresponse()
        assert resp.status == 200
        conn.close()

        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5.0)
        conn.request("GET", "/")
        resp = conn.getresponse()
        assert resp.status == 200
        conn.close()

        activity_ok = False
        for _ in range(50):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5.0)
            conn.request("GET", "/activity.json")
            resp = conn.getresponse()
            resp.read()
            conn.close()
            if resp.status == 200:
                activity_ok = True
                break
            time.sleep(0.2)
        assert activity_ok, "activity.json was not ready in time"

        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5.0)
        conn.request("GET", "/healthz", headers={"Host": "evil.example"})
        resp = conn.getresponse()
        assert resp.status == 403
        conn.close()
    finally:
        proc.send_signal(15)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        time.sleep(0.5)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.3)
            assert probe.connect_ex(("127.0.0.1", port)) != 0, "port still in use after stop"
