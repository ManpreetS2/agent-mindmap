"""Persistent collector + runtime installation: fixed port, duplicate/conflict handling, plists, approval gates."""
import http.server
import json
import plistlib
import socket
import subprocess
import threading
from pathlib import Path

import pytest

from tools import run_collector as rc
from tools import runtime_install as ri


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve(handler_body):
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(handler_body)

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_collector_is_pinned_to_loopback_8799_and_the_local_t3_url():
    assert rc.PORT == 8799 and rc.T3_URL == "http://127.0.0.1:3773/mcp"
    argv = rc.collector_argv(Path("/state"))
    assert argv[argv.index("--port") + 1] == "8799"
    assert "8882" not in " ".join(argv) and "--demo-replay" not in argv and "t3-demo" not in argv
    assert argv[argv.index("--source") + 1] == "t3"
    assert not hasattr(rc, "argparse")  # no CLI, so a plist can never retarget it


def test_second_instance_exits_cleanly_without_touching_the_first(tmp_path):
    first = rc.lock(tmp_path)
    assert first is not None
    assert rc.run(tmp_path, free_port()) == 0          # lock held: duplicate is a no-op
    import os
    os.close(first)
    assert rc.lock(tmp_path) is not None               # released when the owner goes away


def test_existing_collector_on_the_port_is_left_alone(tmp_path):
    srv = serve(json.dumps({"last_build": "x", "errors": []}).encode())
    try:
        assert rc.is_collector(srv.server_port)
        assert rc.run(tmp_path / "s", srv.server_port) == 0
    finally:
        srv.shutdown()


def test_foreign_listener_on_the_port_is_a_retryable_error_never_killed(tmp_path):
    srv = serve(b"<html>not a collector</html>")
    try:
        assert not rc.is_collector(srv.server_port)
        assert rc.run(tmp_path / "s", srv.server_port) == rc.EX_RETRY
        assert srv.socket.fileno() != -1               # still running: we never touch other processes
    finally:
        srv.shutdown()


def test_collector_plist_restarts_after_crashes_only_and_has_no_secrets(tmp_path):
    data = ri.collector_plist(tmp_path / "rt", tmp_path / "state")
    assert data["KeepAlive"] == {"SuccessfulExit": False}
    assert data["RunAtLoad"] is True and data["ThrottleInterval"] >= 30
    assert data["ProgramArguments"][1:] == ["-m", "tools.run_collector"]      # no port/URL arguments at all
    text = json.dumps(data)
    assert str(tmp_path / "rt") in text and "worktrees" not in text
    assert not any(w in text.upper() for w in ("TOKEN", "SECRET", "PASSWORD", "GH_", "AGENT-CONTROL", "AGENT_CONTROL"))
    assert "8882" not in text


def test_publisher_plist_moves_onto_the_runtime_with_the_same_guards(tmp_path):
    data = ri.publisher_plist_runtime(tmp_path / "rt")
    args = data["ProgramArguments"]
    assert args[0] == str(tmp_path / "rt" / "venv" / "bin" / "python")
    assert args[-1] == "--for-real" and "http://127.0.0.1:8799/activity.json" in args
    assert data["StartInterval"] == 240 and data["WorkingDirectory"] == str(tmp_path / "rt" / "current")
    assert "worktrees" not in json.dumps(data)


def test_stage_never_writes_to_launch_agents_so_nothing_starts_at_login(tmp_path, monkeypatch):
    agents = tmp_path / "LaunchAgents"
    monkeypatch.setattr(ri, "LAUNCH_AGENTS", agents)
    paths = ri.stage(tmp_path / "rt")
    assert len(paths) == 2 and all(p.parent == tmp_path / "rt" / "staged" for p in paths)
    assert not agents.exists()
    assert {plistlib.loads(p.read_bytes())["Label"] for p in paths} == {ri.COLLECTOR_LABEL, ri.PUBLISHER_LABEL}


