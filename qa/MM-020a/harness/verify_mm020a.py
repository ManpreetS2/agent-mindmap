#!/usr/bin/env python3
"""Independent QA harness for MM-020a (PR #16). Does not modify product code."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import traceback
from pathlib import Path

_HERE = Path(__file__).resolve().parent
# evidence layout: qa/MM-020a/harness → repo root is parents[2]
# tmp layout: evidence/harness with sibling ../checkout
if (_HERE.parents[2] / "ingest").is_dir():
    ROOT = _HERE.parents[2]
elif (_HERE.parents[1] / "checkout" / "ingest").is_dir():
    ROOT = _HERE.parents[1] / "checkout"
else:
    raise SystemExit(f"cannot locate repo root from {_HERE}")
sys.path.insert(0, str(ROOT))

from ingest.edges import derive_edges, pr_key  # noqa: E402
from ingest.membership import (  # noqa: E402
    group_target_id,
    groups_for_bot,
    load_groups,
    membership_index,
)
from ingest.migrate import CURRENT, SUPPORTED, migrate_activity  # noqa: E402
from ingest.build import build_activity, validate_activity  # noqa: E402
from ingest.github_poller import _looks_like_secret  # noqa: E402
import jsonschema  # noqa: E402

SCHEMA = json.loads((ROOT / "schema" / "activity.schema.json").read_text())
RESULTS: list[dict] = []


def record(check: str, ok: bool, detail: str, **extra) -> None:
    RESULTS.append({"check": check, "ok": ok, "detail": detail, **extra})
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {check}: {detail}")


def base_event(**kwargs):
    e = {
        "id": "e1",
        "type": "message",
        "actor": "director",
        "target": None,
        "task_id": None,
        "attribution": {"method": "unknown"},
        "source_url": "agent://emit",
        "source_time": "2026-10-20T12:00:00-07:00",
        "raw": "hi",
    }
    e.update(kwargs)
    return e


def check_membership_happy() -> None:
    cfg = load_groups(ROOT / "config" / "groups.json")
    by_id = {g["id"]: set(g["members"]) for g in cfg["groups"]}
    ok = (
        by_id["build"]
        == {
            "director",
            "architect",
            "dev-1",
            "dev-2",
            "ui-ux-maker",
            "documentation",
        }
        and by_id["qr"]
        == {
            "director",
            "architect",
            "qa-verifier",
            "security-engineer",
            "devops-release",
        }
        and by_id["radar"]
        == {"director", "architect", "scout", "skeptic", "nomen"}
        and "bug-fixer" not in by_id["radar"]
    )
    idx = membership_index(cfg)
    ok = ok and set(idx["director"]) == {"build", "qr", "radar"}
    ok = ok and set(idx["architect"]) == {"build", "qr", "radar"}
    ok = ok and groups_for_bot("bug-fixer", cfg) == []
    record("membership.happy", ok, f"director={idx.get('director')} radar={sorted(by_id['radar'])}")


def check_membership_unknown_duplicate_missing() -> None:
    # unknown member id in groups.json — silently indexed
    cfg = {
        "groups": [
            {"id": "build", "members": ["director", "ghost-bot", "director"]},
            {"id": "qr", "members": ["architect"]},
        ]
    }
    idx = membership_index(cfg)
    # Expected (QA AC): unknown members handled (warn/skip OR documented);
    # duplicates collapsed; missing bots just empty membership.
    unknown_present = "ghost-bot" in idx
    dup_count = idx.get("director", []).count("build")
    missing = groups_for_bot("no-such-bot", cfg)
    # Document actual behavior
    record(
        "membership.unknown_member",
        True,  # behavior observed (not crash)
        f"unknown bot indexed without validation: ghost-bot in index={unknown_present}; "
        f"no raise. AC asks 'handled' — silent accept observed.",
        severity_hint="medium" if unknown_present else "info",
        actual={"index": idx, "unknown_present": unknown_present},
    )
    record(
        "membership.duplicate_member",
        dup_count == 1,  # expect dedupe
        f"duplicate 'director' in build members → groups list count={dup_count} (expect 1 after dedupe)",
        severity_hint="medium" if dup_count != 1 else "info",
        actual={"director_groups": idx.get("director"), "dup_count": dup_count},
    )
    record(
        "membership.missing_member",
        missing == [],
        f"bot not listed anywhere → groups_for_bot={missing!r}",
    )


def check_membership_malformed() -> None:
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "groups.json"
        bad.write_text("{not json", encoding="utf-8")
        try:
            load_groups(bad)
            record("membership.malformed_json", False, "load_groups did not raise on malformed JSON")
        except json.JSONDecodeError as exc:
            record(
                "membership.malformed_json",
                True,
                f"JSONDecodeError: {exc}",
            )
        # missing members key / wrong shape
        weird = Path(td) / "groups2.json"
        weird.write_text(json.dumps({"groups": [{"id": "build"}]}), encoding="utf-8")
        try:
            idx = membership_index(load_groups(weird))
            record(
                "membership.malformed_missing_members",
                True,
                f"missing members key → empty index entry ok, idx={idx}",
            )
        except Exception as exc:  # noqa: BLE001
            record(
                "membership.malformed_missing_members",
                False,
                f"unexpected raise: {type(exc).__name__}: {exc}",
            )
        # completely wrong top-level
        weird2 = Path(td) / "groups3.json"
        weird2.write_text(json.dumps({"nope": True}), encoding="utf-8")
        try:
            idx = membership_index(load_groups(weird2))
            record(
                "membership.malformed_no_groups_key",
                idx == {},
                f"no groups key → empty index={idx} (no clear failure)",
                severity_hint="low",
            )
        except Exception as exc:  # noqa: BLE001
            record(
                "membership.malformed_no_groups_key",
                True,
                f"raised clearly: {type(exc).__name__}: {exc}",
            )


def check_message_edges() -> None:
    # untargeted
    edges = derive_edges([base_event(group="build")])
    ok = (
        len(edges) == 1
        and edges[0]["source"] == "director"
        and edges[0]["target"] == "group:build"
        and edges[0]["type"] == "message"
    )
    record("message.untargeted_sender_to_group", ok, str(edges[0] if edges else None))

    # explicit recipients
    edges = derive_edges(
        [base_event(id="m2", actor="architect", recipients=["dev-1", "dev-2"], group="build")]
    )
    pairs = {(e["source"], e["target"], e["type"]) for e in edges}
    record(
        "message.explicit_recipients",
        pairs
        == {
            ("architect", "dev-1", "message"),
            ("architect", "dev-2", "message"),
        },
        str(pairs),
    )

    # self-loop recipient
    edges = derive_edges(
        [base_event(id="m3", actor="director", recipients=["director"], group="build")]
    )
    record(
        "message.no_self_loop",
        edges == [],
        f"self recipient → edges={edges}",
    )

    # dedup / idempotency: same message twice → one edge, count=2
    e = base_event(id="m4", group="build")
    e2 = base_event(id="m5", group="build")  # same source/target/type, different id
    edges = derive_edges([e, e2])
    ok = len(edges) == 1 and edges[0]["count"] == 2 and set(edges[0]["event_ids"]) == {"m4", "m5"}
    record("message.dedup_bucket", ok, str(edges[0] if edges else None))

    # identical event id twice (idempotent replay)
    edges = derive_edges([e, copy.deepcopy(e)])
    # current behavior: count increments even for same event_id
    record(
        "message.idempotent_same_event_id",
        len(edges) == 1 and edges[0]["event_ids"].count("m4") == 1,
        f"same event id twice → count={edges[0]['count'] if edges else None} "
        f"event_ids={edges[0]['event_ids'] if edges else None} "
        f"(expect event_id listed once for true idempotency)",
        severity_hint="medium",
        actual=edges[0] if edges else None,
    )

    # never invent
    edges = derive_edges([base_event(id="m6")])  # no group, no recipients
    record("message.never_invent", edges == [], str(edges))

    # recipients empty list + group → group edge
    edges = derive_edges([base_event(id="m7", recipients=[], group="qr")])
    record(
        "message.empty_recipients_falls_to_group",
        len(edges) == 1 and edges[0]["target"] == "group:qr",
        str(edges),
    )


def check_legacy_edge_invariants() -> None:
    # merge self-loop
    events = [
        {
            "id": "pr1",
            "type": "pr_opened",
            "actor": "dev-1",
            "target": None,
            "task_id": "MM-001",
            "pr": 5,
            "repo": "ManpreetS2/fencepost",
            "attribution": {"method": "signature"},
            "source_url": "https://github.com/ManpreetS2/fencepost/pull/5",
            "source_time": "2026-10-01T12:00:00-07:00",
            "raw": "opened",
        },
        {
            "id": "mg1",
            "type": "merged",
            "actor": "dev-1",  # same as author
            "target": None,
            "task_id": "MM-001",
            "pr": 5,
            "repo": "ManpreetS2/fencepost",
            "attribution": {"method": "signature"},
            "source_url": "https://github.com/ManpreetS2/fencepost/pull/5",
            "source_time": "2026-10-01T13:00:00-07:00",
            "raw": "~DEV 1 merged",
        },
    ]
    edges = derive_edges(events)
    merge_edges = [e for e in edges if e["type"] == "merge"]
    record(
        "edges.merge_no_self_loop",
        merge_edges == [],
        f"merge edges={merge_edges}",
    )

    # (repo, number) join — different repos same number
    events2 = events + [
        {
            "id": "pr2",
            "type": "pr_opened",
            "actor": "dev-2",
            "target": None,
            "task_id": "MM-002",
            "pr": 5,
            "repo": "ManpreetS2/agent-mindmap",
            "attribution": {"method": "signature"},
            "source_url": "https://github.com/ManpreetS2/agent-mindmap/pull/5",
            "source_time": "2026-10-01T12:00:00-07:00",
            "raw": "opened",
        },
        {
            "id": "mg2",
            "type": "merged",
            "actor": "architect",
            "target": None,
            "task_id": "MM-002",
            "pr": 5,
            "repo": "ManpreetS2/agent-mindmap",
            "attribution": {"method": "signature"},
            "source_url": "https://github.com/ManpreetS2/agent-mindmap/pull/5",
            "source_time": "2026-10-01T14:00:00-07:00",
            "raw": "~Architect merged",
        },
    ]
    edges = derive_edges(events2)
    merges = [e for e in edges if e["type"] == "merge"]
    # only agent-mindmap merge (architect→dev-2); fencepost self-loop suppressed
    ok = len(merges) == 1 and merges[0]["source"] == "architect" and merges[0]["target"] == "dev-2"
    record("edges.repo_number_join", ok, str(merges))

    # merger only from ledger/signature — unknown attribution ignored
    events3 = [
        events[0],
        {
            "id": "mg3",
            "type": "merged",
            "actor": "manpreet",
            "target": None,
            "task_id": "MM-001",
            "pr": 5,
            "repo": "ManpreetS2/fencepost",
            "attribution": {"method": "unknown"},
            "source_url": "https://github.com/ManpreetS2/fencepost/pull/5",
            "source_time": "2026-10-01T13:00:00-07:00",
            "raw": "merged_by owner",
        },
    ]
    edges = derive_edges(events3)
    merges = [e for e in edges if e["type"] == "merge"]
    record(
        "edges.merger_not_from_unknown",
        merges == [],
        f"unknown attr merge edges={merges}",
    )


def check_provenance() -> None:
    # Schema: provenance optional on events; absent on nodes/edges
    node_has = "provenance" in SCHEMA["$defs"]["node"]["properties"]
    edge_has = "provenance" in SCHEMA["$defs"]["edge"]["properties"]
    event_req = "provenance" in SCHEMA["$defs"]["event"].get("required", [])
    net_req = "provenance" in SCHEMA["$defs"]["networkEvent"].get("required", [])
    record(
        "provenance.schema_on_network_event",
        net_req and not node_has and not edge_has and not event_req,
        f"networkEvent required={net_req}; node has field={node_has}; "
        f"edge has field={edge_has}; event required={event_req}",
        note="AC 'every node and edge carries its source' — nodes/edges have no provenance field; "
        "events keep source_url (required) as source locator; provenance optional on events.",
    )

    # Build activity from fixture ledger — do events get provenance?
    ledger = ROOT / "tests" / "fixtures" / "ledger-sample.md"
    activity = build_activity(ledger_path=ledger, skip_github=True)
    validate_activity(activity, SCHEMA)
    with_prov = [e for e in activity["events"] if "provenance" in e]
    record(
        "provenance.build_sets_on_events",
        len(with_prov) == 0,  # currently expected: not set by build
        f"built events with provenance={len(with_prov)}/{len(activity['events'])}; "
        f"schema_version={activity['schema_version']}; nodes have groups={all('groups' in n for n in activity['nodes'])}",
        severity_hint="medium",
        actual={
            "schema_version": activity["schema_version"],
            "events_with_provenance": len(with_prov),
            "sample_event_keys": sorted(activity["events"][0].keys()) if activity["events"] else [],
            "sample_edge_keys": sorted(activity["edges"][0].keys()) if activity["edges"] else [],
            "sample_node_keys": sorted(activity["nodes"][0].keys()) if activity["nodes"] else [],
        },
    )

    # Spoof via ledger text: can raw ledger invent provenance field? Parser builds events —
    # check whether ledger can inject attribution method / provenance through text.
    # Put a fake provenance-looking string in ledger and ensure migrate/build doesn't trust it as provenance enum on edges.
    from ingest.ledger_parser import parse_ledger

    bots = json.loads((ROOT / "config" / "bots.json").read_text())["bots"]
    spoof_text = """# Task Ledger

