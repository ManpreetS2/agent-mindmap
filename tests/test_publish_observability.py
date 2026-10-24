"""Publisher: destination safety, redaction, idempotency, rate limits, locking, conflicts. Real git, stub gh."""
import json
import os
import stat
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ingest.t3 import T3Projection, read_demo
from tools import publish_observability as pub

NOW = datetime(2026, 10, 23, 20, 0, tzinfo=UTC)
REMOTE = "https://github.com/ManpreetS2/agent-observability-private.git"


def snapshot(now=NOW, title=None, activity_at=NOW):
    raw = read_demo()
    for t in raw["threads"]:
        t["updatedAt"] = t["createdAt"] = activity_at.isoformat()
    if title:
        raw["threads"][0]["title"] = title
    return T3Projection("test", demo=False).snapshot(raw, now.timestamp())


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A bare local repo standing in for GitHub, a stub `gh`, and an isolated state dir."""
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", "-b", "main", str(bare)], check=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = repo ] && [ "$2" = view ]; then\n'
        '  echo "{\\"nameWithOwner\\":\\"$3\\",\\"visibility\\":\\"${FAKE_VISIBILITY:-PRIVATE}\\",\\"isFork\\":false}"\n'
        "  exit 0\nfi\nexit 1\n")
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", f"url.file://{bare}.insteadOf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", REMOTE[:-4] + ".git")
    # insteadOf must match the clone URL exactly
    monkeypatch.setenv("GIT_CONFIG_KEY_0", f"url.file://{bare}.insteadOf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", REMOTE)
    state = tmp_path / "state"
    src = tmp_path / "activity.json"
    src.write_text(json.dumps(snapshot()))
    return type("W", (), {"bare": bare, "state": state, "src": src, "tmp": tmp_path})


def run(world, now=NOW, **kw):
    return pub.publish(world.src, pub.DESTINATION, for_real=True, state_dir=world.state, now=now, **kw)


def remote_files(world):
    out = subprocess.run(["git", "--git-dir", str(world.bare), "ls-tree", "-r", "--name-only", "main"],
                         capture_output=True, text=True, check=True).stdout
    return sorted(out.split())


def remote_commits(world):
    return int(subprocess.run(["git", "--git-dir", str(world.bare), "rev-list", "--count", "main"],
                              capture_output=True, text=True, check=True).stdout)


def test_local_check_never_touches_github(world):
    msg = pub.publish(world.src, pub.DESTINATION, for_real=False, state_dir=world.state, now=NOW)
    assert msg.startswith("LOCAL CHECK OK")
    assert not world.state.exists()
    assert remote_commits_or_zero(world) == 0


def remote_commits_or_zero(world):
    r = subprocess.run(["git", "--git-dir", str(world.bare), "rev-list", "--count", "main"],
                       capture_output=True, text=True, check=False)
    return int(r.stdout) if r.returncode == 0 else 0


def test_first_publish_creates_exactly_the_two_files(world):
    assert run(world).startswith("PUBLISHED")
    assert remote_files(world) == ["latest.json", "summary.md"]
    state = json.loads((world.state / "state.json").read_text())
    assert state["last_success_at"] and state["consecutive_failures"] == 0
    assert stat.S_IMODE(world.state.stat().st_mode) == 0o700


def test_unchanged_snapshot_is_not_republished_until_heartbeat(world):
    run(world)
    n = remote_commits(world)
    later = NOW + timedelta(minutes=5)
    world.src.write_text(json.dumps(snapshot(later)))  # new observed_at only; the sessions did nothing new
    assert run(world, now=later).startswith("NO CHANGE")
    assert remote_commits(world) == n
    beat = NOW + timedelta(minutes=16)
    world.src.write_text(json.dumps(snapshot(beat)))
    assert run(world, now=beat).startswith("PUBLISHED")
    assert remote_commits(world) == n + 1


def test_real_change_is_published_but_rate_limited(world):
    run(world)
    t = NOW + timedelta(seconds=60)
    world.src.write_text(json.dumps(snapshot(t, title="Different task title", activity_at=t)))
    assert run(world, now=t).startswith("SKIPPED: published 60s ago")
    t = NOW + timedelta(minutes=4)
    world.src.write_text(json.dumps(snapshot(t, title="Different task title", activity_at=t)))
    assert run(world, now=t).startswith("PUBLISHED")


def test_public_or_wrong_destination_is_refused(world, monkeypatch):
    monkeypatch.setenv("FAKE_VISIBILITY", "PUBLIC")
    with pytest.raises(pub.PublishError, match="PRIVATE"):
        run(world)
    assert remote_commits_or_zero(world) == 0
    assert json.loads((world.state / "state.json").read_text())["consecutive_failures"] == 1
    assert not pub.verified_destination("ManpreetS2/agent-mindmap",
                                        {"nameWithOwner": "ManpreetS2/agent-mindmap", "visibility": "PRIVATE"})
    with pytest.raises(SystemExit):
        monkeypatch.setattr("sys.argv", ["x", "--input", str(world.src), "--repo", "ManpreetS2/agent-mindmap"])
        pub.main()


def test_failures_back_off_then_recover(world, monkeypatch):
    monkeypatch.setenv("FAKE_VISIBILITY", "PUBLIC")
    with pytest.raises(pub.PublishError):
        run(world)
    assert run(world, now=NOW + timedelta(seconds=10)).startswith("SKIPPED: backing off")
    monkeypatch.setenv("FAKE_VISIBILITY", "PRIVATE")
    assert run(world, now=NOW + timedelta(seconds=90)).startswith("PUBLISHED")
    assert json.loads((world.state / "state.json").read_text())["consecutive_failures"] == 0


def test_secret_in_snapshot_blocks_publishing(world, monkeypatch):
    # upstream sanitising already redacts it; this is the second, independent line of defence
    activity = snapshot()
    activity["nodes"][0]["session"]["branch"] = "feature/ghp_" + "a" * 30
    world.src.write_text(json.dumps(activity))
    run(world)
    assert "ghp_" not in subprocess.run(["git", "--git-dir", str(world.bare), "show", "main:latest.json"],
                                        capture_output=True, text=True, check=True).stdout
    leaky = pub.make_feed

    def make_feed(source, now):
        feed, summary = leaky(source, now=now)
        return feed, summary + "\nleaked ghp_" + "b" * 30
    monkeypatch.setattr(pub, "make_feed", make_feed)
    n = remote_commits(world)
    with pytest.raises(pub.PublishError, match="Sensitive"):
        run(world, now=NOW + timedelta(minutes=10))
    assert remote_commits(world) == n
    for text in ("Authorization: Bearer abcdefgh12345678", "/Users/someone/code", "-----BEGIN PRIVATE KEY-----",
                 "api_key=abcdefghijklmnop12345"):
        assert pub.scan_for_sensitive(text), text
    assert not pub.scan_for_sensitive("Fix token: expiry bug in the roster")


def test_demo_empty_or_unreachable_sources_never_publish(world):
    demo = snapshot()
    demo["meta"]["t3"]["mode"] = "demo"
    world.src.write_text(json.dumps(demo))
    with pytest.raises(pub.PublishError, match="Only real T3"):
        run(world)
    world.src.write_text("not json")
    with pytest.raises(pub.PublishError, match="valid JSON"):
        run(world)
    empty = snapshot()
    empty["nodes"], empty["edges"] = [], []
    world.src.write_text(json.dumps(empty))
    with pytest.raises(pub.PublishError, match="empty feed"):
        run(world)
    with pytest.raises(pub.PublishError, match="loopback"):
        pub.read_source(None, "http://example.com/activity.json")
    with pytest.raises(pub.PublishError, match="loopback"):
        pub.read_source(None, "https://127.0.0.1/activity.json")
    with pytest.raises(pub.PublishError, match="exactly one"):
        pub.read_source(None, None)
    assert remote_commits_or_zero(world) == 0


def test_stale_collector_is_published_honestly_as_stale(world):
    old = NOW - timedelta(hours=2)
    world.src.write_text(json.dumps(snapshot(old)))
    run(world)
    latest = subprocess.run(["git", "--git-dir", str(world.bare), "show", "main:latest.json"],
                            capture_output=True, text=True, check=True).stdout
    assert json.loads(latest)["freshness"] == "stale"


def test_concurrent_publisher_is_refused(world):
    with pub.Lock(world.state), pytest.raises(pub.PublishError, match="Another publisher"):
        run(world)
    assert remote_commits_or_zero(world) == 0


def test_rejected_push_is_retried_from_a_fresh_clone(world, monkeypatch):
    run(world)
    other = world.tmp / "other"
    t = NOW + timedelta(minutes=5)
    world.src.write_text(json.dumps(snapshot(t, title="Changed")))
    real = pub.cmd
    state = {"raced": False}

    def racing(args, **kw):
        if "push" in args and not state["raced"]:
            state["raced"] = True  # someone else pushes between our clone and our push
            subprocess.run(["git", "clone", "-q", str(world.bare), str(other)], check=True)
            (other / "NOTES").write_text("x")
            for c in (["add", "NOTES"], ["-c", "user.name=a", "-c", "user.email=a@b.c", "commit", "-qm", "race"], ["push", "-q", "origin", "HEAD:main"]):
                subprocess.run(["git", "-C", str(other), *c], check=True, capture_output=True)
        return real(args, **kw)

    monkeypatch.setattr(pub, "cmd", racing)
    assert run(world, now=t).startswith("PUBLISHED")
    assert "NOTES" in remote_files(world) and "latest.json" in remote_files(world)  # their file untouched


def test_remote_symlink_or_malformed_feed_is_not_followed(world):
    seed = world.tmp / "seed"
    subprocess.run(["git", "clone", "-q", str(world.bare), str(seed)], check=True, capture_output=True)
    (seed / "target").write_text("x")
    os.symlink("target", seed / "latest.json")
    for c in (["add", "-A"], ["-c", "user.name=a", "-c", "user.email=a@b.c", "commit", "-qm", "s"], ["push", "-q", "origin", "HEAD:main"]):
        subprocess.run(["git", "-C", str(seed), *c], check=True, capture_output=True)
    with pytest.raises(pub.PublishError, match="symlink"):
        run(world)


def test_remote_hooks_and_templates_are_not_executed(world, tmp_path):
    marker = tmp_path / "hook-ran"
    tmpl = tmp_path / "tmpl" / "hooks"
    tmpl.mkdir(parents=True)
    hook = tmpl / "pre-commit"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
    hook.chmod(0o755)
    os.environ["GIT_TEMPLATE_DIR"] = str(tmp_path / "tmpl")
    try:
        run(world)
    finally:
        del os.environ["GIT_TEMPLATE_DIR"]
    assert not marker.exists()


def test_secure_env_drops_worker_credentials(monkeypatch):
    for k in ("GH_TOKEN", "GITHUB_TOKEN", "GH_CONFIG_DIR"):
        monkeypatch.setenv(k, "x")
    env = pub.secure_env()
    assert not {"GH_TOKEN", "GITHUB_TOKEN", "GH_CONFIG_DIR"} & set(env)
    assert env["GIT_TERMINAL_PROMPT"] == "0"


def test_input_inside_public_repo_is_refused(monkeypatch):
    monkeypatch.setattr("sys.argv", ["x", "--input", str(pub.ROOT / "schema" / "activity.schema.json")])
    with pytest.raises(SystemExit):
        pub.main()


def test_unreachable_collector_publishes_unavailable_once_after_a_success(world):
    with pytest.raises(pub.CollectorUnavailable):  # first ever run: nothing to correct, so nothing is uploaded
        pub.publish(None, pub.DESTINATION, for_real=True, collector_url="http://127.0.0.1:9/activity.json",
                    state_dir=world.state, now=NOW)
    assert remote_commits_or_zero(world) == 0
    run(world)
    t = NOW + timedelta(minutes=5)
    out = pub.publish(None, pub.DESTINATION, for_real=True, collector_url="http://127.0.0.1:9/activity.json",
                      state_dir=world.state, now=t)
    assert out.startswith("PUBLISHED: 0 sessions")
    latest = json.loads(subprocess.run(["git", "--git-dir", str(world.bare), "show", "main:latest.json"],
                                       capture_output=True, text=True, check=True).stdout)
    assert latest["connection"] == "unavailable" and latest["sessions"] == [] and latest["freshness"] == "stale"
    t2 = NOW + timedelta(minutes=9)
    again = pub.publish(None, pub.DESTINATION, for_real=True, collector_url="http://127.0.0.1:9/activity.json",
                        state_dir=world.state, now=t2)
    assert again.startswith("NO CHANGE")  # no commit churn while it stays down


def test_launchd_plist_is_bounded_and_carries_no_secrets(tmp_path):
    from tools import publisher_launchd as ld
    data = ld.plist_data(python="/venv/bin/python", repo=Path("/repo"), state_dir=tmp_path)
    assert data["StartInterval"] >= 180
    assert data["ProgramArguments"][-1] == "--for-real" and "--collector-url" in data["ProgramArguments"]
    env = " ".join(f"{k}={v}" for k, v in data["EnvironmentVariables"].items())
    assert not any(w in env.upper() for w in ("TOKEN", "SECRET", "KEY", "PASSWORD"))
    assert data["ProgramArguments"][4].startswith("http://127.0.0.1")
    assert ld.render().startswith(b"<?xml")


def test_enable_requires_explicit_approval_flag(monkeypatch):
    from tools import publisher_launchd as ld
    calls = []
    monkeypatch.setattr(ld, "launchctl", lambda *a: calls.append(a))
    monkeypatch.setattr("sys.argv", ["x", "enable"])
    with pytest.raises(SystemExit):
        ld.main()
    assert calls == []


def test_heartbeat_stays_inside_the_trust_window():
    from tools.export_observability import TRUST_WINDOW_SEC
    assert pub.HEARTBEAT_SEC + 240 < TRUST_WINDOW_SEC  # worst case: due just after a 240 s launchd tick


def _serve(routes):
    import http.server
    import threading

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = routes.get(self.path)
            self.send_response(200 if body is not None else 404)
            self.end_headers()
            if body is not None:
                self.wfile.write(json.dumps(body).encode())

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_last_successful_poll_not_last_change_decides_freshness():
    changed = datetime.now(UTC) - timedelta(minutes=6)
    polled = datetime.now(UTC) - timedelta(seconds=7)
    act = snapshot(changed, activity_at=changed)
    srv = _serve({"/activity.json": act, "/healthz": {"last_t3_poll": polled.isoformat()}})
    try:
        src = pub.read_source(None, f"http://127.0.0.1:{srv.server_port}/activity.json")
    finally:
        srv.shutdown()
    feed, _, _ = pub.build(src, datetime.now(UTC))
    assert feed["freshness"] == "fresh" and feed["observed_at"] == polled.astimezone(UTC).isoformat()


@pytest.mark.parametrize("health", [None, {"last_t3_poll": None}, {"last_t3_poll": "garbage"},
                                    {"last_t3_poll": "2999-01-01T00:00:00+00:00"},
                                    {"last_t3_poll": "2026-01-01T00:00:00+00:00"}])
def test_missing_bad_future_or_older_poll_time_is_ignored(health):
    changed = datetime.now(UTC) - timedelta(minutes=6)
    routes = {"/activity.json": snapshot(changed, activity_at=changed)}
    if health is not None:
        routes["/healthz"] = health
    srv = _serve(routes)
    try:
        src = pub.read_source(None, f"http://127.0.0.1:{srv.server_port}/activity.json")
    finally:
        srv.shutdown()
    feed, _, _ = pub.build(src, datetime.now(UTC))
    assert feed["freshness"] == "stale"


def test_poll_time_is_not_trusted_when_the_snapshot_says_unavailable():
    changed = datetime.now(UTC) - timedelta(minutes=6)
    act = snapshot(changed, activity_at=changed)
    act["meta"]["t3"]["connection"] = "unavailable"
    srv = _serve({"/activity.json": act, "/healthz": {"last_t3_poll": datetime.now(UTC).isoformat()}})
    try:
        src = pub.read_source(None, f"http://127.0.0.1:{srv.server_port}/activity.json")
    finally:
        srv.shutdown()
    feed, _, _ = pub.build(src, datetime.now(UTC))
    assert feed["freshness"] == "stale" and feed["connection"] == "unavailable"


def test_collector_reports_last_successful_poll_even_when_nothing_changed(tmp_path, monkeypatch):
    from ingest.t3 import read_demo
    from ingest.t3_live import T3Daemon
    clock = [1_800_000_000.0]

    async def fake_connect(url, cache=None):
        return read_demo()

    monkeypatch.setattr("ingest.t3_live.connect", fake_connect)
    daemon = T3Daemon(activity_path=tmp_path / "activity.json", static_dir=tmp_path, cache_dir=tmp_path, bots=[],
                      t3_url="http://127.0.0.1:3773/mcp", clock=lambda: clock[0])
    daemon.run_poll_cycle()
    first = daemon.health().last_t3_poll
    built = daemon.activity_body()
    clock[0] += 12
    daemon.run_poll_cycle()
    assert daemon.activity_body() == built            # content unchanged, so the snapshot is not rewritten
    assert daemon.health().last_t3_poll != first      # but the poll time moved
    assert daemon.health().to_json()["last_t3_poll"]

    async def down(url, cache=None):
        raise OSError("unreachable")

    monkeypatch.setattr("ingest.t3_live.connect", down)
    before = daemon.health().last_t3_poll
    clock[0] += 12
    daemon.run_poll_cycle()
    assert daemon.health().last_t3_poll == before     # a failed poll never advances it
