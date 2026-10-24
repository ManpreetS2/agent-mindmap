# ruff: noqa: F811
"""Publisher ownership: lease + epoch fencing, exercised with two simulated Macs on ONE real local git remote."""
import json
import os
import subprocess
import types
from datetime import UTC, datetime, timedelta

import pytest

from tests.test_publish_observability import NOW, remote_commits, snapshot, world  # noqa: F401
from tools import machine_identity as mi
from tools import publish_observability as pub
from tools import publisher_ownership as own

GIT_ENV = {"GIT_AUTHOR_NAME": "a", "GIT_AUTHOR_EMAIL": "a@x", "GIT_COMMITTER_NAME": "a", "GIT_COMMITTER_EMAIL": "a@x",
           "PATH": os.environ["PATH"]}


def mac(world, name, role="publisher", base=None):
    root = base or world.tmp
    cfg, state = root / f"cfg-{name}", root / f"state-{name}"
    ident = mi.init_identity(name, role, cfg)
    return types.SimpleNamespace(cfg=cfg, state=state, ident=ident, name=name)


def go(world, m, now=NOW):
    return pub.publish(world.src, pub.DESTINATION, for_real=True, state_dir=m.state, now=now, config_dir=m.cfg)


def remote_text(world):
    return subprocess.run(["git", "--git-dir", str(world.bare), "show", "main:latest.json"], capture_output=True,
                          text=True, check=True).stdout


def remote_publisher(world):
    return json.loads(remote_text(world))["publisher"]


def push_remote(world, text):
    """Write latest.json straight to the remote (legacy / corrupt / hand-edited feeds)."""
    clone = world.tmp / f"c{len(list(world.tmp.glob('c*')))}"
    subprocess.run(["git", "clone", "-q", str(world.bare), str(clone)], check=True, capture_output=True)
    (clone / "latest.json").write_text(text)
    subprocess.run(["git", "-C", str(clone), "add", "."], check=True, env=GIT_ENV)
    subprocess.run(["git", "-C", str(clone), "commit", "-qm", "x"], check=True, env=GIT_ENV, capture_output=True)
    subprocess.run(["git", "-C", str(clone), "push", "-q", "origin", "HEAD:main"], check=True, env=GIT_ENV)


def claim(world, m, now=NOW, **kw):
    return own.claim(pub.DESTINATION, now=now, state_dir=m.state, config_dir=m.cfg, **kw)


def legacy(exported_at):
    return json.dumps({"format": "agent-mindmap-private-feed/v1", "exported_at": exported_at.isoformat(),
                       "observed_at": exported_at.isoformat(), "sessions": []})


# ------------------------------------------------------------------ decide() as a pure function

def ident(role="publisher", i="mac-0000000a"):
    return mi.MachineIdentity(i, "Mac A", role, "darwin-arm64")


def feed(owner="mac-0000000b", epoch=3, lease=NOW + timedelta(minutes=10), state="active"):
    return {"exported_at": NOW.isoformat(), "publisher": {"machine_id": owner, "label": "Mac B", "epoch": epoch,
                                                           "lease_expires_at": lease.isoformat(), "state": state}}


def test_decide_basic_rules():
    assert own.decide(None, ident(), NOW).action == "publish"
    assert own.decide(None, None, NOW).code == "no_identity"
    assert own.decide(None, ident("reader"), NOW).code == "reader"
    assert own.decide(feed("mac-0000000a"), ident(), NOW).epoch == 3                 # mine: epoch unchanged
    assert own.decide(feed(lease=NOW + timedelta(minutes=1)), ident(), NOW).code == "foreign_active"
    expired = own.decide(feed(lease=NOW - timedelta(seconds=1)), ident(), NOW)
    assert expired.action == "claim_required" and expired.code == "expired"
    assert own.decide(feed(state="released"), ident(), NOW).action == "claim_required"
    assert own.decide(feed("mac-0000000a", state="released"), ident(), NOW).action == "claim_required"


@pytest.mark.parametrize("age_min,action", [(5, "refuse"), (19, "refuse"), (21, "claim_required"), (600, "claim_required")])
def test_legacy_feed_fresh_refuses_old_needs_claim(age_min, action):
    d = own.decide({"exported_at": (NOW - timedelta(minutes=age_min)).isoformat()}, ident(), NOW)
    assert d.action == action


def test_legacy_feed_with_future_or_missing_timestamp_fails_closed():
    assert own.decide({"exported_at": (NOW + timedelta(days=1)).isoformat()}, ident(), NOW).action == "refuse"
    assert own.decide({}, ident(), NOW).code == "corrupt"
    assert own.decide({"exported_at": "yesterday"}, ident(), NOW).code == "corrupt"