def test_activation_needs_the_explicit_flag_and_a_build(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(ri, "launchctl", lambda *a: calls.append(a))
    monkeypatch.setattr("sys.argv", ["x", "activate"])
    with pytest.raises(SystemExit):
        ri.main()
    assert calls == []
    with pytest.raises(ri.InstallError, match="build"):
        ri.activate(tmp_path / "empty")
    assert calls == []


def test_activation_refuses_to_kill_a_port_holder_that_is_not_our_manual_collector(tmp_path, monkeypatch):
    rt = tmp_path / "rt"
    (rt / "current").mkdir(parents=True)
    (rt / "current" / "RELEASE.json").write_text("{}")
    killed = []
    monkeypatch.setattr(ri, "selftest", lambda *a: None)
    monkeypatch.setattr(ri, "port_owner_pids", lambda port: [4242])
    monkeypatch.setattr(ri, "loaded", lambda label: False)
    monkeypatch.setattr(ri, "is_manual_collector", lambda pid, port=8799: False)
    monkeypatch.setattr(ri, "LAUNCH_AGENTS", tmp_path / "LA")
    monkeypatch.setattr(ri, "COLLECTOR_STATE", tmp_path / "cs")
    monkeypatch.setattr(ri, "PUBLISHER_STATE", tmp_path / "ps")
    monkeypatch.setattr(ri.os, "kill", lambda *a: killed.append(a))
    monkeypatch.setattr(ri, "launchctl", lambda *a: subprocess.CompletedProcess(a, 0, "", ""))
    with pytest.raises(ri.InstallError, match="not touching it"):
        ri.activate(rt)
    assert killed == [] and not (tmp_path / "LA" / f"{ri.COLLECTOR_LABEL}.plist").exists()


def test_failed_collector_start_is_unloaded_and_its_plist_removed(tmp_path, monkeypatch):
    rt = tmp_path / "rt"
    (rt / "current").mkdir(parents=True)
    (rt / "current" / "RELEASE.json").write_text("{}")
    seen = []
    monkeypatch.setattr(ri, "selftest", lambda *a: None)
    monkeypatch.setattr(ri, "port_owner_pids", lambda port: [])
    monkeypatch.setattr(ri, "loaded", lambda label: False)
    monkeypatch.setattr(ri, "wait_connected", lambda *a, **k: False)
    monkeypatch.setattr(ri, "LAUNCH_AGENTS", tmp_path / "LA")
    monkeypatch.setattr(ri, "COLLECTOR_STATE", tmp_path / "cs")
    monkeypatch.setattr(ri, "PUBLISHER_STATE", tmp_path / "ps")
    monkeypatch.setattr(ri, "launchctl", lambda *a: seen.append(a) or subprocess.CompletedProcess(a, 0, "", ""))
    with pytest.raises(ri.InstallError, match="did not become healthy"):
        ri.activate(rt)
    assert not (tmp_path / "LA" / f"{ri.COLLECTOR_LABEL}.plist").exists()
    assert any(a[0] == "bootout" for a in seen)
    assert not any(ri.PUBLISHER_LABEL in " ".join(a) for a in seen)   # publisher untouched on failure


def test_build_refuses_a_dirty_tree(tmp_path):
    repo = tmp_path / "r"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "f").write_text("a")
    env = ["-c", "user.name=a", "-c", "user.email=a@b.c"]
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), *env, "commit", "-qm", "x"], check=True)
    (repo / "f").write_text("b")
    with pytest.raises(ri.InstallError, match="uncommitted"):
        ri.build(repo, tmp_path / "rt")
    assert not (tmp_path / "rt" / "venv").exists()


def test_sleep_wake_and_disconnects_cannot_fabricate_a_fresh_observation():
    """The collector only advances last_t3_poll after T3 answered; see test_publish_observability for the
    daemon-level proof. Here: the publisher never trusts a poll time older than the snapshot or from the future."""
    from datetime import UTC, datetime, timedelta

    from tools.publish_observability import apply_last_poll
    old = (datetime.now(UTC) - timedelta(minutes=30)).isoformat()
    src = {"generated_at": old, "meta": {"t3": {"connection": "connected"}}}
    apply_last_poll(src, "http://127.0.0.1:1/activity.json")   # unreachable healthz
    assert src["generated_at"] == old


def test_release_ships_everything_the_web_build_and_collector_import():
    assert {"ingest", "tools", "schema", "shared", "config", "fixtures", "web"} <= set(ri.SHIPPED)
    tracked = subprocess.run(["git", "ls-files", *ri.SHIPPED], cwd=ri.REPO, capture_output=True, text=True,
                             check=True).stdout
    assert "shared/types.ts" in tracked and "config/bots.json" in tracked and "fixtures/t3-demo.json" in tracked
