"""MM-020-OPS: scripts/start-mac.sh and install-launchagent.sh."""

from __future__ import annotations

import http.client
import os
import platform
import shutil
import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

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


def test_start_mac_demo_not_supported() -> None:
    proc = _run_start_mac("--demo")
    assert proc.returncode == 2
    assert "not yet supported (MM-020i)" in proc.stderr


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
        assert "already in use" in proc.stderr
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


@pytest.mark.skipif(platform.system() != "Darwin", reason="plutil is macOS-only")
def test_install_launchagent_renders_plist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    if not vpy.is_file():
        subprocess.run([sys.executable, "-m", "venv", str(ROOT / ".venv")], cwd=ROOT, check=True)
        subprocess.run(
            [str(vpy), "-m", "pip", "install", "-q", "-e", ".[dev]"],
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