@pytest.mark.parametrize("pubobj", [
    "x", [], {}, {"machine_id": "mac-0000000b"},
    {"machine_id": "host.local", "label": "x", "epoch": 1, "lease_expires_at": NOW.isoformat(), "state": "active"},
    {"machine_id": "mac-0000000b", "label": "x", "epoch": 0, "lease_expires_at": NOW.isoformat(), "state": "active"},
    {"machine_id": "mac-0000000b", "label": "x", "epoch": True, "lease_expires_at": NOW.isoformat(), "state": "active"},
    {"machine_id": "mac-0000000b", "label": "x", "epoch": 1, "lease_expires_at": "soon", "state": "active"},
    {"machine_id": "mac-0000000b", "label": "x", "epoch": 1, "lease_expires_at": "2999-01-01T00:00:00+00:00", "state": "active"},
    {"machine_id": "mac-0000000b", "label": "x", "epoch": 1, "lease_expires_at": NOW.isoformat(), "state": "weird"},
])
def test_malformed_owner_record_fails_closed(pubobj):
    d = own.decide({"exported_at": NOW.isoformat(), "publisher": pubobj}, ident(), NOW)
    assert d.action == "refuse" and d.code == "corrupt"


def test_rollback_of_own_epoch_is_refused():
    assert own.decide(feed("mac-0000000a", epoch=2), ident(), NOW, local_epoch=5).code == "rollback"


# ------------------------------------------------------------------ two Macs, one real remote

def test_first_publish_records_owner_and_epoch_one(world):
    a = mac(world, "Mac A")
    assert go(world, a).startswith("PUBLISHED")
    p = remote_publisher(world)
    assert p["machine_id"] == a.ident.id and p["epoch"] == 1 and p["state"] == "active" and p["label"] == "Mac A"
    assert own.parse_time(p["lease_expires_at"]) == NOW + timedelta(seconds=own.LEASE_TTL_SEC)
    text = remote_text(world)
    assert "/Users/" not in text and str(world.tmp) not in text


def test_heartbeat_extends_the_lease_without_changing_the_epoch(world):
    a = mac(world, "Mac A")
    go(world, a)
    later = NOW + timedelta(minutes=16)
    world.src.write_text(json.dumps(snapshot(later)))
    assert go(world, a, later).startswith("PUBLISHED")
    p = remote_publisher(world)
    assert p["epoch"] == 1 and own.parse_time(p["lease_expires_at"]) == later + timedelta(seconds=own.LEASE_TTL_SEC)


def test_second_publisher_is_refused_while_the_lease_is_valid(world):
    a, b = mac(world, "Mac A"), mac(world, "Mac B")
    go(world, a)
    before = remote_text(world)
    with pytest.raises(pub.OwnershipRefusal, match="unexpired lease"):
        go(world, b, NOW + timedelta(minutes=5))
    assert remote_text(world) == before and remote_commits(world) == 1


def test_expired_lease_needs_an_explicit_claim_never_automatic(world):
    a, b = mac(world, "Mac A"), mac(world, "Mac B")
    go(world, a)
    late = NOW + timedelta(minutes=21)
    with pytest.raises(pub.OwnershipRefusal, match="must `claim`"):
        go(world, b, late)
    assert remote_publisher(world)["machine_id"] == a.ident.id
    assert "epoch 2" in claim(world, b, late)
    assert remote_publisher(world)["epoch"] == 2
    assert go(world, b, late + timedelta(minutes=4)).startswith("PUBLISHED")
    assert mi.load_identity(b.cfg).role == "publisher"


def test_takeover_of_an_unexpired_lease_needs_force_and_typed_confirmation(world):
    a, b = mac(world, "Mac A"), mac(world, "Mac B")
    go(world, a)
    t = NOW + timedelta(minutes=2)
    with pytest.raises(own.OwnershipError, match="--force-takeover"):
        claim(world, b, t)
    with pytest.raises(own.OwnershipError):
        claim(world, b, t, force_takeover=True)                       # no confirmation
    with pytest.raises(own.OwnershipError):
        claim(world, b, t, force_takeover=True, confirm="mac-deadbeef")  # wrong confirmation
    assert remote_publisher(world)["epoch"] == 1
    claim(world, b, t, force_takeover=True, confirm=a.ident.id)
    p = remote_publisher(world)
    assert p["machine_id"] == b.ident.id and p["epoch"] == 2


