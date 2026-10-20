#!/usr/bin/env python3
"""
Delta behavioral re-verify for MM-020c PR #18 @ 4cab4d9
(vs earlier FAIL @ 9cb0c58).
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
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path("/tmp/qa-mm020c-d2/checkout")
sys.path.insert(0, str(ROOT))

from ingest.github_poller import _looks_like_secret  # noqa: E402
from tools.atomic_write import atomic_write_bytes, atomic_write_text  # noqa: E402
from tools.events_mirror import decide_flush, prepare_events_payload  # noqa: E402
from tools import events_mirror as em  # noqa: E402
from tools import ledger_mirror as lm  # noqa: E402
from tools.secret_scan import find_secrets, looks_like_secret, secret_kinds  # noqa: E402

EVIDENCE = Path("/tmp/qa-mm020c-d2/evidence")
EVIDENCE.mkdir(parents=True, exist_ok=True)

BENIGN = [
    "task-runner",
    "risk-based",
    "ask-me",
    "desk-top",
    "Mask-RCNN",
    "Tasks",
    "sketch-pad",
    "SK-PROJ-SHOULD-NOT-MATCH-CASE",  # case-sensitive sk-
]


def _evt(eid: str, *, ts: str, summary: str = "ok", **extra: Any) -> dict[str, Any]:
    ev = {
        "id": eid,
        "ts": ts,
        "sender": "dev-1",
        "group": "build",
        "type": "message",
        "summary": summary,
        "provenance": "agent-reported",
    }
    ev.update(extra)
    return ev


def _line(ev: dict[str, Any]) -> str:
    return json.dumps(ev, sort_keys=True, separators=(",", ":"))


class TestNoSkFalsePositives(unittest.TestCase):
    def test_benign_words_pass_all_surfaces(self) -> None:
        now = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)
        rows = []
        for word in BENIGN:
            shared = looks_like_secret(word)
            wrapper = _looks_like_secret(word)
            ledger_hits = lm.secret_line_numbers(f"{word}\n")
            raw = _line(_evt(f"b-{word}", ts=now.isoformat(), summary=f"Completed {word}")) + "\n"
            text, events, _, secrets_seen = prepare_events_payload(raw, now=now, warn=False)
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
                "looks_like_secret": shared,
                "_looks_like_secret_wrapper": wrapper,
                "ledger_secret_lines": ledger_hits,
                "prepare_secrets_seen": secrets_seen,
                "retained": len(events),
                "flush": decision.get("flush"),
                "reason": decision.get("reason"),
            }
            rows.append(row)
            self.assertFalse(shared, word)
            self.assertFalse(wrapper, word)
            self.assertEqual(ledger_hits, [], word)
            self.assertFalse(secrets_seen, word)
            self.assertEqual(len(events), 1, word)
            self.assertTrue(decision.get("flush"), word)

        # CLI path with all benign words
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            events_path = td_path / "events.jsonl"
            payload = td_path / "payload.jsonl"
            lines = [
                _line(
                    _evt(
                        f"cli-{i}",
                        ts=now.isoformat(),
                        summary=f"Completed {w} work",
                    )
                )
                for i, w in enumerate(BENIGN)
            ]
            events_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            import io
            from contextlib import redirect_stdout, redirect_stderr

            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = em.main(
                    [
                        "--events",
                        str(events_path),
                        "--state",
                        str(td_path / "state.json"),
                        "--payload",
                        str(payload),
                        "--force",
                    ]
                )
            decision = json.loads(out.getvalue().strip().splitlines()[-1])
            rows.append(
                {
                    "cli_rc": rc,
                    "cli_decision": decision,
                    "cli_stderr": err.getvalue(),
                    "payload_exists": payload.exists(),
                }
            )
            self.assertEqual(rc, 0)
            self.assertTrue(decision.get("flush"), decision)
            self.assertNotEqual(decision.get("reason"), "secret_detected")
            self.assertTrue(payload.exists())

        EVIDENCE.joinpath("delta_sk_false_positives.json").write_text(
            json.dumps(rows, indent=2), encoding="utf-8"
        )

    def test_real_sk_keys_refused_including_near_min_length(self) -> None:
        # Pattern: sk- + ≥20 of [A-Za-z0-9_-]
        sk_19 = "sk-" + ("a" * 19)  # below minimum → must NOT match
        sk_20 = "sk-" + ("b" * 20)  # exact minimum → refuse
        sk_21 = "sk-" + ("c" * 21)
        sk_proj = "sk-proj-abcdefghijklmnopqrstuvwxyz1234"  # well over 20
        sk_ant = "sk-ant-abcdefghijklmnopqrstuvwxyz1234"
        cases = {
            "sk_19_below_min": (sk_19, False),
            "sk_20_min": (sk_20, True),
            "sk_21": (sk_21, True),
            "sk_proj": (sk_proj, True),
            "sk_ant": (sk_ant, True),
        }
        report = {}
        now = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)
        for name, (token, expect_refuse) in cases.items():
            hit = looks_like_secret(token)
            kinds = find_secrets(token)
            raw = _line(_evt(name, ts=now.isoformat(), summary=f"token {token}")) + "\n"
            _, events, _, secrets_seen = prepare_events_payload(raw, now=now, warn=False)
            ledger = lm.secret_line_numbers(f"{token}\n")
            report[name] = {
                "token_len_after_sk": len(token) - 3,
                "looks_like_secret": hit,
                "kinds": kinds,
                "prepare_secrets_seen": secrets_seen,
                "retained": len(events),
                "ledger_lines": ledger,
                "expect_refuse": expect_refuse,
            }
            self.assertEqual(hit, expect_refuse, name)
            self.assertEqual(secrets_seen, expect_refuse, name)
            self.assertEqual(bool(ledger), expect_refuse, name)
            if expect_refuse:
                self.assertIn("sk", kinds)
                self.assertEqual(len(events), 0)
            else:
                self.assertEqual(len(events), 1)
        EVIDENCE.joinpath("delta_sk_real_keys.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )


class TestSingleSourceSecretScan(unittest.TestCase):
    def test_all_surfaces_same_function(self) -> None:
        probes = [
            "ghp_abcdefghijklmnopqrstuvwxyz1234567890AB",
            "sk-" + ("x" * 20),
            "AKIAIOSFODNN7EXAMPLE",
            "task-runner",
            "alice@example.com",
        ]
        rows = []
        for p in probes:
            rows.append(
                {
                    "probe": p[:40],
                    "secret_scan": looks_like_secret(p),
                    "github_poller_wrapper": _looks_like_secret(p),
                    "ledger": bool(lm.secret_line_numbers(p + "\n")),
                    "events_mirror_prepare_secret": prepare_events_payload(
                        _line(
                            _evt(
                                "x",
                                ts="2026-10-20T12:00:00+00:00",
                                summary=p if len(p) < 200 else p[:200],
                            )
                        )
                        + "\n",
                        now=datetime(2026, 10, 20, 12, tzinfo=timezone.utc),
                        warn=False,
                    )[3],
                }
            )
            self.assertEqual(
                looks_like_secret(p),
                _looks_like_secret(p),
                p,
            )
        EVIDENCE.joinpath("delta_single_source_surfaces.json").write_text(
            json.dumps({"kinds": list(secret_kinds()), "rows": rows}, indent=2),
            encoding="utf-8",
        )

    def test_no_leftover_local_denylist_copies(self) -> None:
        """Behavioral: ripgrep for old local regex owners outside secret_scan.py."""
        r = subprocess.run(
            [
                "rg",
                "-n",
                r"sk-\[A-Za-z0-9|_MIRROR_SECRET_EXTRA|_FREE_TEXT_SCANNERS|AKIA\[0-9A-Z\]\{16\}",
                str(ROOT / "tools"),
                str(ROOT / "ingest"),
                "--glob",
                "!secret_scan.py",
            ],
            capture_output=True,
            text=True,
        )
        # Also ensure events_mirror / ledger import shared module
        em_src = (ROOT / "tools" / "events_mirror.py").read_text(encoding="utf-8")
        lm_src = (ROOT / "tools" / "ledger_mirror.py").read_text(encoding="utf-8")
        gp_src = (ROOT / "ingest" / "github_poller.py").read_text(encoding="utf-8")
        # Prefer import-presence checks over reading patterns from secret_scan
        self.assertIn("from tools.secret_scan import looks_like_secret", em_src)
        self.assertIn("from tools.secret_scan import looks_like_secret", lm_src)
        self.assertIn("from tools.secret_scan import looks_like_secret", gp_src)
        self.assertNotIn("_MIRROR_SECRET_EXTRA", em_src)
        leftover = r.stdout.strip()
        EVIDENCE.joinpath("delta_no_leftover_local_patterns.txt").write_text(
            leftover or "(none)", encoding="utf-8"
        )
        self.assertEqual(leftover, "", f"leftover local patterns:\n{leftover}")


class TestFullPatternSetAndNewFalsePositives(unittest.TestCase):
    def test_full_set_refused_on_every_surface(self) -> None:
        probes = {
            "AKIA": "AKIAIOSFODNN7EXAMPLE",
            "JWT": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0In0.signature",
            "PEM": "-----BEGIN PRIVATE KEY----- MIIEvQIBADANBgkqhkiG9w0BAQEFAASC -----END PRIVATE KEY-----",
            "email": "alice@example.com",
            "ghp_": "ghp_abcdefghijklmnopqrstuvwxyz1234567890AB",
            "Bearer": "Authorization: Bearer abcdefghijklmnop",
        }
        report = {}
        now = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
        for name, text in probes.items():
            report[name] = {
                "secret_scan": looks_like_secret(text),
                "kinds": find_secrets(text),
                "wrapper": _looks_like_secret(text),
                "ledger_lines": lm.secret_line_numbers(text + "\n"),
                "mirror_secrets_seen": prepare_events_payload(
                    _line(_evt(name, ts=now.isoformat(), summary=f"x {text} y"))
                    + "\n",
                    now=now,
                    warn=False,
                )[3],
            }
            self.assertTrue(report[name]["secret_scan"], name)
            self.assertTrue(report[name]["wrapper"], name)
            self.assertTrue(report[name]["ledger_lines"], name)
            self.assertTrue(report[name]["mirror_secrets_seen"], name)
        EVIDENCE.joinpath("delta_full_pattern_surfaces.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )

    def test_new_false_positives_email_and_base64(self) -> None:
        """Document whether ordinary emails / base64 trip the scanner."""
        cases = {
            "docs_email": "See docs at support@example.com for help",
            "short_email": "a@b.co",
            "base64_lorem": base64.b64encode(
                b"The quick brown fox jumps over the lazy dog " * 5
            ).decode(),
            "base64_jsonish": base64.b64encode(
                json.dumps({"hello": "world", "n": 1}).encode()
            ).decode(),
            # JWT-like prefix risk: eyJ is base64 for '{"'
            "base64_starts_eyJ_three_segments": ".".join(
                [
                    base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip("="),
                    base64.urlsafe_b64encode(b'{"sub":"1"}').decode().rstrip("="),
                    base64.urlsafe_b64encode(b"sig").decode().rstrip("="),
                ]
            ),
            "plain_sentence": "No secrets in this ordinary operational summary.",
        }
        report = {}
        for name, text in cases.items():
            report[name] = {
                "looks_like_secret": looks_like_secret(text),
                "kinds": find_secrets(text),
                "len": len(text),
            }
        EVIDENCE.joinpath("delta_new_false_positives.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        # Hard expects: plain sentence must pass
        self.assertFalse(report["plain_sentence"]["looks_like_secret"])
        # Emails are currently in denylist — flag as finding if true (expected by current design)
        # Base64 lorem should ideally pass; JWT-shaped three-segment eyJ will match jwt kind
        # Assert only that we recorded results; specific FAIL findings derived in report.
        self.assertIsInstance(report["docs_email"]["looks_like_secret"], bool)


class TestAtomicPayloadWrite(unittest.TestCase):
    def test_atomic_write_replace_no_partial_dest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "events.jsonl"
            dest.write_text("OLD\n", encoding="utf-8")
            # Simulate crash mid-write: write temp then kill before replace
            tmp = dest.with_name(dest.name + ".tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
            try:
                os.write(fd, b"PARTIAL")
                # no fsync/replace — crash
            finally:
                os.close(fd)
            self.assertEqual(dest.read_text(encoding="utf-8"), "OLD\n")
            self.assertTrue(tmp.exists())
            # Recovery: atomic_write completes
            atomic_write_text(dest, "NEW\n")
            self.assertEqual(dest.read_text(encoding="utf-8"), "NEW\n")
            self.assertFalse(tmp.exists(), "tmp should be replaced away")

    def test_cli_payload_uses_atomic_helper(self) -> None:
        now = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            events = td_path / "events.jsonl"
            payload = td_path / "out" / "events.jsonl"
            events.write_text(
                _line(_evt("a1", ts=now.isoformat(), summary="atomic cli")) + "\n",
                encoding="utf-8",
            )
            # Patch os.replace to observe call
            replaces: list[tuple[str, str]] = []
            real_replace = os.replace

            def spy_replace(src, dst):  # noqa: ANN001
                replaces.append((str(src), str(dst)))
                return real_replace(src, dst)

            with mock.patch("tools.atomic_write.os.replace", side_effect=spy_replace):
                rc = em.main(
                    [
                        "--events",
                        str(events),
                        "--state",
                        str(td_path / "state.json"),
                        "--payload",
                        str(payload),
                        "--force",
                    ]
                )
            self.assertEqual(rc, 0)
            self.assertTrue(payload.exists())
            self.assertTrue(
                any(str(payload) == dst for _, dst in replaces),
                f"expected os.replace into payload; got {replaces}",
            )
            self.assertFalse(payload.with_name(payload.name + ".tmp").exists())
            EVIDENCE.joinpath("delta_atomic_payload.json").write_text(
                json.dumps({"rc": rc, "replaces": replaces}, indent=2),
                encoding="utf-8",
            )


class TestRegressionsPriorChecks(unittest.TestCase):
    def test_retention_boundary_still_ok(self) -> None:
        now = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)
        cutoff = now - timedelta(days=7)
        raw = "\n".join(
            [
                _line(_evt("at", ts=cutoff.isoformat())),
                _line(_evt("out", ts=(cutoff - timedelta(seconds=1)).isoformat())),
                _line(
                    _evt(
                        "z",
                        ts=(cutoff + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    )
                ),
            ]
        )
        _, events, _, _ = prepare_events_payload(raw, now=now, warn=False)
        ids = {e["id"] for e in events}
        self.assertIn("at", ids)
        self.assertNotIn("out", ids)
        self.assertIn("z", ids)

    def test_idempotent_flush(self) -> None:
        now = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
        text, events, _, _ = prepare_events_payload(
            _line(_evt("i1", ts=now.isoformat(), summary="hello")) + "\n",
            now=now,
            warn=False,
        )
        state = {
            "last_flushed_sha256": None,
            "last_flushed_at": None,
            "state_change_fingerprints": [],
        }
        d1 = decide_flush(content=text, events=events, state=state, now=1e6, force=True)
        self.assertTrue(d1["flush"])
        state["last_flushed_sha256"] = d1["sha256"]
        state["last_flushed_at"] = 1e6
        state["state_change_fingerprints"] = [events[0]["id"]]
        d2 = decide_flush(
            content=text, events=events, state=state, now=1e6 + 10_000, force=True
        )
        self.assertFalse(d2["flush"])
        self.assertEqual(d2["reason"], "unchanged")

    def test_gh_still_read_only(self) -> None:
        from ingest.events_fetch import EventsFetcher
        from ingest.github_poller import GhResponse

        calls: list[str] = []

        def runner(args: list[str]) -> GhResponse:
            calls.append(" ".join(args))
            return GhResponse(status=404, headers={}, body="")

        with tempfile.TemporaryDirectory() as td:
            EventsFetcher(cache_dir=Path(td), runner=runner).fetch()  # type: ignore[arg-type]
        joined = " ".join(calls).lower()
        for bad in (" -x post", "-x patch", "-x delete", " merge", " comment"):
            self.assertNotIn(bad.strip(), joined)
        self.assertTrue(any("contents/events.jsonl" in c for c in calls))


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    log = EVIDENCE / "delta_behavioral_run.txt"
    with log.open("w", encoding="utf-8") as fh:
        result = unittest.TextTestRunner(verbosity=2, stream=fh).run(suite)
    print(log.read_text(encoding="utf-8"))
    summary = {
        "testsRun": result.testsRun,
        "failures": [(str(t), e) for t, e in result.failures],
        "errors": [(str(t), e) for t, e in result.errors],
        "skipped": [(str(t), s) for t, s in result.skipped],
        "wasSuccessful": result.wasSuccessful(),
    }
    EVIDENCE.joinpath("delta_behavioral_results.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise
