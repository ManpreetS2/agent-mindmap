"""Regression tests for the four findings of the independent Opus review of publisher_ownership.py."""
from datetime import UTC, datetime, timedelta

import pytest

from tools import machine_identity as mi
from tools import publisher_ownership as own

NOW = datetime(2026, 10, 24, 7, 0, tzinfo=UTC)
ME = mi.MachineIdentity(id="mac-aaaaaaaa", label="Mac A", role="publisher", platform="darwin-arm64")
OTHER = "mac-bbbbbbbb"


def feed(machine=OTHER, epoch=3, lease=None, state="active"):
    lease = lease if lease is not None else (NOW + timedelta(minutes=10)).isoformat()
    return {"publisher": {"machine_id": machine, "label": "Mac B", "epoch": epoch, "lease_expires_at": lease, "state": state},
            "exported_at": NOW.isoformat()}


# 1) crafted timestamps must fail closed with a decision, never an uncaught OverflowError
@pytest.mark.parametrize("stamp", ["9999-12-31T23:59:59-23:59", "0001-01-01T00:00:00+01:00", "0001-01-01T00:00:00+23:59"])
def test_extreme_timestamps_do_not_raise(stamp):
    assert own.parse_time(stamp) is None
    assert own.decide(feed(lease=stamp), ME, NOW).action == "refuse"                      # malformed owner record
    legacy = own.decide({"exported_at": stamp}, ME, NOW)                                  # legacy feed with a hostile stamp
    assert legacy.action in {"refuse", "claim_required"}
    assert own.decide(feed(lease=stamp), ME, NOW, claiming=True).action == "refuse"       # needs the typed override


def test_a_future_exported_at_never_suppresses_the_heartbeat():
    """Found while pinning finding 1: a far-future remote stamp made the age negative, so an unchanged feed was never
    re-stamped (silent heartbeat starvation => the feed goes stale while looking up to date)."""
    from tools.publish_observability import should_publish
    for stamp in ("9999-12-31T23:59:59-23:59", (NOW + timedelta(days=3)).isoformat(), "0001-01-01T00:00:00+23:59"):
        assert should_publish({"exported_at": stamp, "x": 1}, {"x": 1}, now=NOW) is True
    fresh = (NOW - timedelta(seconds=30)).isoformat()
    assert should_publish({"exported_at": fresh, "x": 1}, {"x": 1}, now=NOW) is False  # normal suppression still works


# 2) epoch is bounded
@pytest.mark.parametrize("epoch", [10**400, 2**31, 2**31 + 5, 0, -1, True, 1.5, "3"])
def test_out_of_range_epoch_is_malformed(epoch):
    assert own.validate_publisher(feed(epoch=epoch)["publisher"], NOW) is None
    assert own.decide(feed(epoch=epoch), ME, NOW).code == "corrupt"


def test_epoch_just_inside_the_bound_is_valid_and_a_forced_claim_cannot_overflow():
    assert own.validate_publisher(feed(epoch=2**31 - 1)["publisher"], NOW) is not None
    d = own.decide(feed(epoch=10**400), ME, NOW, claiming=True, force_takeover=True)
    assert d.action == "publish" and d.epoch == 1  # a huge/garbage prior epoch restarts at 1 instead of growing


# 3) a publisher-role Mac that claimed an empty repo and lost the first write learns it was superseded
def test_lost_empty_repo_race_is_recorded_as_superseded():
    d = own.decide(feed(epoch=1), ME, NOW, local_epoch=None)
    assert d.action == "refuse" and d.code == "foreign_active"
    assert d.superseded_by == {"machine_id": OTHER, "label": "Mac B", "epoch": 1}


def test_a_plain_reader_is_not_told_it_was_superseded():
    reader = mi.MachineIdentity(id="mac-cccccccc", label="Mac C", role="reader", platform="darwin-arm64")
    assert own.decide(feed(epoch=1), reader, NOW, local_epoch=None).superseded_by is None


# 4) rollback detection works for the NEWER owner too, and a later claim outranks its own record
def test_foreign_owner_with_a_lower_epoch_than_my_record_is_a_rollback():
    d = own.decide(feed(epoch=2), ME, NOW, local_epoch=3)
    assert d.action == "refuse" and d.code == "rollback"


def test_claim_after_rollback_outranks_both_epochs():
    d = own.decide(feed(epoch=2, lease=(NOW - timedelta(minutes=1)).isoformat()), ME, NOW, claiming=True, local_epoch=5)
    assert d.action == "publish" and d.epoch == 6