def test_resurrected_old_publisher_refuses_and_records_superseded(world):
    a, b = mac(world, "Mac A"), mac(world, "Mac B")
    go(world, a)
    claim(world, b, NOW + timedelta(minutes=2), force_takeover=True, confirm=a.ident.id)
    go(world, b, NOW + timedelta(minutes=6))
    before = remote_text(world)
    with pytest.raises(pub.OwnershipRefusal):
        go(world, a, NOW + timedelta(minutes=10))                       # A wakes up, thinks it still owns the feed
    assert remote_text(world) == before                                  # never overwritten
    state = pub.load_state(a.state)
    assert state["ownership"]["state"] == "superseded" and state["ownership"]["superseded_by"]["epoch"] == 2
    health = own.feed_health(a.state, NOW + timedelta(minutes=11), a.cfg)
    assert health["owned_by_this_machine"] is False and health["owner"]["machine_id"] == b.ident.id
    # still refused even long after B's lease expired: only an explicit claim can bring A back
    with pytest.raises(pub.OwnershipRefusal, match="claim"):
        go(world, a, NOW + timedelta(hours=3))
    assert remote_publisher(world)["machine_id"] == b.ident.id


def test_released_marker_lets_the_next_mac_claim_without_force(world):
    a, b = mac(world, "Mac A"), mac(world, "Mac B")
    go(world, a)
    t = NOW + timedelta(minutes=1)
    assert own.release(pub.DESTINATION, now=t, state_dir=a.state, config_dir=a.cfg).startswith("RELEASED")
    p = remote_publisher(world)
    assert p["state"] == "released" and p["epoch"] == 1 and p["machine_id"] == a.ident.id
    assert mi.load_identity(a.cfg).role == "reader"
    assert go(world, a, t + timedelta(minutes=5)).startswith("SKIPPED")      # A no longer publishes
    with pytest.raises(pub.OwnershipRefusal, match="released"):               # B must still claim explicitly
        go(world, b, t)
    claim(world, b, t)                                                        # no force needed
    assert remote_publisher(world)["epoch"] == 2 and remote_publisher(world)["state"] == "active"
    assert go(world, b, t + timedelta(minutes=4)).startswith("PUBLISHED")


def test_release_by_a_non_owner_never_touches_the_remote(world):
    a, b = mac(world, "Mac A"), mac(world, "Mac B")
    go(world, a)
    before = remote_text(world)
    msg = own.release(pub.DESTINATION, now=NOW, state_dir=b.state, config_dir=b.cfg)
    assert "left untouched" in msg and remote_text(world) == before
    assert mi.load_identity(b.cfg).role == "reader"


def test_legacy_feed_fresh_is_protected_old_needs_claim(world):
    a = mac(world, "Mac A")
    push_remote(world, legacy(NOW - timedelta(minutes=5)))
    with pytest.raises(pub.OwnershipRefusal, match="recently"):
        go(world, a)
    with pytest.raises(own.OwnershipError, match="legacy"):
        claim(world, a)
    claim(world, a, force_takeover=True, confirm="legacy")
    assert remote_publisher(world)["epoch"] == 1
    assert go(world, a, NOW + timedelta(minutes=4)).startswith("PUBLISHED")


def test_legacy_feed_older_than_the_lease_needs_only_a_claim(world):
    a = mac(world, "Mac A")
    push_remote(world, legacy(NOW - timedelta(hours=2)))
    with pytest.raises(pub.OwnershipRefusal, match="claim"):
        go(world, a)
    assert remote_commits(world) == 1
    claim(world, a)
    assert go(world, a, NOW + timedelta(minutes=4)).startswith("PUBLISHED")


def test_corrupt_remote_fails_closed_and_forced_claim_can_repair(world):
    a = mac(world, "Mac A")
    push_remote(world, "{not json")
    with pytest.raises(pub.PublishError, match="malformed"):
        go(world, a)
    push_remote(world, json.dumps({"exported_at": NOW.isoformat(), "publisher": {"machine_id": "zzz"}}))
    with pytest.raises(pub.OwnershipRefusal, match="malformed"):
        go(world, a, NOW + timedelta(minutes=10))
    with pytest.raises(own.OwnershipError):
        claim(world, a)
    claim(world, a, force_takeover=True, confirm="corrupt")
    assert remote_publisher(world)["machine_id"] == a.ident.id


