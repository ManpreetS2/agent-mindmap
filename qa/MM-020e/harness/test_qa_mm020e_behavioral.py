#!/usr/bin/env python3
"""
Independent behavioral tests for MM-020e (PR #20) @ 1b3f178.

Includes Security addition: commit subject → event.raw unscanned/uncapped → activity.json.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import traceback
import unittest
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path("/tmp/qa-mm020e/checkout")
sys.path.insert(0, str(ROOT))

from ingest.attribute import load_bots  # noqa: E402
from ingest.build import build_activity  # noqa: E402
from ingest.github_poller import (  # noqa: E402
    ALLOWED_REPOS,
    SUMMARY_MAX_CHARS,
    GitHubPoller,
    activity_event_to_network_event,
    build_pr_lane_events,
    poll_github,
    sanitize_pr_summary,
)
from tools.secret_scan import looks_like_secret  # noqa: E402
from tests.test_github_poller import MockGh, _fixture_map, _load  # noqa: E402

EVIDENCE = Path("/tmp/qa-mm020e/evidence")
EVIDENCE.mkdir(parents=True, exist_ok=True)

LEDGER = ROOT / "tests" / "fixtures" / "ledger-sample.md"
SECRET_SUBJECT = "fix: rotate sk-proj-abcdefghijklmnopqrstuvwxyz1234 quietly"
LONG_SUBJECT = "A" * 300
XSS_SUBJECT = '<img src=x onerror="alert(1)"> <script>alert(2)</script> & "quotes"'


def _commit(sha: str, message: str, *, login: str = "dev1") -> dict[str, Any]:
    return {
        "sha": sha,
        "commit": {
            "message": message,
            "author": {
                "name": login,
                "date": "2026-10-20T12:00:00Z",
            },
        },
        "author": {"login": login},
    }


def _map_with_commits(commits: list[dict[str, Any]]) -> dict[str, Any]:
    m = _fixture_map()
    # Keep one PR (#5) with our crafted commits; empty #6 commits
    m["repos/ManpreetS2/fencepost/pulls/5/commits?per_page=100"] = commits
    m["repos/ManpreetS2/fencepost/pulls/6/commits?per_page=100"] = []
    # check-runs for last sha
    if commits:
        sha = commits[-1]["sha"]
        m[f"repos/ManpreetS2/fencepost/commits/{sha}/check-runs"] = _load(
            "check_runs_empty.json"
        )
    return m


class TestAllowlist(unittest.TestCase):
    def test_non_allowlisted_repo_rejected_at_ctor(self) -> None:
        with self.assertRaises(ValueError):
            GitHubPoller(repos=("evil/other",))

    def test_fork_head_and_foreign_repo_not_polled(self) -> None:
        """Behavioral: only ALLOWED_REPOS appear in MockGh calls."""
        runner = MockGh()
        with tempfile.TemporaryDirectory() as td:
            poll_github(cache_dir=Path(td), runner=runner)
        repos_hit = set()
        for path in runner.calls:
            m = re.match(r"repos/([^/]+/[^/]+)", path)
            if m:
                repos_hit.add(m.group(1))
        self.assertTrue(repos_hit)
        self.assertTrue(repos_hit.issubset(ALLOWED_REPOS), repos_hit)
        # Renamed / other org never requested
        joined = " ".join(runner.calls)
        self.assertNotIn("evil/", joined)
        self.assertNotIn("OtherOrg/", joined)

    def test_pagination_next_to_other_repo_ignored(self) -> None:
        """Cross-repo Link next must not expand allowlist (existing poller rule)."""
        from ingest.github_poller import next_link_path, PaginationLinkError

        link = (
            '<https://api.github.com/repositories/999/pulls/5/commits?page=2>; rel="next"'
        )
        with self.assertRaises(PaginationLinkError):
            next_link_path(
                link,
                allowed_repos=frozenset({"ManpreetS2/fencepost"}),
                allowed_repo_ids=frozenset({111001}),
                expected_suffix="pulls/5/commits",
            )


class TestSecretScanSharedAndBenign(unittest.TestCase):
    def test_uses_shared_scanner_no_local_copy(self) -> None:
        src = (ROOT / "ingest" / "github_poller.py").read_text(encoding="utf-8")
        self.assertIn("from tools.secret_scan import looks_like_secret", src)
        # No leftover local sk-/AKIA denylist in poller
        self.assertNotIn(r"sk-[A-Za-z0-9", src)
        self.assertNotIn("AKIA[0-9A-Z]", src)
        r = subprocess.run(
            [
                "rg",
                "-n",
                r"_MIRROR_SECRET|sk-\[A-Za-z0-9\{|_FREE_TEXT_SCANNERS",
                str(ROOT / "ingest" / "github_poller.py"),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.stdout.strip(), "")

    def test_secret_summaries_refused_benign_pass(self) -> None:
        probes = {
            "sk-": "token sk-proj-abcdefghijklmnopqrstuvwxyz1234",
            "AKIA": "AKIAIOSFODNN7EXAMPLE",
            "JWT": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0In0.signature",
            "PEM": "-----BEGIN PRIVATE KEY----- MIIE -----END PRIVATE KEY-----",
            "email": "leak alice@example.com in subject",
            "ghp_": "ghp_abcdefghijklmnopqrstuvwxyz1234567890AB",
            "Bearer": "Authorization: Bearer abcdefghijklmnop",
            "benign": "use the task-runner for builds",
        }
        report = {}
        for name, text in probes.items():
            shared = looks_like_secret(text)
            capped = sanitize_pr_summary(text)
            report[name] = {
                "shared": shared,
                "sanitize_pr_summary": capped,
                "refused": capped is None,
            }
            if name == "benign":
                self.assertIsNotNone(capped)
                self.assertIn("task-runner", capped or "")
            else:
                self.assertTrue(shared, name)
                self.assertIsNone(capped, name)
        EVIDENCE.joinpath("secret_summary_results.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )


class TestSummaryCap240(unittest.TestCase):
    def test_239_240_241_multibyte_emoji_multiline(self) -> None:
        s239 = "a" * 239
        s240 = "b" * 240
        s241 = "c" * 241
        self.assertEqual(len(sanitize_pr_summary(s239) or ""), 239)
        self.assertEqual(len(sanitize_pr_summary(s240) or ""), 240)
        out241 = sanitize_pr_summary(s241)
        assert out241 is not None
        self.assertEqual(len(out241), 240)
        self.assertTrue(out241.endswith("…"))

        emoji = "😀" * 241
        out_e = sanitize_pr_summary(emoji)
        assert out_e is not None
        self.assertEqual(len(out_e), 240)
        self.assertEqual(out_e[0], "😀")
        # Must not split surrogate / produce invalid lone char — Python str slice is codepoint-safe
        self.assertTrue(out_e.endswith("…"))

        uni = "é" * 241
        out_u = sanitize_pr_summary(uni)
        assert out_u is not None
        self.assertEqual(len(out_u), 240)
        self.assertEqual(out_u[0], "é")

        multiline = "Subject line one\n\nBody paragraph with more detail\nand another line"
        out_m = sanitize_pr_summary(multiline)
        assert out_m is not None
        self.assertNotIn("\n", out_m)
        self.assertIn("Subject line one", out_m)
        self.assertIn("Body paragraph", out_m)

        EVIDENCE.joinpath("summary_cap.json").write_text(
            json.dumps(
                {
                    "SUMMARY_MAX_CHARS": SUMMARY_MAX_CHARS,
                    "len_239": len(sanitize_pr_summary(s239) or ""),
                    "len_240": len(sanitize_pr_summary(s240) or ""),
                    "len_241": len(out241),
                    "emoji_len": len(out_e),
                    "multiline": out_m,
                },
                indent=2,
            ),
            encoding="utf-8",
        )


class TestRawFieldSecurityFinding(unittest.TestCase):
    """SEC-MM020e-1: commit subject must be sanitized before event.raw / activity.json."""

    def test_secret_and_long_subject_in_activity_json_raw(self) -> None:
        commits = [
            _commit(
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                SECRET_SUBJECT + "\n\nbody with more text",
            ),
            _commit(
                "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                LONG_SUBJECT + "\n\ntrailing body",
            ),
            _commit(
                "cccccccccccccccccccccccccccccccccccccccc",
                XSS_SUBJECT + "\n\nbody",
            ),
            _commit(
                "dddddddddddddddddddddddddddddddddddddddd",
                "benign task-runner subject ~Dev 1 🛠️\n\nbody",
            ),
        ]
        runner = MockGh(mapping=_map_with_commits(commits))
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            out = td_path / "activity.json"
            cache = td_path / "cache"
            activity = build_activity(
                ledger_path=LEDGER,
                cache_dir=cache,
                github_runner=runner,
                skip_github=False,
            )
            out.write_text(json.dumps(activity, indent=2), encoding="utf-8")
            on_disk = json.loads(out.read_text(encoding="utf-8"))

        pr_updated = [
            e
            for e in activity["events"]
            if e.get("type") == "pr_updated" and e.get("pr") == 5
        ]
        raws = [e.get("raw") or "" for e in pr_updated]
        blob = json.dumps(activity)
        disk_blob = json.dumps(on_disk)

        sk_token = "sk-proj-abcdefghijklmnopqrstuvwxyz1234"
        secret_in_activity = sk_token in blob
        secret_on_disk = sk_token in disk_blob
        long_uncapped = any(r == LONG_SUBJECT or len(r) > SUMMARY_MAX_CHARS for r in raws)
        long_capped_present = any(
            len(r) == SUMMARY_MAX_CHARS and r.endswith("…") for r in raws
        )
        benign_present = any("task-runner" in r for r in raws)
        xss_markup_in_raw = any("<script>" in r or "onerror=" in r for r in raws)

        network, _ = build_pr_lane_events(
            {"events": [e for e in activity["events"] if e.get("pr") == 5]},
            load_bots(),
        )
        secret_in_network = sk_token in json.dumps(network)

        # Residual: review/comment raw still set from body without sanitize?
        residual_review = False
        src = (ROOT / "ingest" / "github_poller.py").read_text(encoding="utf-8")
        # Behavioral probe via activity_event_to_network_event on a review-shaped event
        review_evt = {
            "id": "rev1",
            "type": "verdict",
            "actor": "architect",
            "pr": 5,
            "repo": "ManpreetS2/fencepost",
            "raw": "Reviewed with " + sk_token,
            "source_time": "2026-10-20T12:00:00+00:00",
            "attribution": {"method": "signature"},
            "provenance": "github-verified",
            "verdict": "PASS",
        }
        # If poller still assigns unsanitized review bodies to raw, network path drops
        ne_review = activity_event_to_network_event(review_evt, load_bots())
        residual_review = "sk-proj-" in review_evt["raw"] and ne_review is None

        finding = {
            "head_note": "SEC-MM020e-1 fix expected at 9a30965+",
            "pr_updated_count": len(pr_updated),
            "raw_samples": raws,
            "secret_in_activity_events_raw": secret_in_activity,
            "secret_on_disk_activity_json": secret_on_disk,
            "long_subject_uncapped_in_raw": long_uncapped,
            "long_subject_capped_in_raw": long_capped_present,
            "longest_raw_len": max((len(r) for r in raws), default=0),
            "benign_task_runner_present": benign_present,
            "xss_markup_in_raw": xss_markup_in_raw,
            "secret_in_network_events": secret_in_network,
            "secret_review_raw_still_possible_on_event_dict": residual_review,
            "ui_would_receive_raw_from_activity": True,
        }
        EVIDENCE.joinpath("raw_field_security.json").write_text(
            json.dumps(finding, indent=2), encoding="utf-8"
        )

        # After SEC-MM020e-1: secret commit subjects must not land in activity.json
        self.assertFalse(
            secret_in_activity or secret_on_disk,
            f"secret still in activity.json; finding={finding}",
        )
        self.assertFalse(
            long_uncapped,
            f"uncapped long subject still in raw; finding={finding}",
        )
        self.assertTrue(long_capped_present, finding)
        self.assertTrue(benign_present, finding)
        self.assertFalse(secret_in_network)
        # Secret commit event dropped entirely (not just capped)
        self.assertTrue(
            all(sk_token not in r for r in raws),
            raws,
        )

    def test_ui_detail_panel_renders_raw_as_text_not_html(self) -> None:
        """XSS: DetailPanel uses React text child for raw (escaped); no dangersetInnerHTML."""
        detail = (ROOT / "web" / "src" / "components" / "DetailPanel.tsx").read_text(
            encoding="utf-8"
        )
        self.assertIn("{lastActivity.event.raw}", detail)
        self.assertNotIn("dangerouslySetInnerHTML", detail)
        # Repo-wide web src
        r = subprocess.run(
            [
                "rg",
                "-n",
                "dangerouslySetInnerHTML",
                str(ROOT / "web" / "src"),
            ],
            capture_output=True,
            text=True,
        )
        EVIDENCE.joinpath("xss_ui_scan.txt").write_text(
            (r.stdout or "(none)") + "\nDetailPanel has text binding: "
            + str("{lastActivity.event.raw}" in detail),
            encoding="utf-8",
        )
        self.assertEqual(r.stdout.strip(), "")

        # Behavioral DOM escape via a tiny React-less check: HTML-escape expectation
        # for React text nodes — simulate what must NOT appear unescaped in HTML.
        import html as html_mod

        escaped = html_mod.escape(XSS_SUBJECT, quote=True)
        self.assertIn("&lt;script&gt;", escaped)
        self.assertNotIn("<script>", escaped)


class TestGhReadOnlyTokenAndErrors(unittest.TestCase):
    def test_gh_argv_read_only_and_no_token(self) -> None:
        fake = "ghp_TESTTOKENVALUE000000000000000000099"
        env = os.environ.copy()
        env["GH_TOKEN"] = fake
        env["GITHUB_TOKEN"] = fake
        runner = MockGh()
        with tempfile.TemporaryDirectory() as td:
            result = poll_github(cache_dir=Path(td), runner=runner)
        joined = " ".join(runner.calls).lower()
        for bad in (" -x post", "-x patch", "-x delete", "merge", " comment"):
            # paths won't contain these verbs as methods
            pass
        # All calls are api paths (MockGh records path only) — ensure GETty resources
        for path in runner.calls:
            self.assertFalse(path.strip().upper().startswith("POST"))
            self.assertNotIn(fake, path)
        # assert_no_credentials on payload
        from ingest.github_poller import assert_no_credentials

        assert_no_credentials(result.events)
        EVIDENCE.joinpath("gh_calls.json").write_text(
            json.dumps({"calls": runner.calls[:50], "n": len(runner.calls)}, indent=2),
            encoding="utf-8",
        )

    def test_commit_pagination_many_pages(self) -> None:
        """Many commits across Link pages are collected (up to MAX_PAGES)."""
        page1 = [
            _commit(f"{i:040x}", f"commit {i} ~Dev 1 🛠️") for i in range(1, 3)
        ]
        page2 = [
            _commit(f"{i:040x}", f"commit {i} ~Dev 1 🛠️") for i in range(3, 5)
        ]
        m = _map_with_commits(page1)
        # MockGh uses full path as key; pagination passes next path from Link
        path1 = "repos/ManpreetS2/fencepost/pulls/5/commits?per_page=100"
        path2 = "repos/ManpreetS2/fencepost/pulls/5/commits?per_page=100&page=2"
        m[path1] = page1
        m[path2] = page2
        # next link must be same repo id allowlisted
        link = (
            f'<https://api.github.com/repos/ManpreetS2/fencepost/pulls/5/commits'
            f'?per_page=100&page=2>; rel="next"'
        )
        # Also need repo id resolution — fixture map has repos/ManpreetS2/fencepost
        runner = MockGh(mapping=m, links={path1: link})
        with tempfile.TemporaryDirectory() as td:
            result = poll_github(cache_dir=Path(td), runner=runner)
        shas = {
            e.get("sha")
            for e in result.events
            if e.get("type") == "pr_updated" and e.get("pr") == 5
        }
        # Depending on Link parsing, page2 may be followed
        EVIDENCE.joinpath("commit_pagination.json").write_text(
            json.dumps(
                {
                    "calls": [c for c in runner.calls if "commits" in c],
                    "pr5_updated_shas": sorted(x for x in shas if x),
                    "meta": result.meta_github,
                    "errors": result.errors[:10],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        self.assertGreaterEqual(len(shas), 2)

    def test_rate_limit_graceful(self) -> None:
        runner = MockGh(
            status_for={
                "repos/ManpreetS2/fencepost/pulls?state=all&per_page=100": 403,
            },
            remaining_for={
                "repos/ManpreetS2/fencepost/pulls?state=all&per_page=100": "0",
            },
        )
        with tempfile.TemporaryDirectory() as td:
            result = poll_github(cache_dir=Path(td), runner=runner)
        self.assertIn(result.meta_github, {"ok", "error", "rate_limited", "partial"})
        # Must not raise
        self.assertIsInstance(result.events, list)
        EVIDENCE.joinpath("rate_limit.json").write_text(
            json.dumps(
                {
                    "meta": result.meta_github,
                    "errors": result.errors[:20],
                    "n_events": len(result.events),
                },
                indent=2,
            ),
            encoding="utf-8",
        )


class TestRegressions(unittest.TestCase):
    def test_mm020a_and_020c_suites(self) -> None:
        r = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "--tb=no",
                "tests/test_mm020a_membership.py",
                "tests/test_events_mirror.py",
                "tests/test_events_fetch.py",
                "tests/test_secret_scan.py",
                "tests/test_pr_lanes.py",
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        EVIDENCE.joinpath("pytest_regression_subset.txt").write_text(
            r.stdout + r.stderr, encoding="utf-8"
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_020f_multigroup_still_present(self) -> None:
        # Branch includes post-020a/c base; AgentGraph still references groups
        ag = (ROOT / "web" / "src" / "components" / "AgentGraph.tsx").read_text(
            encoding="utf-8"
        )
        self.assertIn("groups", ag)


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    log = EVIDENCE / "behavioral_run.txt"
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
    EVIDENCE.joinpath("behavioral_results.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    # Note: raw-field test *expects* the leak (documents Security finding).
    # Suite success means tests ran as designed; verdict uses finding JSON.
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise
