#!/usr/bin/env python3
"""Delta behavioral verification for MM-020a @ 82f2066 (verify-only)."""

from __future__ import annotations

import copy
import json
import sys
import traceback
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "checkout"
sys.path.insert(0, str(ROOT))

import jsonschema  # noqa: E402
from ingest.edges import derive_edges  # noqa: E402
from ingest.build import build_activity, validate_activity, merge_events  # noqa: E402
from ingest.membership import (  # noqa: E402
    group_target_id,
    load_groups,
    membership_index,
    resolve_membership,
)
from ingest.migrate import infer_provenance, migrate_activity  # noqa: E402
from ingest.github_poller import _looks_like_secret, GitHubPollResult  # noqa: E402

SCHEMA = json.loads((ROOT / "schema" / "activity.schema.json").read_text())
RESULTS: list[dict] = []


def record(check: str, ok: bool, detail: str, **extra) -> None:
    RESULTS.append({"check": check, "ok": ok, "detail": detail, **extra})
    print(f"[{'PASS' if ok else 'FAIL'}] {check}: {detail}")


def base_evt(**kw):
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
        "provenance": "agent-reported",
    }
    e.update(kw)
    return e


def activity_shell(events, *, version="1.1.0"):
    return {
        "schema_version": version,
        "generated_at": "2026-10-20T12:00:00-07:00",
        "project": "fencepost",
        "meta": {"github": "skipped"},
        "nodes": [],
        "tasks": [],
        "events": events,
        "edges": [],
        "unparsed": [],
    }


# --- (1) QA-MM020a-1 ---
def check_dedupe():
    known = {"director", "architect", "dev-1"}
    cfg = {
        "groups": [
            {
                "id": "build",
                "members": ["director", "director", "architect", "director"],
            },
            {
                "id": "qr",
                "members": ["director", "architect", "director"],
            },
            {
                "id": "radar",
                "members": ["architect", "director"],
            },
        ]
    }
    idx = membership_index(cfg, known_bot_ids=known)
    ok = (
        idx["director"] == ["build", "qr", "radar"]
        and idx["architect"] == ["build", "qr", "radar"]
        and idx["director"].count("build") == 1
        and idx["director"].count("qr") == 1
        and idx["architect"].count("build") == 1
    )
    record(
        "QA-MM020a-1.dedupe_within_and_across_groups",
        ok,
        f"director={idx.get('director')} architect={idx.get('architect')}",
        actual=idx,
    )


# --- (2) QA-MM020a-2 ---
def check_unknown_parked():
    cfg = {
        "groups": [
            {"id": "build", "members": ["director", "ghost-bot", "ghost-bot", "architect"]},
            {"id": "qr", "members": ["ghost-bot", "director"]},
        ]
    }
    known = {"director", "architect"}
    warn = StringIO()
    result = resolve_membership(cfg, known_bot_ids=known, warn_stream=warn)
    w = warn.getvalue()
    ok = (
        "ghost-bot" not in result.index
        and set(result.index) == {"director", "architect"}
        and {"bot_id": "ghost-bot", "group_id": "build"} in result.unknown_members
        and {"bot_id": "ghost-bot", "group_id": "qr"} in result.unknown_members
        and "ghost-bot" in w
        and ("parking" in w.lower() or "QA-MM020a-2" in w)
        and result.index["director"] == ["build", "qr"]
    )
    # no raise already implied
    record(
        "QA-MM020a-2.unknown_parked_with_warning",
        ok,
        f"unknown={result.unknown_members}; warn={w.strip()!r}; index={result.index}",
        actual={"unknown": result.unknown_members, "warn": w, "index": result.index},
    )


