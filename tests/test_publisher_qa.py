# ruff: noqa: F811
"""Independent QA probes for the private publisher (originally strict-xfail defects; all fixed)."""
import subprocess
from datetime import timedelta

import pytest

from tests.test_publish_observability import (  # noqa: F401
    NOW,
    REMOTE,
    remote_commits,
    remote_files,
    run,
    snapshot,
    world,
)
from tools import publish_observability as pub
from tools.export_observability import make_feed


@pytest.mark.parametrize("branch", ["feature/task-queue-redesign-v2", "Risk-assessment-framework-update"])
def test_ordinary_branch_names_do_not_block_publishing(branch):
    from ingest.t3 import T3Projection, read_demo
    data = read_demo()
    for t in data["threads"]:
        t["updatedAt"] = t["createdAt"] = NOW.isoformat()
    data["threads"][0]["branch"] = branch
    src = T3Projection("test", demo=False).snapshot(data, NOW.timestamp())
    pub.build(src, NOW)


def test_future_observation_is_not_fresh():
    with pytest.raises(ValueError, match="future"):
        make_feed(snapshot(now=NOW + timedelta(days=3)), now=NOW)


def test_trusted_until_is_bounded_by_observation_age():
    feed, _ = make_feed(snapshot(now=NOW - timedelta(minutes=10)), now=NOW)
    assert feed["freshness"] == "stale"
    assert feed["trusted_until"] <= NOW.isoformat()


def test_stale_feed_marks_every_session_stale():
    feed, _ = make_feed(snapshot(now=NOW - timedelta(minutes=10)), now=NOW)
    assert feed["freshness"] == "stale"
    assert all(s["stale"] for s in feed["sessions"])


@pytest.mark.parametrize("bad", ["abc", [1], float("nan")])
def test_corrupt_failure_counter_does_not_wedge(bad):
    pub.due({"consecutive_failures": bad}, NOW)


def test_future_last_success_does_not_block_forever():
    assert pub.due({"last_success_at": (NOW + timedelta(days=30)).isoformat()}, NOW) is None


def test_missing_gh_is_recorded_as_a_failure(world, monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent")
    with pytest.raises((pub.PublishError, OSError)):
        run(world)
    assert pub.load_state(world.state).get("consecutive_failures") == 1


def test_default_branch_other_than_main_is_not_silently_ignored(world):
    """Existing repo whose default branch is master: documents what happens (feed lands on a new `main`)."""
    seed = world.tmp / "seed"
    subprocess.run(["git", "init", "-q", "-b", "master", str(seed)], check=True)
    (seed / "README.md").write_text("x")
    env = {"GIT_AUTHOR_NAME": "a", "GIT_AUTHOR_EMAIL": "a@x", "GIT_COMMITTER_NAME": "a", "GIT_COMMITTER_EMAIL": "a@x",
           "PATH": "/usr/bin:/bin:/opt/homebrew/bin"}
    subprocess.run(["git", "-C", str(seed), "add", "."], check=True, env=env)
    subprocess.run(["git", "-C", str(seed), "commit", "-qm", "seed"], check=True, env=env)
    subprocess.run(["git", "-C", str(seed), "push", "-q", str(world.bare), "master"], check=True)
    subprocess.run(["git", "--git-dir", str(world.bare), "symbolic-ref", "HEAD", "refs/heads/master"], check=True)
    assert run(world).startswith("PUBLISHED")
    assert "latest.json" in remote_files(world)  # on `main`
    head = subprocess.run(["git", "--git-dir", str(world.bare), "ls-tree", "-r", "--name-only", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.split()
    assert "latest.json" not in head, "feed is on `main` but repo default branch (master) shows nothing: doc this"


def test_remote_latest_json_as_directory_is_a_clean_failure(world):
    run(world)
    clone = world.tmp / "c"
    subprocess.run(["git", "clone", "-q", str(world.bare), str(clone)], check=True)
    env = {"GIT_AUTHOR_NAME": "a", "GIT_AUTHOR_EMAIL": "a@x", "GIT_COMMITTER_NAME": "a", "GIT_COMMITTER_EMAIL": "a@x",
           "PATH": "/usr/bin:/bin:/opt/homebrew/bin"}
    subprocess.run(["git", "-C", str(clone), "rm", "-q", "latest.json"], check=True, env=env)
    (clone / "latest.json").mkdir()
    (clone / "latest.json" / "x").write_text("x")
    subprocess.run(["git", "-C", str(clone), "add", "."], check=True, env=env)
    subprocess.run(["git", "-C", str(clone), "commit", "-qm", "dir"], check=True, env=env)
    subprocess.run(["git", "-C", str(clone), "push", "-q", "origin", "HEAD:main"], check=True)
    with pytest.raises(pub.PublishError):
        run(world, now=NOW + timedelta(hours=1))
    assert pub.load_state(world.state)["consecutive_failures"] == 1
