#!/usr/bin/env python3
"""
Independent behavioral tests for MM-020c (PR #18) @ 9cb0c58.

Also covers Security additions:
  - false-positive sk- substrings must NOT refuse flush
  - stronger secret patterns scope: mirror vs shared scanner vs ledger vs PR17 emitter
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import traceback
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path("/tmp/qa-mm020c/checkout")
PR17 = Path("/tmp/qa-mm020c/pr17")
sys.path.insert(0, str(ROOT))

from ingest.events_fetch import (  # noqa: E402
    EVENTS_API_PATH,
    EventsFetcher,
    fetch_events_from_gh,
)
from ingest.github_poller import GhResponse, _looks_like_secret  # noqa: E402
from tools.events_mirror import (  # noqa: E402
    RETENTION_DAYS,
    decide_flush,
    looks_like_mirror_secret,
    mark_flushed,
    prepare_events_payload,
    save_state,
    secret_line_numbers,
    sha256_text,
)
from tools import ledger_mirror as ledger_mirror  # noqa: E402

EVIDENCE = Path("/tmp/qa-mm020c/evidence")
EVIDENCE.mkdir(parents=True, exist_ok=True)

BENIGN_SK_FALSE_POSITIVES = [
    "task-runner",
    "risk-based",
    "ask-me",
    "desk-top",
    "Mask-RCNN",
]


def _evt(
    eid: str,
    *,
    ts: str,
    summary: str = "ok",
    sender: str = "dev-1",
    group: str = "build",
    provenance: str = "agent-reported",
    **extra: Any,
) -> dict[str, Any]:
    ev: dict[str, Any] = {
        "id": eid,
        "ts": ts,
        "sender": sender,
        "group": group,
        "type": "message",
        "summary": summary,
        "provenance": provenance,
    }
    ev.update(extra)
    return ev


def _line(ev: dict[str, Any]) -> str:
    return json.dumps(ev, sort_keys=True, separators=(",", ":"))


class TestRetention7Day(unittest.TestCase):
    def test_exact_boundary_and_timezone(self) -> None:
        now = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)
        cutoff = now - timedelta(days=RETENTION_DAYS)
        # Exactly at cutoff → retained (>= cutoff uses ts < cutoff to drop)
        at_boundary = cutoff.isoformat()
        just_inside = (cutoff + timedelta(seconds=1)).isoformat()
        just_outside = (cutoff - timedelta(seconds=1)).isoformat()
        # Zulu / offset variants of just_inside
        zulu = (cutoff + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        plus_offset = (cutoff + timedelta(hours=2)).isoformat().replace("+00:00", "+00:00")
        # Negative offset that is still within 7d in absolute UTC
        eastern = (cutoff + timedelta(hours=3)).astimezone(
            timezone(timedelta(hours=-4))
        ).isoformat()
        # Old event with +05:30 that falls outside when converted
        old_ist = (cutoff - timedelta(days=1)).astimezone(
            timezone(timedelta(hours=5, minutes=30))
        ).isoformat()

        raw = "\n".join(
            [
                _line(_evt("boundary", ts=at_boundary, summary="at boundary")),
                _line(_evt("inside", ts=just_inside, summary="inside")),
                _line(_evt("outside", ts=just_outside, summary="outside")),
                _line(_evt("zulu", ts=zulu, summary="zulu")),
                _line(_evt("offset", ts=plus_offset, summary="offset")),
                _line(_evt("eastern", ts=eastern, summary="eastern")),
                _line(_evt("old_ist", ts=old_ist, summary="old ist")),
            ]
        )
        text, events, _, secrets = prepare_events_payload(raw, now=now, warn=False)
        ids = {e["id"] for e in events}
        self.assertFalse(secrets)
        self.assertIn("boundary", ids, "exact 7-day boundary should be retained")
        self.assertIn("inside", ids)
        self.assertNotIn("outside", ids)
        self.assertIn("zulu", ids)
        self.assertIn("offset", ids)
        self.assertIn("eastern", ids)
        self.assertNotIn("old_ist", ids)
        # Overwrite payload contains only retained lines
        out_ids = [json.loads(ln)["id"] for ln in text.splitlines() if ln.strip()]
        self.assertEqual(set(out_ids), ids)
        self.assertEqual(len(out_ids), len(ids), "no duplicate lines in overwrite")


class TestFlushIdempotentAtomic(unittest.TestCase):
    def test_repeated_flush_no_duplicates(self) -> None:
        now = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)
        raw = _line(_evt("a1", ts=now.isoformat(), summary="hello")) + "\n"
        text1, ev1, _, _ = prepare_events_payload(raw, now=now, warn=False)
        text2, ev2, _, _ = prepare_events_payload(raw + raw, now=now, warn=False)
        self.assertEqual(text1, text2)
        self.assertEqual(len(ev2), 1)
        digest = sha256_text(text1)
        state: dict[str, Any] = {
            "last_flushed_sha256": None,
            "last_flushed_at": None,
            "state_change_fingerprints": [],
        }
        d1 = decide_flush(content=text1, events=ev1, state=state, now=1_000_000.0)
        self.assertTrue(d1["flush"])
        state = mark_flushed(
            state_path=Path(tempfile.mkdtemp()) / "state.json",
            sha256=d1["sha256"],
            events=ev1,
            now=1_000_000.0,
        )
        d2 = decide_flush(
            content=text1, events=ev1, state=state, now=1_000_000.0 + 10_000
        )
        self.assertFalse(d2["flush"])
        self.assertEqual(d2["reason"], "unchanged")
        # force cannot re-flush identical sha
        d3 = decide_flush(
            content=text1, events=ev1, state=state, now=1_000_000.0 + 10_000, force=True
        )
        self.assertFalse(d3["flush"])
        self.assertEqual(d3["reason"], "unchanged")
        self.assertEqual(d1["sha256"], digest)

    def test_state_write_atomic_replace(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "state.json"
            save_state(
                path,
                {
                    "last_flushed_sha256": "abc",
                    "last_flushed_at": 1.0,
                    "state_change_fingerprints": ["x"],
                },
            )
            self.assertTrue(path.is_file())
            self.assertFalse(path.with_suffix(".json.tmp").exists())
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["last_flushed_sha256"], "abc")

    def test_crash_midway_partial_payload_behavior(self) -> None:
        """Simulate partial write of payload file; re-prepare must not duplicate ids."""
        now = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)
        lines = [
            _line(_evt(f"id-{i}", ts=(now - timedelta(minutes=i)).isoformat(), summary=f"s{i}"))
            for i in range(5)
        ]
        full = "\n".join(lines) + "\n"
        # Partial: truncated mid-line
        partial = full[: len(full) // 2]
        text, events, warnings, secrets = prepare_events_payload(
            partial, now=now, warn=False
        )
        ids = [e["id"] for e in events]
        self.assertEqual(len(ids), len(set(ids)), "no duplicate ids after partial input")
        # Re-run on full content after "recovery"
        text2, events2, _, _ = prepare_events_payload(full, now=now, warn=False)
        ids2 = [e["id"] for e in events2]
        self.assertEqual(len(ids2), len(set(ids2)))
        self.assertEqual(len(ids2), 5)

    def test_cli_payload_write_and_repeat_idempotent(self) -> None:
        """CLI force flush writes payload; repeat is unchanged (no dup content)."""
        from tools import events_mirror as em

        now = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            events = td_path / "events.jsonl"
            state = td_path / "state.json"
            payload = td_path / "out" / "events.jsonl"
            events.write_text(
                _line(_evt("cli1", ts=now.isoformat(), summary="cli")) + "\n",
                encoding="utf-8",
            )
            rc = em.main(
                [
                    "--events",
                    str(events),
                    "--state",
                    str(state),
                    "--payload",
                    str(payload),
                    "--force",
                ]
            )
            self.assertEqual(rc, 0)
            self.assertTrue(payload.is_file())
            body = payload.read_text(encoding="utf-8")
            self.assertEqual(len([ln for ln in body.splitlines() if ln.strip()]), 1)
            digest = sha256_text(
                prepare_events_payload(
                    events.read_text(encoding="utf-8"), now=now, warn=False
                )[0]
            )
            rc_mark = em.main(
                [
                    "--events",
                    str(events),
                    "--state",
                    str(state),
                    "--mark-flushed",
                    digest,
                ]
            )
            self.assertEqual(rc_mark, 0)
            import io
            from contextlib import redirect_stdout

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc2 = em.main(
                    [
                        "--events",
                        str(events),
                        "--state",
                        str(state),
                        "--payload",
                        str(td_path / "out2" / "events.jsonl"),
                        "--force",
                    ]
                )
            self.assertEqual(rc2, 0)
            decision = json.loads(buf.getvalue().strip().splitlines()[-1])
            self.assertFalse(decision.get("flush"))
            self.assertEqual(decision.get("reason"), "unchanged")


class TestSecretRefusalAndFalsePositives(unittest.TestCase):
    def test_qa_mm020b2_secrets_refuse_flush(self) -> None:
        now = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)
        probes = {
            "ghp_": "token ghp_abcdefghijklmnopqrstuvwxyz1234567890AB",
            "github_pat_": "github_pat_11AAAAAAA0123456789_abcdefghijklmnopqrstuvwx",
            "sk-": "sk-proj-abcdefghijklmnopqrstuvwxyz1234567890ABCDEF",
            "AKIA": "AKIAIOSFODNN7EXAMPLE",
            "Bearer": "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc.def",
            "JWT": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0In0.signature",
            "private_key": "-----BEGIN PRIVATE KEY----- MIIEvQIBADANBg -----END PRIVATE KEY-----",
            "email": "contact alice@example.com please",
        }
        results = {}
        for name, summary in probes.items():
            raw = _line(_evt(f"sec-{name}", ts=now.isoformat(), summary=summary)) + "\n"
            text, events, warnings, secrets_seen = prepare_events_payload(
                raw, now=now, warn=False
            )
            # Also put secret in sender field
            raw_sender = (
                _line(
                    _evt(
                        f"sec-sender-{name}",
                        ts=now.isoformat(),
                        summary="benign summary text here",
                        sender=summary[:40] if len(summary) > 5 else summary,
                    )
                )
                + "\n"
            )
            # sender may fail validation (pattern) — also test related_id / group
            raw_group = (
                _line(
                    _evt(
                        f"sec-group-{name}",
                        ts=now.isoformat(),
                        summary="benign summary text here",
                        group=summary if len(summary) < 80 else summary[:80],
                    )
                )
                + "\n"
            )
            t2, e2, w2, s2 = prepare_events_payload(raw_group, now=now, warn=False)
            decision = decide_flush(
                content=raw,  # unprepared content with secret
                events=[],
                state={
                    "last_flushed_sha256": None,
                    "last_flushed_at": None,
                    "state_change_fingerprints": [],
                },
                now=1_000_000.0,
                force=True,
            )
            results[name] = {
                "prepare_secrets_seen": secrets_seen,
                "prepare_event_count": len(events),
                "prepare_text_empty_or_no_secret": summary[:10] not in text,
                "group_field_secrets_seen": s2,
                "group_events": len(e2),
                "decide_on_raw": decision.get("reason"),
                "warning_has_secret_word_material": any(
                    "ghp_" in w or "AKIA" in w or "sk-proj" in w for w in warnings
                ),
            }
            self.assertTrue(
                secrets_seen or decision.get("reason") == "secret_detected",
                f"{name} should be refused/dropped",
            )
            self.assertFalse(
                results[name]["warning_has_secret_word_material"],
                f"{name} warning leaked secret material",
            )

        EVIDENCE.joinpath("secret_refusal_results.json").write_text(
            json.dumps(results, indent=2), encoding="utf-8"
        )
        # All listed probes should set secrets_seen on prepare
        for name, row in results.items():
            self.assertTrue(
                row["prepare_secrets_seen"],
                f"{name}: expected secrets_seen on prepare; got {row}",
            )
            self.assertEqual(row["prepare_event_count"], 0)

    def test_false_positive_benign_words_must_not_refuse(self) -> None:
        now = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)
        report = []
        for word in BENIGN_SK_FALSE_POSITIVES:
            mirror_hit = looks_like_mirror_secret(word)
            shared_hit = _looks_like_secret(word)
            # What does the sk- regex match? (behavioral via mirror helper)
            raw = (
                _line(
                    _evt(
                        f"benign-{word}",
                        ts=now.isoformat(),
                        summary=f"Completed {word} work item",
                    )
                )
                + "\n"
            )
            text, events, warnings, secrets_seen = prepare_events_payload(
                raw, now=now, warn=False
            )
            decision = decide_flush(
                content=text,
                events=events,
                state={
                    "last_flushed_sha256": None,
                    "last_flushed_at": None,
                    "state_change_fingerprints": [],
                },
                now=1_000_000.0,
                force=True,
            )
            row = {
                "word": word,
                "looks_like_mirror_secret": mirror_hit,
                "shared_looks_like_secret": shared_hit,
                "prepare_secrets_seen": secrets_seen,
                "retained": len(events),
                "flush": decision.get("flush"),
                "reason": decision.get("reason"),
            }
            report.append(row)
        EVIDENCE.joinpath("false_positive_sk_results.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        # Security requirement: must NOT refuse
        failures = [r for r in report if r["prepare_secrets_seen"] or not r["flush"]]
        self.assertEqual(
            failures,
            [],
            f"benign words incorrectly refused: {json.dumps(failures, indent=2)}",
        )


class TestScannerScope(unittest.TestCase):
    """Stronger patterns: mirror-only vs shared vs ledger vs PR17 emitter."""

    PROBES = {
        "sk-": "sk-proj-abcdefghijklmnopqrstuvwxyz1234567890ABCDEF",
        "AKIA": "AKIAIOSFODNN7EXAMPLE",
        "JWT": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0In0.signature",
        "private_key": "-----BEGIN PRIVATE KEY----- MIIE -----END PRIVATE KEY-----",
        "email": "alice@example.com",
        "ghp_": "ghp_abcdefghijklmnopqrstuvwxyz1234567890AB",
        "task-runner": "task-runner",
    }

    def test_shared_scanner_lacks_stronger_patterns(self) -> None:
        scope = {}
        for name, text in self.PROBES.items():
            scope[name] = {
                "shared__looks_like_secret": _looks_like_secret(text),
                "mirror_looks_like_mirror_secret": looks_like_mirror_secret(text),
                "ledger_secret_line_numbers": ledger_mirror.secret_line_numbers(
                    text + "\n"
                ),
            }
        EVIDENCE.joinpath("scanner_scope_shared_ledger_mirror.json").write_text(
            json.dumps(scope, indent=2), encoding="utf-8"
        )
        self.assertFalse(scope["sk-"]["shared__looks_like_secret"])
        self.assertTrue(scope["sk-"]["mirror_looks_like_mirror_secret"])
        self.assertEqual(scope["sk-"]["ledger_secret_line_numbers"], [])
        self.assertFalse(scope["AKIA"]["shared__looks_like_secret"])
        self.assertTrue(scope["AKIA"]["mirror_looks_like_mirror_secret"])
        self.assertEqual(scope["AKIA"]["ledger_secret_line_numbers"], [])
        self.assertTrue(scope["ghp_"]["shared__looks_like_secret"])
        self.assertTrue(scope["ghp_"]["mirror_looks_like_mirror_secret"])
        self.assertEqual(scope["ghp_"]["ledger_secret_line_numbers"], [1])

    def test_pr17_emitter_has_local_stronger_not_via_shared(self) -> None:
        if not (PR17 / "tools" / "event_emit.py").is_file():
            self.skipTest("PR17 checkout missing")
        probe_script = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
from tools.event_emit import sanitize_summary, SecretRefusedError
from ingest.github_poller import _looks_like_secret
probes = json.loads(sys.argv[2])
rows = {}
for name, text in probes.items():
    refused = False
    err = None
    try:
        sanitize_summary(text)
    except SecretRefusedError as exc:
        refused = True
        err = type(exc).__name__
    except Exception as exc:
        refused = True
        err = type(exc).__name__
    rows[name] = {
        "emitter_refused": refused,
        "shared_pr17": _looks_like_secret(text),
        "err_type": err,
    }
print(json.dumps(rows))
"""
        r = subprocess.run(
            [
                sys.executable,
                "-c",
                probe_script,
                str(PR17),
                json.dumps(self.PROBES),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = json.loads(r.stdout)
        head = subprocess.check_output(
            ["git", "-C", str(PR17), "rev-parse", "HEAD"], text=True
        ).strip()
        payload = {"pr17_head": head, "rows": rows}
        EVIDENCE.joinpath("scanner_scope_pr17_emitter.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
        self.assertTrue(rows["sk-"]["emitter_refused"])
        self.assertFalse(rows["sk-"]["shared_pr17"])
        self.assertTrue(rows["AKIA"]["emitter_refused"])
        self.assertFalse(rows["AKIA"]["shared_pr17"])
        self.assertTrue(
            rows["task-runner"]["emitter_refused"],
            "document: PR17 tip also false-positive refuses task-runner",
        )


class TestGhReadOnlyAndNoToken(unittest.TestCase):
    def test_gh_argv_read_only_no_write_verbs(self) -> None:
        calls: list[list[str]] = []

        def runner(args: list[str]) -> GhResponse:
            calls.append(list(args))
            # Minimal 404 missing
            return GhResponse(status=404, headers={}, body="")

        # Also wrap default path via EventsFetcher
        with tempfile.TemporaryDirectory() as td:
            fetcher = EventsFetcher(
                cache_dir=Path(td), runner=runner  # type: ignore[arg-type]
            )
            result = fetcher.fetch()
            self.assertEqual(result.meta_events, "missing")
        self.assertTrue(calls)
        joined = " ".join(" ".join(c) for c in calls).lower()
        for bad in (
            "post",
            "patch",
            "delete",
            "--method",
            " -x ",
            "merge",
            "comment",
            "edit",
            "put ",
        ):
            self.assertNotIn(bad.strip(), joined)
        # Should be contents GET path only
        self.assertTrue(any(EVENTS_API_PATH in " ".join(c) for c in calls))

        # Audit a broader mock that tries to sneak write — fetcher must not emit it
        write_attempts: list[str] = []

        def evil_runner(args: list[str]) -> GhResponse:
            write_attempts.append(" ".join(args))
            # If code asked for write, record it
            return GhResponse(status=200, headers={}, body="{}")

        with tempfile.TemporaryDirectory() as td:
            fetch_events_from_gh(runner=evil_runner, cache_dir=Path(td))  # type: ignore[arg-type]
        for attempt in write_attempts:
            low = attempt.lower()
            self.assertFalse(any(v in low for v in (" -x post", "-x patch", "-x delete")))
            self.assertIn("contents/events.jsonl", attempt)

        EVIDENCE.joinpath("gh_argv_calls.json").write_text(
            json.dumps({"calls": calls, "write_attempts": write_attempts}, indent=2),
            encoding="utf-8",
        )

    def test_no_token_in_logs_env_argv_mirror(self) -> None:
        fake_token = "ghp_TESTTOKENVALUE000000000000000000001"
        now = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)
        env = os.environ.copy()
        env["GH_TOKEN"] = fake_token
        env["GITHUB_TOKEN"] = fake_token
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            events = td_path / "events.jsonl"
            state = td_path / "state.json"
            payload = td_path / "payload.jsonl"
            # benign content
            events.write_text(
                _line(_evt("tok1", ts=now.isoformat(), summary="no secrets here"))
                + "\n",
                encoding="utf-8",
            )
            r = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "tools.events_mirror",
                    "--events",
                    str(events),
                    "--state",
                    str(state),
                    "--payload-out",
                    str(payload),
                    "--force",
                ],
                cwd=str(ROOT),
                env=env,
                capture_output=True,
                text=True,
            )
            blob = (r.stdout or "") + (r.stderr or "")
            self.assertNotIn(fake_token, blob)
            if payload.exists():
                self.assertNotIn(fake_token, payload.read_text(encoding="utf-8"))
            # Child env: use a helper that prints whether token env leaked into
            # a mocked gh child — events_mirror itself should not spawn gh.
            self.assertNotIn("gh ", blob.lower().replace("events_mirror", ""))

        # Fetch path: runner must not receive token in argv; simulate child env audit
        seen_env: dict[str, str] = {}
        seen_argv: list[str] = []

        def runner(args: list[str]) -> GhResponse:
            seen_argv.extend(args)
            # default_gh_runner uses subprocess — our mock does not; ensure args clean
            body = {
                "name": "events.jsonl",
                "path": "events.jsonl",
                "content": base64.b64encode(b"").decode(),
                "encoding": "base64",
                "size": 0,
                "sha": "0" * 40,
            }
            return GhResponse(
                status=200,
                headers={"etag": '"e1"'},
                body=json.dumps(body),
            )

        with tempfile.TemporaryDirectory() as td:
            # Put token in env around fetch
            with mock.patch.dict(os.environ, {"GH_TOKEN": fake_token}):
                fetch_events_from_gh(runner=runner, cache_dir=Path(td))  # type: ignore[arg-type]
                seen_env["GH_TOKEN_PRESENT_IN_PARENT"] = "GH_TOKEN" in os.environ
        self.assertTrue(all(fake_token not in a for a in seen_argv))
        EVIDENCE.joinpath("token_exposure.json").write_text(
            json.dumps(
                {
                    "mirror_rc": r.returncode,
                    "token_in_mirror_output": fake_token in blob,
                    "argv": seen_argv,
                    "parent_env_had_token": seen_env.get("GH_TOKEN_PRESENT_IN_PARENT"),
                },
                indent=2,
            ),
            encoding="utf-8",
        )


class TestNoRegressions020a(unittest.TestCase):
    def test_mm020a_suite_subset(self) -> None:
        r = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "--tb=no",
                "tests/test_mm020a_membership.py",
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        EVIDENCE.joinpath("pytest_mm020a.txt").write_text(
            r.stdout + r.stderr, encoding="utf-8"
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_mm020b_emitter_absent_on_branch(self) -> None:
        # Document: 020b not merged into this PR branch
        self.assertFalse((ROOT / "tools" / "event_emit.py").exists())


def main() -> int:
    loader = unittest.defaultTestLoader
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    stream_path = EVIDENCE / "behavioral_run.txt"
    with stream_path.open("w", encoding="utf-8") as fh:
        runner = unittest.TextTestRunner(verbosity=2, stream=fh)
        result = runner.run(suite)
    # also print
    print(stream_path.read_text(encoding="utf-8"))
    summary = {
        "testsRun": result.testsRun,
        "failures": [(str(t), e) for t, e in result.failures],
        "errors": [(str(t), e) for t, e in result.errors],
        "skipped": [(str(t), r) for t, r in result.skipped],
        "wasSuccessful": result.wasSuccessful(),
    }
    EVIDENCE.joinpath("behavioral_results.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        raise