# --- (3) provenance required on 1.1.0 ---
def check_provenance_required():
    missing = activity_shell([base_evt()])
    del missing["events"][0]["provenance"]
    try:
        jsonschema.validate(instance=missing, schema=SCHEMA)
        record("provenance.1_1_missing_rejected", False, "schema accepted missing provenance")
    except jsonschema.ValidationError as exc:
        record("provenance.1_1_missing_rejected", True, exc.message)

    invalid = activity_shell([base_evt(provenance="ledger-claimed")])
    try:
        jsonschema.validate(instance=invalid, schema=SCHEMA)
        record("provenance.1_1_invalid_rejected", False, "schema accepted ledger-claimed")
    except jsonschema.ValidationError as exc:
        record("provenance.1_1_invalid_rejected", True, exc.message)

    valid = activity_shell([base_evt(provenance="observed")])
    try:
        jsonschema.validate(instance=valid, schema=SCHEMA)
        record("provenance.1_1_valid_accepted", True, "observed ok")
    except jsonschema.ValidationError as exc:
        record("provenance.1_1_valid_accepted", False, exc.message)

    # 1.0.0 still optional
    legacy = activity_shell(
        [
            {
                "id": "e1",
                "type": "note",
                "actor": "director",
                "target": None,
                "task_id": None,
                "attribution": {"method": "unknown"},
                "source_url": "build/task-ledger.md",
                "source_time": "2026-10-20T12:00:00-07:00",
                "raw": "no provenance",
            }
        ],
        version="1.0.0",
    )
    try:
        jsonschema.validate(instance=legacy, schema=SCHEMA)
        record("provenance.1_0_optional", True, "1.0.0 without provenance validates")
    except jsonschema.ValidationError as exc:
        record("provenance.1_0_optional", False, exc.message)