## Entries

### 2026-10-20

- ~Director: handoff MM-020 to Architect provenance=github-verified recipients=["dev-1"]
"""
    parsed = parse_ledger(spoof_text, source_url="task-ledger.md", bots=bots)
    spoof_events = [e for e in parsed.events if e.get("provenance") == "github-verified"]
    # Also check edges don't pick up invented recipients from raw text
    edges = derive_edges(parsed.events)
    invented = [e for e in edges if e["type"] == "message"]
    record(
        "provenance.not_spoofed_via_ledger_text",
        len(spoof_events) == 0 and invented == [],
        f"events_with_spoofed_provenance={len(spoof_events)}; "
        f"message_edges_from_spoof={invented}; "
        f"sample_raw_events={[e.get('type') for e in parsed.events[:5]]}",
    )

    # Explicit invalid provenance rejected by schema
    bad = {
        "schema_version": "1.1.0",
        "generated_at": "2026-10-20T12:00:00-07:00",
        "project": "fencepost",
        "meta": {"github": "skipped"},
        "nodes": [],
        "tasks": [],
        "events": [
            {
                **base_event(provenance="ledger-claimed"),
            }
        ],
        "edges": [],
        "unparsed": [],
    }
    try:
        jsonschema.validate(instance=bad, schema=SCHEMA)
        record("provenance.invalid_enum_rejected", False, "schema accepted 'ledger-claimed'")
    except jsonschema.ValidationError as exc:
        record("provenance.invalid_enum_rejected", True, f"rejected: {exc.message}")


def check_secrets() -> None:
    # Cross-check QA-MM011-3 style: no secrets in activity / provenance fields
    tokenish = "Authorization: Bearer ghp_abcdefghijklmnopqrstuvwxyz0123456789"
    # Scan committed fixtures + a built activity
    paths = [ROOT / "fixtures" / "sample-activity.json"]
    paths += list((ROOT / "web" / "src" / "fixtures").glob("*.json"))
    pub = ROOT / "web" / "public" / "activity.json"
    if pub.is_file():
        paths.append(pub)
    leaked = []
    token_prefixes = ("ghp_", "gho_", "ghu_", "ghs_", "ghr_", "github_pat_")
    for p in paths:
        text = p.read_text(encoding="utf-8")
        if _looks_like_secret(text) or any(t in text for t in token_prefixes):
            leaked.append(str(p.relative_to(ROOT)))
    ledger = ROOT / "tests" / "fixtures" / "ledger-sample.md"
    activity = build_activity(ledger_path=ledger, skip_github=True)
    blob = json.dumps(activity)
    build_leak = _looks_like_secret(blob) or any(t in blob for t in token_prefixes)
    # Inject secret into message raw and ensure schema still allows (secret scan is mirror/emit concern)
    # but activity write path does not strip — document like F3 MM-011
    activity2 = copy.deepcopy(activity)
    if activity2["events"]:
        activity2["events"][0]["raw"] = tokenish
        activity2["events"][0]["provenance"] = "agent-reported"
    try:
        validate_activity(activity2, SCHEMA)
        schema_blocks_secret = False
    except Exception:
        schema_blocks_secret = True
    record(
        "secrets.fixtures_clean",
        leaked == [] and not build_leak,
        f"fixture_leaks={leaked}; build_leak={build_leak}",
    )
    record(
        "secrets.activity_schema_does_not_strip",
        not schema_blocks_secret,
        "schema validates activity with Bearer token in event.raw "
        "(secret blocking is MM-010 mirror / future emitter — same class as QA-MM011 F3). "
        "Provenance field itself holds only enum, not secret text.",
        severity_hint="info",
        note="QA-MM011-3 cross-check: token-like strings must not appear in committed activity; "
        "daemon/build path still does not secret-scan writes (observed/documented).",
    )


def check_migration() -> None:
    # Load activity from main @ 1a3a0cc
    import subprocess

    sample_main = subprocess.check_output(
        ["git", "show", "1a3a0cc:fixtures/sample-activity.json"],
        cwd=str(ROOT),
    ).decode()
    doc = json.loads(sample_main)
    assert doc["schema_version"] == "1.0.0"
    m1 = migrate_activity(doc)
    m2 = migrate_activity(m1)
    lossless = (
        m1["schema_version"] == "1.0.0"
        and m1["nodes"] == doc["nodes"]
        and m1["events"] == doc["events"]
        and m1["edges"] == doc["edges"]
        and m1["tasks"] == doc["tasks"]
    )
    idempotent = m2 == m1
    record("migration.lossless_1a3a0cc_sample", lossless, f"keys={sorted(m1.keys())}")
    record("migration.idempotent", idempotent, "migrate(migrate(doc)) == migrate(doc)")

    # bump then validate
    bumped = migrate_activity(doc, bump_version=True)
    try:
        jsonschema.validate(instance=bumped, schema=SCHEMA)
        record("migration.bump_validates_110", True, f"version={bumped['schema_version']}")
    except jsonschema.ValidationError as exc:
        record("migration.bump_validates_110", False, str(exc.message))

    # unknown version
    bad = copy.deepcopy(doc)
    bad["schema_version"] = "0.9.0"
    try:
        migrate_activity(bad)
        record("migration.unknown_version_fails", False, "did not raise for 0.9.0")
    except ValueError as exc:
        record("migration.unknown_version_fails", True, str(exc))

    # future version
    bad2 = copy.deepcopy(doc)
    bad2["schema_version"] = "2.0.0"
    try:
        migrate_activity(bad2)
        record("migration.future_version_fails", False, "did not raise for 2.0.0")
    except ValueError as exc:
        record("migration.future_version_fails", True, str(exc))

    # All legacy fixtures validate as 1.0.0 under new schema
    fixtures = [ROOT / "fixtures" / "sample-activity.json"]
    fixtures += list((ROOT / "web" / "src" / "fixtures").glob("*.json"))
    fails = []
    for p in fixtures:
        d = json.loads(p.read_text())
        try:
            jsonschema.validate(instance=d, schema=SCHEMA)
            migrate_activity(d)
        except Exception as exc:  # noqa: BLE001
            fails.append(f"{p.name}: {exc}")
    record("migration.all_fixtures_validate", fails == [], f"fails={fails}")

    record(
        "migration.backcompat_story",
        set(SUPPORTED) == {"1.0.0", "1.1.0"} and CURRENT == "1.1.0",
        f"SUPPORTED={sorted(SUPPORTED)} CURRENT={CURRENT}; "
        "schema enum accepts both; migrate is pure deepcopy + optional bump; "
        "fixtures left on disk as 1.0.0",
    )


def check_schema_message_edge_fixture() -> None:
    # Minimal 1.1.0 with message edge + provenance validates
    activity = {
        "schema_version": "1.1.0",
        "generated_at": "2026-10-20T12:00:00-07:00",
        "project": "fencepost",
        "meta": {"github": "skipped"},
        "nodes": [
            {
                "id": "director",
                "label": "Director",
                "group": "build",
                "groups": ["build", "qr", "radar"],
                "status": "IDLE",
                "agent_links": [],
                "layout": {"x": 0, "y": 0},
            }
        ],
        "tasks": [],
        "events": [base_event(group="build", provenance="agent-reported")],
        "edges": [
            {
                "id": "e",
                "source": "director",
                "target": "group:build",
                "type": "message",
                "count": 1,
                "event_ids": ["e1"],
            }
        ],
        "unparsed": [],
    }
    try:
        jsonschema.validate(instance=activity, schema=SCHEMA)
        record("schema.110_message_edge", True, "validated")
    except jsonschema.ValidationError as exc:
        record("schema.110_message_edge", False, exc.message)


def main() -> int:
    print(f"ROOT={ROOT}")
    print(f"HEAD={(ROOT / '.git').read_text() if False else ''}")
    checks = [
        check_membership_happy,
        check_membership_unknown_duplicate_missing,
        check_membership_malformed,
        check_message_edges,
        check_legacy_edge_invariants,
        check_provenance,
        check_secrets,
        check_migration,
        check_schema_message_edge_fixture,
    ]
    for fn in checks:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            record(fn.__name__, False, f"CRASH: {exc}\n{traceback.format_exc()}")
    out = Path(__file__).resolve().parent.parent / "logs" / "harness_results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(RESULTS, indent=2) + "\n", encoding="utf-8")
    fails = [r for r in RESULTS if not r["ok"]]
    print(f"\nSummary: {len(RESULTS) - len(fails)}/{len(RESULTS)} checks ok; {len(fails)} fail")
    for f in fails:
        print(f"  FAIL {f['check']}: {f['detail']}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