def test_two_macs_racing_on_one_remote_exactly_one_wins(world, monkeypatch):
    a, b = mac(world, "Mac A"), mac(world, "Mac B")
    real, fired = pub.cmd, []

    def spy(args, **kw):
        if "push" in args and not fired:
            fired.append(1)
            go(world, b)                       # B pushes first, between A's decision and A's push
        return real(args, **kw)

    monkeypatch.setattr(pub, "cmd", spy)
    with pytest.raises(pub.OwnershipRefusal):    # A's push is rejected; the re-clone shows B owns it; A re-decides
        go(world, a)
    assert remote_publisher(world)["machine_id"] == b.ident.id and remote_commits(world) == 1


def test_race_between_publisher_and_claimer_never_leaves_two_owners(world, monkeypatch):
    a, b = mac(world, "Mac A"), mac(world, "Mac B")
    go(world, a)
    late = NOW + timedelta(minutes=30)
    real, fired = pub.cmd, []

    def spy(args, **kw):
        if "push" in args and not fired:
            fired.append(1)
            claim(world, b, late)               # B claims the expired lease while A is mid-publish
        return real(args, **kw)

    monkeypatch.setattr(pub, "cmd", spy)
    # A's own lease is expired but nobody had claimed when A started: A decides 'owner', loses the push race, re-decides
    with pytest.raises(pub.OwnershipRefusal):
        go(world, a, late)
    assert remote_publisher(world)["machine_id"] == b.ident.id and remote_publisher(world)["epoch"] == 2


def test_reader_role_never_clones_or_writes(world, monkeypatch):
    r = mac(world, "Mac R", role="reader")
    monkeypatch.setattr(pub, "cmd", lambda *a, **k: pytest.fail("a reader must not run any git/gh command"))
    assert go(world, r).startswith("SKIPPED: this Mac is not a publisher")
    assert not r.state.exists()


def test_uninitialised_mac_never_writes(world, monkeypatch):
    monkeypatch.setattr(pub, "cmd", lambda *a, **k: pytest.fail("no identity, no network"))
    out = pub.publish(world.src, pub.DESTINATION, for_real=True, state_dir=world.tmp / "s", now=NOW,
                      config_dir=world.tmp / "empty")
    assert out.startswith("SKIPPED")


def test_local_check_works_for_a_reader(world):
    r = mac(world, "Mac R", role="reader")
    out = pub.publish(world.src, pub.DESTINATION, for_real=False, state_dir=r.state, now=NOW, config_dir=r.cfg)
    assert out.startswith("LOCAL CHECK OK")


def test_clone_outage_backs_off_and_keeps_ownership_state(world):
    a = mac(world, "Mac A")
    go(world, a)
    owner_before = pub.load_state(a.state)["ownership"]
    moved = world.tmp / "gone.git"
    world.bare.rename(moved)
    t = NOW + timedelta(minutes=10)
    with pytest.raises(pub.PublishError, match="clone"):
        go(world, a, t)
    state = pub.load_state(a.state)
    assert state["consecutive_failures"] == 1 and state["ownership"] == owner_before
    assert go(world, a, t + timedelta(seconds=10)).startswith("SKIPPED: backing off")
    moved.rename(world.bare)
    world.src.write_text(json.dumps(snapshot(t + timedelta(minutes=2))))
    assert go(world, a, t + timedelta(minutes=2)).startswith("PUBLISHED")
    assert pub.load_state(a.state)["consecutive_failures"] == 0


def test_push_outage_is_a_clean_failure(world):
    a = mac(world, "Mac A")
    go(world, a)
    objects = world.bare / "objects"
    objects.chmod(0o500)
    try:
        t = NOW + timedelta(minutes=12)
        world.src.write_text(json.dumps(snapshot(t, title="changed", activity_at=t)))
        with pytest.raises(pub.PublishError, match="push"):
            go(world, a, t)
    finally:
        objects.chmod(0o700)
    state = pub.load_state(a.state)
    assert state["consecutive_failures"] == 1 and state["ownership"]["state"] == "owner"
    assert remote_publisher(world)["epoch"] == 1


def test_paths_with_spaces_work_end_to_end(world):
    base = world.tmp / "my macs & stuff"
    base.mkdir()
    a, b = mac(world, "Mac A", base=base), mac(world, "Mac B", base=base)
    assert go(world, a).startswith("PUBLISHED")
    claim(world, b, NOW + timedelta(minutes=1), force_takeover=True, confirm=a.ident.id)
    assert remote_publisher(world)["machine_id"] == b.ident.id
    assert own.release(pub.DESTINATION, now=NOW + timedelta(minutes=2), state_dir=b.state,
                       config_dir=b.cfg).startswith("RELEASED")