# --- (4) migration fill + idempotent ---
def check_migration_fill():
    import subprocess

    sample = json.loads(
        subprocess.check_output(
            ["git", "show", "1a3a0cc:fixtures/sample-activity.json"], cwd=str(ROOT)
        ).decode()
    )
    # without bump: unchanged 1.0.0
    m0 = migrate_activity(sample)
    ok0 = m0["schema_version"] == "1.0.0" and m0["events"] == sample["events"]
    record("migration.no_bump_leaves_10", ok0, f"version={m0['schema_version']}")

    bumped = migrate_activity(sample, bump_version=True)
    all_have = all(
        e.get("provenance") in {"observed", "agent-reported", "github-verified"}
        for e in bumped["events"]
    ) and all(
        e.get("provenance") in {"observed", "agent-reported", "github-verified"}
        for e in bumped["unparsed"]
    )
    # source rules spot-check on sample events
    rules_ok = True
    for e in bumped["events"]:
        expected = infer_provenance(
            {k: v for k, v in e.items() if k != "provenance"}
            if True
            else e
        )
        # Re-infer from original-ish fields: strip and recompute
        stripped = {k: v for k, v in e.items() if k != "provenance"}
        if infer_provenance(stripped) != e["provenance"]:
            # If already filled with valid enum, fill leaves it — check consistency with rules
            # For freshly filled from legacy (no prior provenance), must match infer
            pass
    # Better: compare against originals
    orig_by_id = {e["id"]: e for e in sample["events"]}
    mismatches = []
    for e in bumped["events"]:
        o = orig_by_id[e["id"]]
        want = infer_provenance(o)
        if e["provenance"] != want:
            mismatches.append((e["id"], e["provenance"], want))
    record(
        "migration.fill_by_source_rules",
        all_have and mismatches == [],
        f"all_have={all_have} mismatches={mismatches[:5]}",
        sample_counts={
            "agent-reported": sum(
                1 for e in bumped["events"] if e["provenance"] == "agent-reported"
            ),
            "github-verified": sum(
                1 for e in bumped["events"] if e["provenance"] == "github-verified"
            ),
        },
    )
    try:
        jsonschema.validate(instance=bumped, schema=SCHEMA)
        record("migration.bumped_validates_110", True, "ok")
    except jsonschema.ValidationError as exc:
        record("migration.bumped_validates_110", False, exc.message)

    # idempotent: migrate twice
    twice = migrate_activity(bumped)
    thrice = migrate_activity(migrate_activity(sample, bump_version=True))
    # compare provenance maps
    p1 = {e["id"]: e["provenance"] for e in bumped["events"]}
    p2 = {e["id"]: e["provenance"] for e in twice["events"]}
    p3 = {e["id"]: e["provenance"] for e in thrice["events"]}
    record(
        "migration.idempotent",
        p1 == p2 == p3 and twice["schema_version"] == "1.1.0",
        f"p1==p2==p3 ({len(p1)} events)",
    )

    # explicit github vs ledger vs signature cases
    gh = {
        "id": "g",
        "type": "pr_opened",
        "actor": "dev-1",
        "target": None,
        "task_id": "MM-001",
        "pr": 1,
        "repo": "ManpreetS2/agent-mindmap",
        "attribution": {"method": "unknown"},
        "source_url": "https://github.com/ManpreetS2/agent-mindmap/pull/1",
        "source_time": "2026-10-20T12:00:00-07:00",
        "raw": "opened",
    }
    led = {
        "id": "l",
        "type": "handoff",
        "actor": "architect",
        "target": "dev-1",
        "task_id": "MM-020",
        "attribution": {"method": "ledger_owner"},
        "source_url": "build/task-ledger.md#L1",
        "source_time": "2026-10-20T12:00:00-07:00",
        "raw": "handoff",
    }
    sig = {
        "id": "s",
        "type": "verdict",
        "actor": "qa-verifier",
        "target": None,
        "task_id": "MM-020",
        "pr": 1,
        "repo": "ManpreetS2/agent-mindmap",
        "verdict": "PASS",
        "attribution": {"method": "signature"},
        "source_url": "https://github.com/ManpreetS2/agent-mindmap/pull/1",
        "source_time": "2026-10-20T12:00:00-07:00",
        "raw": "PASS ~QA",
    }
    doc = activity_shell([gh, led, sig], version="1.0.0")
    b = migrate_activity(doc, bump_version=True)
    ok = (
        b["events"][0]["provenance"] == "github-verified"
        and b["events"][1]["provenance"] == "agent-reported"
        and b["events"][2]["provenance"] == "agent-reported"
    )
    record(
        "migration.github_vs_ledger_vs_signature",
        ok,
        f"provs={[e['provenance'] for e in b['events']]}",
    )

    # unknown/future still fail
    for ver in ("0.9.0", "2.0.0"):
        bad = copy.deepcopy(sample)
        bad["schema_version"] = ver
        try:
            migrate_activity(bad)
            record(f"migration.reject_{ver}", False, "did not raise")
        except ValueError as exc:
            record(f"migration.reject_{ver}", True, str(exc))


