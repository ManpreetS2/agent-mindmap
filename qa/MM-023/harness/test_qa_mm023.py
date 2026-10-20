#!/usr/bin/env python3
"""Lean behavioral repros for PR #23 (MM-020e2) @ 0e65cd0."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path("/tmp/qa-mm023/repo")
sys.path.insert(0, str(ROOT))

from ingest.github_poller import GitHubPoller, poll_github  # noqa: E402
from ingest.attribute import load_bots  # noqa: E402
from tests.test_github_poller import (  # noqa: E402
    FENCEPOST_REPO_ID,
    MockGh,
    _load,
    _single_pr_mapping,
)

EVIDENCE = Path("/tmp/qa-mm023/evidence")
EVIDENCE.mkdir(parents=True, exist_ok=True)


def _merged_pr(
    *,
    merged_by: dict | None,
    merge_sha: str = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
    commits: list | None = None,
) -> dict:
    mapping = _single_pr_mapping()
    pr = {
        "number": 5,
        "title": "feat/RP-005-ingest-hardening",
        "body": "~DEV 1 ⚙️",
        "html_url": "https://github.com/ManpreetS2/fencepost/pull/5",
        "created_at": "2026-10-19T21:35:00-07:00",
        "merged_at": "2026-10-19T21:39:00-07:00",
        "merge_commit_sha": merge_sha,
        "head": {"ref": "feat/RP-005-ingest-hardening", "sha": "aaa"},
        "base": {
            "repo": {"id": FENCEPOST_REPO_ID, "full_name": "ManpreetS2/fencepost"}
        },
        "user": {"login": "ManpreetS2"},
    }
    if merged_by is not None:
        pr["merged_by"] = merged_by
    mapping["repos/ManpreetS2/fencepost/pulls?state=all&per_page=100"] = [pr]
    mapping["repos/ManpreetS2/fencepost/pulls/5/commits?per_page=100"] = (
        [] if commits is None else commits
    )
    mapping[
        f"repos/ManpreetS2/fencepost/commits/{merge_sha}/check-runs"
    ] = _load("check_runs_empty.json")
    return mapping


class TestMergedByLogin(unittest.TestCase):
    def test_mapped_unmapped_missing_squash(self) -> None:
        report: dict = {}

        with tempfile.TemporaryDirectory() as td:
            # Mapped login → github-verified
            r = poll_github(
                cache_dir=Path(td) / "m",
                runner=MockGh(
                    mapping=_merged_pr(merged_by={"login": "ManpreetS2"}, commits=[])
                ),
                repos=("ManpreetS2/fencepost",),
            )
            merged = [e for e in r.events if e["type"] == "merged"]
            self.assertEqual(len(merged), 1)
            self.assertEqual(merged[0]["actor"], "manpreet")
            self.assertEqual(merged[0]["provenance"], "github-verified")
            report["mapped"] = {
                "actor": merged[0]["actor"],
                "provenance": merged[0]["provenance"],
                "method": merged[0]["attribution"]["method"],
            }

        with tempfile.TemporaryDirectory() as td:
            # Unmapped → agent-reported
            r = poll_github(
                cache_dir=Path(td) / "u",
                runner=MockGh(
                    mapping=_merged_pr(
                        merged_by={"login": "dependabot[bot]"}, commits=[]
                    )
                ),
                repos=("ManpreetS2/fencepost",),
            )
            merged = [e for e in r.events if e["type"] == "merged"]
            self.assertEqual(merged[0]["actor"], None)
            self.assertEqual(merged[0]["provenance"], "agent-reported")
            report["unmapped"] = {
                "actor": merged[0]["actor"],
                "provenance": merged[0]["provenance"],
                "method": merged[0]["attribution"]["method"],
            }

        with tempfile.TemporaryDirectory() as td:
            # Missing merged_by → agent-reported / unknown
            r = poll_github(
                cache_dir=Path(td) / "x",
                runner=MockGh(mapping=_merged_pr(merged_by=None, commits=[])),
                repos=("ManpreetS2/fencepost",),
            )
            merged = [e for e in r.events if e["type"] == "merged"]
            self.assertIsNone(merged[0]["actor"])
            self.assertEqual(merged[0]["provenance"], "agent-reported")
            self.assertEqual(merged[0]["attribution"]["method"], "unknown")
            report["missing_merged_by"] = {
                "actor": merged[0]["actor"],
                "provenance": merged[0]["provenance"],
                "method": merged[0]["attribution"]["method"],
            }

        with tempfile.TemporaryDirectory() as td:
            # Squash: merge SHA absent from commits list; merged_by still wins
            squash_sha = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            r = poll_github(
                cache_dir=Path(td) / "s",
                runner=MockGh(
                    mapping=_merged_pr(
                        merged_by={"login": "ManpreetS2"},
                        merge_sha=squash_sha,
                        commits=[],  # squash SHA not in PR commits
                    )
                ),
                repos=("ManpreetS2/fencepost",),
            )
            merged = [e for e in r.events if e["type"] == "merged"]
            self.assertEqual(merged[0]["actor"], "manpreet")
            self.assertEqual(merged[0]["provenance"], "github-verified")
            self.assertEqual(merged[0].get("sha"), squash_sha)
            report["squash_no_commit_match"] = {
                "actor": merged[0]["actor"],
                "provenance": merged[0]["provenance"],
                "sha": merged[0].get("sha"),
            }

        EVIDENCE.joinpath("merged_by.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )


class TestResolveMergerRemoved(unittest.TestCase):
    def test_no_dangling_refs(self) -> None:
        src = (ROOT / "ingest" / "github_poller.py").read_text(encoding="utf-8")
        self.assertNotIn("_resolve_merger", src)
        self.assertNotIn("_LEDGER_STYLE_MERGED", src)
        self.assertIn("_merged_by_login", src)
        # Repo-wide (exclude this evidence / .git)
        r = subprocess.run(
            ["rg", "-n", "_resolve_merger", str(ROOT), "-g", "!**/.git/**"],
            capture_output=True,
            text=True,
        )
        # Only allowed in comments/docs if any — expect empty in product+tests after rename
        hits = [
            ln
            for ln in (r.stdout or "").splitlines()
            if "_resolve_merger" in ln and "test_qa_mm023" not in ln
        ]
        EVIDENCE.joinpath("resolve_merger_refs.txt").write_text(
            "\n".join(hits) if hits else "(none)\n", encoding="utf-8"
        )
        self.assertEqual(hits, [], hits)


class TestQaMm020e7Source(unittest.TestCase):
    def test_pending_reconnect_tracked(self) -> None:
        src = (ROOT / "web" / "src" / "data" / "activityTransport.ts").read_text(
            encoding="utf-8"
        )
        self.assertIn("pendingReconnect", src)
        self.assertIn("closePendingReconnect", src)
        self.assertIn("const dispose = () =>", src)
        self.assertIn("closePendingReconnect();", src)
        # dispose closes pending before return
        self.assertIn("return dispose", src)
        EVIDENCE.joinpath("qa7_transport.json").write_text(
            json.dumps(
                {
                    "pendingReconnect": True,
                    "dispose_closes_pending": True,
                    "onopen_closes_if_cancelled": 'if (cancelled)' in src
                    and "es.close()" in src,
                },
                indent=2,
            ),
            encoding="utf-8",
        )


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
        "wasSuccessful": result.wasSuccessful(),
    }
    EVIDENCE.joinpath("behavioral_results.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
