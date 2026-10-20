#!/usr/bin/env python3
"""
Independent QA verifier for MM-010 (PR #11).
Does not modify product code. Writes evidence under --outdir.
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("QA_ROOT", Path.cwd())).resolve()

FINDINGS: list[dict[str, Any]] = []
CHECKS: list[dict[str, Any]] = []


def record_check(name: str, result: str, detail: str = "", evidence: str = "") -> None:
    CHECKS.append({"name": name, "result": result, "detail": detail, "evidence": evidence})


def finding(
    *,
    component: str,
    expected: str,
    actual: str,
    repro: str,
    evidence: str,
    environment: str,
    severity: str,
    confidence: str,
    id: str,
) -> None:
    FINDINGS.append(
        {
            "id": id,
            "component": component,
            "expected": expected,
            "actual": actual,
            "repro": repro,
            "evidence": evidence,
            "environment": environment,
            "severity": severity,
            "confidence": confidence,
        }
    )


def run(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT), **kw)


def main() -> int:
    outdir = Path(sys.argv[1] if len(sys.argv) > 1 else "qa/MM-010/logs").resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    head = run(["git", "rev-parse", "HEAD"]).stdout.strip()
    env_desc = f"linux python={sys.version.split()[0]} cwd={ROOT} head={head}"

    sys.path.insert(0, str(ROOT))
    from ingest.build import build_activity, resolve_ledger_path, write_activity
    from ingest.edges import derive_edges, pr_key
    from ingest.github_poller import GhResponse, assert_no_credentials, _looks_like_secret
    from ingest.ledger_fetch import LEDGER_API_PATH, fetch_ledger_from_gh
    from tools.ledger_mirror import decide_flush, secret_line_numbers, sha256_text, load_state

    import jsonschema

    schema = json.loads((ROOT / "schema" / "activity.schema.json").read_text())
    activity_fixtures = [
        ROOT / "fixtures" / "sample-activity.json",
        *sorted((ROOT / "web" / "src" / "fixtures").glob("state-*.json")),
    ]
    fixture_ok = True
    fixture_lines: list[str] = []
    for fp in activity_fixtures:
        data = json.loads(fp.read_text())
        try:
            jsonschema.validate(instance=data, schema=schema)
            fixture_lines.append(f"PASS {fp.relative_to(ROOT)}")
        except Exception as exc:  # noqa: BLE001
            fixture_ok = False
            fixture_lines.append(f"FAIL {fp.relative_to(ROOT)}: {exc}")
            finding(
                id="QA-MM010-FIXTURE",
                component=str(fp.relative_to(ROOT)),
                expected="Validates against schema/activity.schema.json",
                actual=str(exc)[:500],
                repro=f"jsonschema.validate({fp.name})",
                evidence="\n".join(fixture_lines[-3:]),
                environment=env_desc,
                severity="HIGH",
                confidence="HIGH",
            )
    (outdir / "fixture_validation.txt").write_text("\n".join(fixture_lines) + "\n", encoding="utf-8")
    record_check(
        "fixture_schema_validation",
        "PASS" if fixture_ok else "FAIL",
        f"{len(activity_fixtures)} activity fixtures",
        "\n".join(fixture_lines),
    )

    # Required ledger path — no fixture default
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        env = os.environ.copy()
        env.pop("MINDMAP_LEDGER", None)
        assert resolve_ledger_path(None, env={}) is None
        proc = run(
            [sys.executable, "-m", "ingest", "--out", str(td_path / "a.json")],
            env=env,
        )
        excerpt = f"rc={proc.returncode}\nstdout={proc.stdout[:300]}\nstderr={proc.stderr[:500]}"
        (outdir / "missing_ledger_path.txt").write_text(excerpt, encoding="utf-8")
        src = (ROOT / "ingest" / "build.py").read_text()
        has_fixture_default = re.search(r'default\s*=\s*.*ledger-sample', src) is not None
        ok = (
            proc.returncode == 2
            and "MINDMAP_LEDGER" in proc.stderr
            and "provide --ledger" in proc.stderr
            and not has_fixture_default
        )
        record_check(
            "required_ledger_path_no_default",
            "PASS" if ok else "FAIL",
            excerpt[:200],
            excerpt,
        )
        if not ok:
            finding(
                id="QA-MM010-LEDGER-DEFAULT",
                component="ingest/build.py",
                expected="Exit 2 when --ledger and MINDMAP_LEDGER absent; no fixture default",
                actual=excerpt,
                repro="env -u MINDMAP_LEDGER python3 -m ingest --out /tmp/a.json",
                evidence=excerpt,
                environment=env_desc,
                severity="HIGH",
                confidence="HIGH",
            )

    # Malformed ledger
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        bad = td_path / "bad-ledger.md"
        bad.write_text("this is not a markdown table\n\x00 garbage {{{{\n", encoding="latin-1")
        out = td_path / "activity.json"
        proc = run(
            [
                sys.executable,
                "-m",
                "ingest",
                "--ledger",
                str(bad),
                "--out",
                str(out),
                "--skip-github",
            ],
        )
        excerpt = f"rc={proc.returncode}\nstderr={proc.stderr[:800]}\nexists={out.exists()}"
        if out.exists():
            act = json.loads(out.read_text())
            excerpt += f"\nmeta={act.get('meta')}\ntasks={len(act.get('tasks',[]))}"
            try:
                jsonschema.validate(instance=act, schema=schema)
                excerpt += "\nschema=ok"
            except Exception as exc:  # noqa: BLE001
                excerpt += f"\nschema=FAIL {exc}"
        (outdir / "malformed_ledger_path.txt").write_text(excerpt, encoding="utf-8")
        crashed = "Traceback" in proc.stderr and proc.returncode not in (0, 1, 2)
        record_check(
            "malformed_ledger_local",
            "PASS" if not crashed and (out.exists() or proc.returncode in (1, 2)) else "FAIL",
            "parser tolerates garbage or exits cleanly",
            excerpt,
        )

        class BadGh:
            def __call__(self, args: list[str], *, timeout: float = 60.0) -> GhResponse:
                return GhResponse(
                    status=200,
                    headers={"etag": '"x"'},
                    body=json.dumps(
                        {
                            "name": "ledger.md",
                            "path": "ledger.md",
                            "encoding": "base64",
                            "content": "!!!not-base64!!!",
                        }
                    ),
                )

        r = fetch_ledger_from_gh(cache_dir=td_path / "cache", runner=BadGh())
        excerpt2 = f"meta_ledger={r.meta_ledger} text={r.text!r} errors={r.errors}"
        (outdir / "malformed_ledger_gh.txt").write_text(excerpt2, encoding="utf-8")
        ok_gh = r.meta_ledger == "error" and r.text is None
        record_check("malformed_ledger_gh_decode", "PASS" if ok_gh else "FAIL", excerpt2, excerpt2)
        if not ok_gh:
            finding(
                id="QA-MM010-MALFORMED-GH",
                component="ingest/ledger_fetch.py",
                expected="meta_ledger=error and text=None on bad base64",
                actual=excerpt2,
                repro="fetch_ledger_from_gh with invalid base64 content",
                evidence=excerpt2,
                environment=env_desc,
                severity="MEDIUM",
                confidence="HIGH",
            )

    # Idempotent re-runs
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        ledger = td_path / "ledger.md"
        state = td_path / "state.json"
        payload = td_path / "payload.md"
        content = (
            "# L\n\n| Task ID | Project | Owner | Mode | Model | Status | Evidence |\n"
            "|---|---|---|---|---|---|---|\n| MM-010 | x | Architect | a | m | PLANNED | — |\n"
            "- 2026-10-20 Architect: assigned DEV 1 on MM-010.\n"
        )
        ledger.write_text(content, encoding="utf-8")
        digest = sha256_text(content)
        proc1 = run(
            [
                sys.executable,
                "tools/ledger_mirror.py",
                "--ledger",
                str(ledger),
                "--state",
                str(state),
                "--payload",
                str(payload),
                "--now",
                "2000000",
            ]
        )
        out1 = json.loads(proc1.stdout)
        mark = run(
            [
                sys.executable,
                "tools/ledger_mirror.py",
                "--mark-flushed",
                digest,
                "--state",
                str(state),
                "--ledger",
                str(ledger),
                "--now",
                "2000000",
            ]
        )
        proc2 = run(
            [
                sys.executable,
                "tools/ledger_mirror.py",
                "--ledger",
                str(ledger),
                "--state",
                str(state),
                "--payload",
                str(payload),
                "--force",
                "--now",
                "3000000",
            ]
        )
        out2 = json.loads(proc2.stdout)
        excerpt = f"first={out1}\nmark_rc={mark.returncode}\nsecond={out2}"
        (outdir / "idempotent_mirror.txt").write_text(excerpt, encoding="utf-8")
        ok = out1["flush"] is True and out2["flush"] is False and out2["reason"] == "unchanged"
        record_check("idempotent_mirror_rerun", "PASS" if ok else "FAIL", excerpt, excerpt)

        out_a = td_path / "a.json"
        out_b = td_path / "b.json"
        sample = ROOT / "tests" / "fixtures" / "ledger-sample.md"
        run(
            [
                sys.executable,
                "-m",
                "ingest",
                "--ledger",
                str(sample),
                "--out",
                str(out_a),
                "--skip-github",
            ]
        )
        run(
            [
                sys.executable,
                "-m",
                "ingest",
                "--ledger",
                str(sample),
                "--out",
                str(out_b),
                "--skip-github",
            ]
        )
        a = json.loads(out_a.read_text())
        b = json.loads(out_b.read_text())
        for d in (a, b):
            d.pop("generated_at", None)
        same = a == b
        (outdir / "idempotent_ingest.txt").write_text(f"equal_without_generated_at={same}\n", encoding="utf-8")
        record_check("idempotent_ingest_rerun", "PASS" if same else "FAIL", f"equal={same}", f"equal={same}")

    # PR joins keyed on (repo, number)
    events = [
        {
            "id": "o1",
            "type": "pr_opened",
            "actor": "dev-1",
            "repo": "ManpreetS2/fencepost",
            "pr": 5,
            "source": "github",
            "source_url": "https://github.com/ManpreetS2/fencepost/pull/5",
            "source_time": "2026-10-19T00:00:00Z",
            "attribution": {"method": "github_login", "confidence": "high"},
        },
        {
            "id": "o2",
            "type": "pr_opened",
            "actor": "dev-2",
            "repo": "ManpreetS2/agent-mindmap",
            "pr": 5,
            "source": "github",
            "source_url": "https://github.com/ManpreetS2/agent-mindmap/pull/5",
            "source_time": "2026-10-19T00:01:00Z",
            "attribution": {"method": "github_login", "confidence": "high"},
        },
        {
            "id": "m1",
            "type": "merged",
            "actor": "architect",
            "repo": "ManpreetS2/fencepost",
            "pr": 5,
            "source": "ledger",
            "source_url": "build/task-ledger.md",
            "source_time": "2026-10-19T01:00:00Z",
            "attribution": {"method": "ledger_owner", "confidence": "high"},
            "raw": "Architect: merged fencepost PR #5",
        },
        {
            "id": "m2",
            "type": "merged",
            "actor": "qa-verifier",
            "repo": "ManpreetS2/agent-mindmap",
            "pr": 5,
            "source": "ledger",
            "source_url": "build/task-ledger.md",
            "source_time": "2026-10-19T01:01:00Z",
            "attribution": {"method": "ledger_owner", "confidence": "high"},
            "raw": "QA: merged agent-mindmap PR #5",
        },
    ]
    edges = derive_edges(events)
    merge_edges = [e for e in edges if e["type"] == "merge"]
    excerpt = json.dumps(merge_edges, indent=2)
    (outdir / "pr_join_repo_number.txt").write_text(excerpt, encoding="utf-8")
    pairs = {(e["source"], e["target"]) for e in merge_edges}
    expected_pairs = {("architect", "dev-1"), ("qa-verifier", "dev-2")}
    ok = pairs == expected_pairs
    assert pr_key(events[0]) == ("ManpreetS2/fencepost", 5)
    assert pr_key(events[1]) == ("ManpreetS2/agent-mindmap", 5)
    record_check("pr_join_repo_number", "PASS" if ok else "FAIL", f"pairs={pairs}", excerpt)
    if not ok:
        finding(
            id="QA-MM010-PR-JOIN",
            component="ingest/edges.py",
            expected=f"merge edges {expected_pairs}",
            actual=f"pairs={pairs}",
            repro="derive_edges with two PR #5 in different repos",
            evidence=excerpt,
            environment=env_desc,
            severity="HIGH",
            confidence="HIGH",
        )

    # Merger from ledger/signature; merged_by ignored
    gh_only = [
        {
            "id": "o",
            "type": "pr_opened",
            "actor": "dev-1",
            "repo": "ManpreetS2/fencepost",
            "pr": 99,
            "source": "github",
            "source_url": "u",
            "source_time": "2026-10-19T00:00:00Z",
            "attribution": {"method": "github_login", "confidence": "high"},
        },
        {
            "id": "m",
            "type": "merged",
            "actor": None,
            "repo": "ManpreetS2/fencepost",
            "pr": 99,
            "source": "github",
            "source_url": "u",
            "source_time": "2026-10-19T01:00:00Z",
            "attribution": {"method": "unknown", "confidence": "low"},
            "raw": "merged_by ManpreetS2",
        },
    ]
    merge_u = [e for e in derive_edges(gh_only) if e["type"] == "merge"]
    excerpt_u = json.dumps(merge_u)
    (outdir / "merged_by_ignored.txt").write_text(excerpt_u + "\n", encoding="utf-8")
    record_check("merged_by_ignored_no_edge", "PASS" if merge_u == [] else "FAIL", excerpt_u, excerpt_u)

    sig = [
        gh_only[0],
        {
            "id": "ms",
            "type": "merged",
            "actor": "architect",
            "repo": "ManpreetS2/fencepost",
            "pr": 99,
            "source": "github",
            "source_url": "u",
            "source_time": "2026-10-19T01:00:00Z",
            "attribution": {"method": "signature", "confidence": "high"},
            "raw": "merged as abcdef1\n\n~Architect",
        },
    ]
    merge_s = [e for e in derive_edges(sig) if e["type"] == "merge"]
    excerpt_s = json.dumps(merge_s)
    (outdir / "merger_from_signature.txt").write_text(excerpt_s + "\n", encoding="utf-8")
    ok_s = len(merge_s) == 1 and merge_s[0]["source"] == "architect" and merge_s[0]["target"] == "dev-1"
    record_check("merger_from_bot_signature", "PASS" if ok_s else "FAIL", excerpt_s, excerpt_s)

    gp = (ROOT / "ingest" / "github_poller.py").read_text()
    merged_by_lines = [ln for ln in gp.splitlines() if "merged_by" in ln]
    real_use = []
    for ln in merged_by_lines:
        if "ignore" in ln.lower() or "Director" in ln or "QA-MM004" in ln:
            continue
        if ".get(\"merged_by\"" in ln or "['merged_by']" in ln or '["merged_by"]' in ln:
            real_use.append(ln)
    (outdir / "merged_by_static.txt").write_text("\n".join(merged_by_lines) + "\n", encoding="utf-8")
    record_check(
        "merged_by_not_read_for_actor",
        "PASS" if not real_use else "FAIL",
        "no runtime reads of merged_by",
        "\n".join(real_use) or "none",
    )

    # gh read-only
    write_verbs = []
    for path in (ROOT / "ingest").rglob("*.py"):
        text = path.read_text()
        for i, ln in enumerate(text.splitlines(), 1):
            if re.search(
                r"gh\s+(pr\s+merge|pr\s+create|issue\s+create|api\s+.*-X\s*(POST|PUT|PATCH|DELETE))",
                ln,
                re.I,
            ):
                write_verbs.append(f"{path.relative_to(ROOT)}:{i}:{ln.strip()}")
    runner_ok = 'cmd = ["gh", "api", "--include", *args]' in (
        ROOT / "ingest" / "github_poller.py"
    ).read_text()
    (outdir / "gh_readonly_static.txt").write_text(
        f"runner_ok={runner_ok}\nwrite_verbs={write_verbs or ['NONE']}\n",
        encoding="utf-8",
    )
    record_check(
        "gh_read_only",
        "PASS" if runner_ok and not write_verbs else "FAIL",
        f"runner_ok={runner_ok}",
        f"write_verbs={write_verbs}",
    )

    # ------------------------------------------------------------------
    # SEC-MM010-1 fix verification (target 50f210c)
    # ------------------------------------------------------------------
    SECRET = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    mirror_src = (ROOT / "tools" / "ledger_mirror.py").read_text()
    calls_scanner = "_looks_like_secret" in mirror_src and "secret_line_numbers" in mirror_src

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        ledger = td_path / "ledger.md"
        state = td_path / "state.json"
        payload = td_path / "payload.md"
        clean = (
            "# L\n\n| Task ID | Project | Owner | Mode | Model | Status | Evidence |\n"
            "|---|---|---|---|---|---|---|\n| MM-010 | x | Architect | a | m | PLANNED | — |\n"
            "- 2026-10-20 Architect: assigned DEV 1 on MM-010.\n"
        )
        dirty = clean + f"- note with token {SECRET}\n"
        # 1) Dirty blocks even with --force; no payload/state; line numbers only
        ledger.write_text(dirty, encoding="utf-8")
        proc = run(
            [
                sys.executable,
                "tools/ledger_mirror.py",
                "--ledger",
                str(ledger),
                "--state",
                str(state),
                "--payload",
                str(payload),
                "--force",
                "--now",
                "4000000",
            ]
        )
        combined = proc.stdout + proc.stderr
        out = json.loads(proc.stdout) if proc.returncode == 0 else {}
        lines_expected = secret_line_numbers(dirty)
        decision = decide_flush(
            content=dirty, state=load_state(td_path / "missing.json"), now=4000000, force=True
        )
        excerpt_sec = (
            f"calls_scanner={calls_scanner}\n"
            f"cli_rc={proc.returncode}\n"
            f"cli_out={out}\n"
            f"decide={ {k: decision.get(k) for k in ('flush','reason','lines','sha256')} }\n"
            f"secret_in_stdout_stderr={SECRET in combined}\n"
            f"secret_in_json_dumps_decision={SECRET in json.dumps(decision)}\n"
            f"payload_exists={payload.exists()}\n"
            f"state_exists={state.exists()}\n"
            f"lines_expected={lines_expected}\n"
            f"_looks_like_secret(dirty)={_looks_like_secret(dirty)}\n"
        )
        (outdir / "sec_mm010_1_fix.txt").write_text(excerpt_sec, encoding="utf-8")

        ok_block = (
            calls_scanner
            and out.get("flush") is False
            and out.get("reason") == "secret_detected"
            and out.get("lines") == lines_expected
            and SECRET not in combined
            and not payload.exists()
            and not state.exists()
            and decision["flush"] is False
            and decision["reason"] == "secret_detected"
        )
        # Tool never pushes (no network); confirm no gh invocation in mirror
        no_network = "subprocess" not in mirror_src and "gh " not in mirror_src and "urllib" not in mirror_src
        record_check(
            "SEC-MM010-1_secret_blocks_force_no_write_no_leak",
            "PASS" if ok_block and no_network else "FAIL",
            excerpt_sec[:600],
            excerpt_sec,
        )
        if not (ok_block and no_network):
            finding(
                id="SEC-MM010-1",
                component="tools/ledger_mirror.py",
                expected=(
                    "secret payload → flush=false reason=secret_detected even with --force; "
                    "no payload/state write; output line numbers only; no push/network"
                ),
                actual=excerpt_sec,
                repro="ledger_mirror.py --force with ghp_… in ledger",
                evidence=excerpt_sec,
                environment=env_desc,
                severity="HIGH",
                confidence="HIGH",
            )

        # 2) Clean payload still flushes
        if payload.exists():
            payload.unlink()
        if state.exists():
            state.unlink()
        ledger.write_text(clean, encoding="utf-8")
        proc_c = run(
            [
                sys.executable,
                "tools/ledger_mirror.py",
                "--ledger",
                str(ledger),
                "--state",
                str(state),
                "--payload",
                str(payload),
                "--now",
                "5000000",
            ]
        )
        out_c = json.loads(proc_c.stdout)
        excerpt_c = (
            f"rc={proc_c.returncode}\nout={out_c}\n"
            f"payload_exists={payload.exists()}\n"
            f"payload_matches={payload.read_text()==clean if payload.exists() else False}\n"
        )
        (outdir / "sec_mm010_1_clean_flush.txt").write_text(excerpt_c, encoding="utf-8")
        ok_clean = (
            out_c.get("flush") is True
            and out_c.get("reason") == "state_change"
            and payload.exists()
            and payload.read_text() == clean
            and not state.exists()  # state only via --mark-flushed
        )
        record_check(
            "SEC-MM010-1_clean_payload_still_flushes",
            "PASS" if ok_clean else "FAIL",
            excerpt_c,
            excerpt_c,
        )
        if not ok_clean:
            finding(
                id="QA-MM010-CLEAN-FLUSH",
                component="tools/ledger_mirror.py",
                expected="clean ledger still flushes (state_change) and writes payload",
                actual=excerpt_c,
                repro="ledger_mirror.py with clean assigned line",
                evidence=excerpt_c,
                environment=env_desc,
                severity="HIGH",
                confidence="HIGH",
            )

    # Write paths + gh mocked e2e
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        sandbox = td_path / "sandbox"
        sandbox.mkdir()
        cache = sandbox / "cache"
        out_json = sandbox / "activity.json"
        text = (ROOT / "tests" / "fixtures" / "ledger-sample.md").read_text()
        encoded = base64.b64encode(text.encode()).decode()

        class CapGh:
            def __init__(self) -> None:
                self.calls: list[list[str]] = []

            def __call__(self, args: list[str], *, timeout: float = 60.0) -> GhResponse:
                self.calls.append(list(args))
                joined = " ".join(args)
                if "contents/ledger.md" in joined:
                    return GhResponse(
                        status=200,
                        headers={"etag": '"e"'},
                        body=json.dumps(
                            {
                                "name": "ledger.md",
                                "path": "ledger.md",
                                "encoding": "base64",
                                "content": encoded,
                            }
                        ),
                    )
                if "/pulls" in joined:
                    return GhResponse(status=200, headers={}, body="[]")
                return GhResponse(
                    status=200,
                    headers={},
                    body=json.dumps({"id": 1, "full_name": "ManpreetS2/agent-mindmap"}),
                )

        cap = CapGh()
        result = fetch_ledger_from_gh(cache_dir=cache / "ledger", runner=cap)
        activity = build_activity(
            ledger_text=result.text or "",
            ledger_source_url="https://github.com/ManpreetS2/agent-mindmap/blob/data/ledger/ledger.md",
            meta_ledger=result.meta_ledger,
            bots=json.loads((ROOT / "config" / "bots.json").read_text())["bots"],
            skip_github=True,
            cache_dir=cache / "gh",
            generated_at="2026-10-20T12:00:00-07:00",
        )
        write_activity(activity, out_json)
        assert_no_credentials(activity)
        written = sorted(p.relative_to(sandbox).as_posix() for p in sandbox.rglob("*") if p.is_file())
        unexpected = [
            w
            for w in written
            if not (w == "activity.json" or w.startswith("cache/"))
        ]
        mutating = [c for c in cap.calls if any(a.startswith("-X") or a == "--method" for a in c)]
        excerpt_w = f"gh_calls={cap.calls}\nfiles={written}\nunexpected={unexpected}\nmutating={mutating}\n"
        (outdir / "write_paths_and_gh_mock.txt").write_text(excerpt_w, encoding="utf-8")
        ok_w = (
            not unexpected
            and not mutating
            and any(LEDGER_API_PATH in " ".join(c) for c in cap.calls)
            and activity["meta"]["ledger"] == "ok"
        )
        record_check(
            "write_paths_constrained_gh_mocked_e2e",
            "PASS" if ok_w else "FAIL",
            excerpt_w[:500],
            excerpt_w,
        )

    # No secrets in repo (excluding intentional test token + scanner regex)
    secret_hits = run(
        [
            "rg",
            "-n",
            r"ghp_[A-Za-z0-9]{10,}|github_pat_[A-Za-z0-9_]+|GITHUB_TOKEN\s*=\s*\S+",
            "--glob",
            "!.git",
            "--glob",
            "!node_modules",
            "--glob",
            "!**/dist/**",
            "--glob",
            "!qa/**",
            str(ROOT),
        ]
    )
    (outdir / "repo_secret_scan.txt").write_text(
        secret_hits.stdout + secret_hits.stderr, encoding="utf-8"
    )
    # Allow only test fixture token and regex definitions
    allowed = True
    for ln in secret_hits.stdout.splitlines():
        if "test_ledger_mirror.py" in ln and "SECRET_TOKEN" in ln:
            continue
        if "github_poller.py" in ln and ("_looks_like_secret" in ln or "r\"(" in ln or "r'(" in ln or "ghp_" in ln):
            continue
        if "test_github_poller.py" in ln:
            continue
        if ln.strip():
            # inspect more carefully
            if re.search(r"SECRET_TOKEN\s*=\s*\"ghp_", ln):
                continue
            if "ghp_" in ln and ("r\"" in ln or "r'" in ln or "assert" in ln or "regex" in ln.lower()):
                continue
            allowed = False
            break
    record_check(
        "no_secrets_in_repo",
        "PASS" if secret_hits.returncode in (0, 1) and allowed else "FAIL",
        "only test/scanner references",
        secret_hits.stdout[:1000],
    )

    report = {
        "head": head,
        "checks": CHECKS,
        "findings": FINDINGS,
        "environment": env_desc,
    }
    (outdir / "qa_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "head": head,
                "checks": [(c["name"], c["result"]) for c in CHECKS],
                "findings": [f["id"] for f in FINDINGS],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