# --- regressions from earlier FAIL scope ---
def check_regressions():
    # happy membership
    cfg = load_groups(ROOT / "config" / "groups.json")
    idx = membership_index(cfg)
    ok = set(idx["director"]) == {"build", "qr", "radar"} and "bug-fixer" not in idx
    record("regression.multi_membership", ok, f"director={idx.get('director')}")

    # message edges
    edges = derive_edges([base_evt(group="build")])
    record(
        "regression.message_untargeted",
        len(edges) == 1
        and edges[0]["source"] == "director"
        and edges[0]["target"] == group_target_id("build"),
        str(edges[0] if edges else None),
    )
    edges = derive_edges(
        [base_evt(id="m2", actor="architect", recipients=["dev-1", "dev-2"], group="build")]
    )
    pairs = {(e["source"], e["target"], e["type"]) for e in edges}
    record(
        "regression.message_explicit",
        pairs
        == {("architect", "dev-1", "message"), ("architect", "dev-2", "message")},
        str(pairs),
    )
    edges = derive_edges([base_evt(id="m3", recipients=["director"])])
    record("regression.message_no_self_loop", edges == [], str(edges))
    edges = derive_edges([base_evt(id="m4")])  # no group
    record("regression.message_never_invent", edges == [], str(edges))

    # merge self-loop / repo join / merger unknown (abbreviated)
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
            "provenance": "agent-reported",
        },
        {
            "id": "mg1",
            "type": "merged",
            "actor": "dev-1",
            "target": None,
            "task_id": "MM-001",
            "pr": 5,
            "repo": "ManpreetS2/fencepost",
            "attribution": {"method": "signature"},
            "source_url": "https://github.com/ManpreetS2/fencepost/pull/5",
            "source_time": "2026-10-01T13:00:00-07:00",
            "raw": "merged",
            "provenance": "agent-reported",
        },
    ]
    merges = [e for e in derive_edges(events) if e["type"] == "merge"]
    record("regression.merge_no_self_loop", merges == [], str(merges))

    # build emits provenance
    act = build_activity(
        ledger_path=ROOT / "tests" / "fixtures" / "ledger-sample.md",
        skip_github=True,
    )
    try:
        validate_activity(act, SCHEMA)
        schema_ok = True
        err = ""
    except Exception as exc:  # noqa: BLE001
        schema_ok = False
        err = str(exc)
    prov_ok = all("provenance" in e for e in act["events"]) and act["schema_version"] == "1.1.0"
    record(
        "regression.build_emits_provenance_110",
        schema_ok and prov_ok,
        f"schema_ok={schema_ok} prov_ok={prov_ok} n_events={len(act['events'])} err={err[:120]}",
        sample_prov=sorted({e.get("provenance") for e in act["events"]}),
    )

    # secrets fixtures clean
    paths = [ROOT / "fixtures" / "sample-activity.json"] + list(
        (ROOT / "web" / "src" / "fixtures").glob("*.json")
    )
    leaked = [str(p.relative_to(ROOT)) for p in paths if _looks_like_secret(p.read_text())]
    record("regression.secrets_fixtures_clean", leaked == [], f"leaked={leaked}")

    # spoof ledger text still cannot invent provenance enum on parse path without migrate
    from ingest.ledger_parser import parse_ledger

    bots = json.loads((ROOT / "config" / "bots.json").read_text())["bots"]
    spoof = "# Task Ledger\n\n## Entries\n\n### 2026-10-20\n\n- ~Director: note provenance=github-verified\n"
    parsed = parse_ledger(spoof, source_url="task-ledger.md", bots=bots)
    spoofed = [e for e in parsed.events if e.get("provenance") == "github-verified"]
    record(
        "regression.provenance_not_spoofed_by_ledger_text",
        spoofed == [],
        f"spoofed={len(spoofed)} types={[e.get('type') for e in parsed.events[:3]]}",
    )

    # malformed groups.json
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "g.json"
        bad.write_text("{not", encoding="utf-8")
        try:
            load_groups(bad)
            record("regression.malformed_groups_json", False, "no raise")
        except json.JSONDecodeError as exc:
            record("regression.malformed_groups_json", True, str(exc)[:80])


def main() -> int:
    print(f"ROOT={ROOT} HEAD={(ROOT / '.git').read_text() if False else 'detached'}")
    for fn in (
        check_dedupe,
        check_unknown_parked,
        check_provenance_required,
        check_migration_fill,
        check_regressions,
    ):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            record(fn.__name__, False, f"CRASH: {exc}\n{traceback.format_exc()}")
    out = Path(__file__).resolve().parents[1] / "logs" / "delta_harness_results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(RESULTS, indent=2) + "\n")
    fails = [r for r in RESULTS if not r["ok"]]
    print(f"\nSummary: {len(RESULTS)-len(fails)}/{len(RESULTS)} ok; {len(fails)} fail")
    for f in fails:
        print(f"  FAIL {f['check']}: {f['detail']}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
