"""session.account: which T3 provider instance ran a thread (two separate Claude memberships stay distinguishable)."""
import copy

from ingest.build import validate_activity
from ingest.t3 import T3Projection, read_demo

NOW = 1792699200


def _raw(instances):
    raw = read_demo()
    base = raw["threads"][0]
    raw["providers"] = [
        {"providerInstanceId": i, "driverKind": "claudeAgent", "displayName": label} for i, label in instances.items()
    ]
    raw["threads"] = [
        {**copy.deepcopy(base), "threadId": f"thread-{n}", "providerInstanceId": i, "parentThreadId": None}
        for n, i in enumerate(instances)
    ]
    return raw


def test_two_claude_memberships_have_distinct_accounts():
    activity = T3Projection("local").snapshot(_raw({"claudeAgent": "Claude", "claudeAgent_2": "Claude2"}), NOW)
    validate_activity(activity)
    accounts = {n["session"]["thread_id"]: n["session"]["account"] for n in activity["nodes"]}
    assert accounts["thread-0"] == {"id": "claudeAgent", "label": "Claude"}
    assert accounts["thread-1"] == {"id": "claudeAgent_2", "label": "Claude2"}
    assert {n["session"]["provider"] for n in activity["nodes"]} == {"Claude Code"}  # provider alone cannot tell them apart


def test_account_label_is_sanitised_and_falls_back_to_id():
    raw = _raw({"claudeAgent": "/Users/someone/private", "claudeAgent_2": None})
    activity = T3Projection("local").snapshot(raw, NOW)
    validate_activity(activity)
    by_id = {n["session"]["account"]["id"]: n["session"]["account"]["label"] for n in activity["nodes"]}
    assert "/Users" not in by_id["claudeAgent"] and by_id["claudeAgent_2"] == "claudeAgent_2"


def test_unsafe_or_missing_instance_id_means_no_account_not_an_invented_one():
    raw = _raw({"claudeAgent": "Claude"})
    raw["threads"][0]["providerInstanceId"] = "/Users/me/x"
    raw["providers"][0]["providerInstanceId"] = "/Users/me/x"
    activity = T3Projection("local").snapshot(raw, NOW)
    validate_activity(activity)
    assert activity["nodes"][0]["session"]["account"] is None
    raw["threads"][0].pop("providerInstanceId")
    assert T3Projection("local").snapshot(raw, NOW)["nodes"][0]["session"]["account"] is None