def test_claim_is_refused_for_a_public_destination(world, monkeypatch):
    a = mac(world, "Mac A")
    monkeypatch.setenv("FAKE_VISIBILITY", "PUBLIC")
    with pytest.raises(pub.PublishError, match="PRIVATE"):
        claim(world, a)


def test_claim_without_an_existing_feed_only_sets_the_role(world):
    a = mac(world, "Mac A", role="reader")
    assert "NO FEED YET" in claim(world, a) or "role=publisher" in claim(world, a)
    assert mi.load_identity(a.cfg).role == "publisher"
    assert go(world, a).startswith("PUBLISHED") and remote_publisher(world)["epoch"] == 1


# ------------------------------------------------------------------ FeedHealth

HEALTH_KEYS = {"status", "last_published_at", "last_observed_at", "trusted_until", "owner", "owned_by_this_machine",
               "last_error"}


def test_feed_health_has_exactly_the_documented_shape_in_every_state(world):
    a, r = mac(world, "Mac A"), mac(world, "Mac R", role="reader")
    h = own.feed_health(a.state, NOW, a.cfg)
    assert set(h) == HEALTH_KEYS and h["status"] == "unpublished" and h["owner"] is None
    go(world, a)
    h = own.feed_health(a.state, NOW + timedelta(minutes=5), a.cfg)
    assert set(h) == HEALTH_KEYS and h["status"] == "fresh" and h["owned_by_this_machine"] is True
    assert h["owner"] == {"machine_id": a.ident.id, "label": "Mac A", "epoch": 1}
    assert h["last_published_at"] == NOW.isoformat() and h["trusted_until"]
    assert own.feed_health(a.state, NOW + timedelta(hours=1), a.cfg)["status"] == "stale"
    h = own.feed_health(r.state, NOW, r.cfg)
    assert set(h) == HEALTH_KEYS and h["status"] == "disabled" and h["owned_by_this_machine"] is False
    st = {}
    own.record_remote_view(st, json.loads(remote_text(world)), NOW)
    r.state.mkdir(exist_ok=True)
    pub.save_state(r.state, st)
    h = own.feed_health(r.state, NOW + timedelta(minutes=1), r.cfg)
    assert h["owner"]["machine_id"] == a.ident.id and h["owned_by_this_machine"] is False and h["status"] in {"fresh", "stale"}
    assert own.feed_health(world.tmp / "nothing", NOW, world.tmp / "nocfg")["status"] == "disabled"


def test_feed_health_surfaces_the_last_error_truncated(world):
    a = mac(world, "Mac A")
    a.state.mkdir()
    pub.save_state(a.state, {"last_error": "x" * 500})
    assert len(own.feed_health(a.state, NOW, a.cfg)["last_error"]) == 160


# ------------------------------------------------------------------ CLI

def test_cli_handover_prints_both_sides(capsys):
    assert own.main(["handover"]) == 0
    out = capsys.readouterr().out
    for needle in ("release", "claim", "publisher_launchd disable", "publisher_launchd enable", "20 min"):
        assert needle in out


def test_cli_status_offline_and_wrong_repo(world, capsys, monkeypatch):
    a = mac(world, "Mac A")
    go(world, a)
    assert own.main(["status", "--offline", "--state-dir", str(a.state), "--config-dir", str(a.cfg)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["machine"]["id"] == a.ident.id and out["feed_health"]["owned_by_this_machine"] is True
    with pytest.raises(SystemExit):
        own.main(["status", "--repo", "ManpreetS2/agent-mindmap"])


def test_cli_claim_error_is_reported_not_raised(world, capsys):
    a, b = mac(world, "Mac A"), mac(world, "Mac B")
    go(world, a, datetime.now(UTC))                                   # main() uses the real clock
    code = own.main(["claim", "--state-dir", str(b.state), "--config-dir", str(b.cfg)])
    assert code == 1 and "--force-takeover" in capsys.readouterr().out


def test_status_reads_remote_read_only_through_the_injected_runner():
    calls = []

    def runner(args, env):
        calls.append(args)
        return 0, json.dumps({"exported_at": NOW.isoformat()}), ""

    kind, data = own.fetch_remote_feed(pub.DESTINATION, runner)
    assert kind == "ok" and data["exported_at"] and calls[0][:2] == ["gh", "api"]
    assert own.fetch_remote_feed(pub.DESTINATION, lambda a, e: (1, "", "HTTP 404 Not Found"))[0] == "missing"
    assert own.fetch_remote_feed(pub.DESTINATION, lambda a, e: (1, "", "boom"))[0] == "error"
    assert own.fetch_remote_feed(pub.DESTINATION, lambda a, e: (0, "nope", ""))[0] == "malformed"
