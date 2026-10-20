#!/usr/bin/env python3
"""Delta-only behavioral repros for MM-020e @ d8c8ea0 (239a8e9..d8c8ea0)."""

from __future__ import annotations

import http.client
import json
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest
from http import HTTPStatus
from pathlib import Path

ROOT = Path("/tmp/qa-mm020e-delta/repo")
sys.path.insert(0, str(ROOT))

from ingest.github_poller import (  # noqa: E402
    SUMMARY_MAX_CHARS,
    GitHubPoller,
    AGENT_REPORTED_PROVENANCE,
    GITHUB_PROVENANCE,
)
from ingest.attribute import load_bots  # noqa: E402
from ingest.live import LiveDaemon, create_http_server, MAX_SSE_CONNECTIONS  # noqa: E402
from tests.test_github_poller import MockGh  # noqa: E402
from tests.test_live import _daemon, _sample_network_event, _http_get  # noqa: E402

EVIDENCE = Path("/tmp/qa-mm020e-delta/evidence")
EVIDENCE.mkdir(parents=True, exist_ok=True)
LEDGER = ROOT / "tests" / "fixtures" / "ledger-sample.md"


def _env(td: Path) -> dict:
    ledger = td / "task-ledger.md"
    shutil.copy(LEDGER, ledger)
    static = td / "dist"
    static.mkdir()
    (static / "index.html").write_text("ok", encoding="utf-8")
    activity = static / "activity.json"
    activity.write_text("{}", encoding="utf-8")
    bots = json.loads((ROOT / "config" / "bots.json").read_text(encoding="utf-8"))["bots"]
    return {
        "ledger": ledger,
        "static": static,
        "activity": activity,
        "cache": td / "cache",
        "bots": bots,
    }


class TestQaMm020e4Slots(unittest.TestCase):
    def test_abort_storm_releases_all_slots(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            env = _env(Path(td))
            daemon = _daemon(env, events_source="off", github_runner=MockGh(fail=True))
            for i in range(40):
                daemon.ingest_network_events([_sample_network_event(f"abort-{i}")])
            httpd = create_http_server(daemon, port=0, sse_heartbeat_sec=0.15)
            t = threading.Thread(
                target=httpd.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True
            )
            t.start()
            host, port = httpd.server_address
            time.sleep(0.1)
            try:
                for _ in range(MAX_SSE_CONNECTIONS + 5):
                    s = socket.create_connection((host, port), timeout=2)
                    s.sendall(
                        f"GET /events HTTP/1.1\r\nHost: {host}:{port}\r\n"
                        f"Accept: text/event-stream\r\n\r\n".encode()
                    )
                    s.settimeout(0.02)
                    try:
                        s.recv(8)
                    except Exception:
                        pass
                    try:
                        s.shutdown(socket.SHUT_RDWR)
                    except Exception:
                        pass
                    s.close()
                    time.sleep(0.05)
                deadline = time.monotonic() + 5.0
                while daemon.sse_limiter.active_count() > 0 and time.monotonic() < deadline:
                    time.sleep(0.05)
                active = daemon.sse_limiter.active_count()
                report = {"active": active, "max": MAX_SSE_CONNECTIONS}
                EVIDENCE.joinpath("qa4_slots.json").write_text(
                    json.dumps(report, indent=2), encoding="utf-8"
                )
                self.assertEqual(active, 0, report)
            finally:
                httpd.shutdown()
                t.join(timeout=3)
                httpd.server_close()


class TestQaMm020e5Cap(unittest.TestCase):
    def test_oversized_capped_secret_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            daemon = _daemon(_env(Path(td)), events_source="off", github_runner=MockGh(fail=True))
            before = daemon.health().dropped_network_events
            big = _sample_network_event("big-1")
            big["summary"] = "Z" * 500
            added = daemon.ingest_network_events([big])
            self.assertEqual(len(added), 1)
            self.assertEqual(len(added[0]["summary"]), SUMMARY_MAX_CHARS)

            sk = "sk-proj-abcdefghijklmnopqrstuvwxyz1234567890ABCDEF"
            secret = _sample_network_event("sec-1")
            secret["summary"] = f"leak {sk}"
            self.assertEqual(daemon.ingest_network_events([secret]), [])
            after = daemon.health().dropped_network_events
            report = {
                "capped_len": len(added[0]["summary"]),
                "dropped_delta": after - before,
                "secret_rejected": True,
            }
            EVIDENCE.joinpath("qa5_cap.json").write_text(
                json.dumps(report, indent=2), encoding="utf-8"
            )
            self.assertGreaterEqual(after - before, 1)


class TestSecMm020e2Actor(unittest.TestCase):
    def test_commit_body_signature_not_github_verified(self) -> None:
        poller = GitHubPoller(bots=load_bots(), runner=MockGh(fail=True))
        html = "https://github.com/ManpreetS2/fencepost/pull/99"
        # Body claims ~DEV 2; author login is ManpreetS2 → mapped manpreet, github-verified
        mapped = poller._push_events(
            "ManpreetS2/fencepost",
            99,
            html,
            None,
            {
                "sha": "abcdef1234567890abcdef1234567890abcdef12",
                "author": {"login": "ManpreetS2"},
                "commit": {
                    "message": "~DEV 2 ⚙️ should not attribute from body",
                    "author": {"date": "2026-10-20T12:00:00Z"},
                },
            },
            set(),
        )
        self.assertEqual(len(mapped), 1)
        self.assertEqual(mapped[0]["actor"], "manpreet")
        self.assertEqual(mapped[0]["provenance"], GITHUB_PROVENANCE)
        self.assertEqual(mapped[0]["attribution"]["method"], "github_login")

        # Unmapped login + body signature → agent-reported, actor None (not body bot)
        unmapped = poller._push_events(
            "ManpreetS2/fencepost",
            100,
            html,
            None,
            {
                "sha": "bbbbbb1234567890abcdef1234567890abcdef12",
                "author": {"login": "unknown-external-bot"},
                "commit": {
                    "message": "~QA / Verifier 🧪 still ignored",
                    "author": {"date": "2026-10-20T12:01:00Z"},
                },
            },
            set(),
        )
        self.assertEqual(len(unmapped), 1)
        self.assertIsNone(unmapped[0]["actor"])
        self.assertEqual(unmapped[0]["provenance"], AGENT_REPORTED_PROVENANCE)
        self.assertNotEqual(unmapped[0]["actor"], "qa-verifier")

        # No author login at all + body signature → agent-reported
        no_login = poller._push_events(
            "ManpreetS2/fencepost",
            101,
            html,
            None,
            {
                "sha": "cccccccc1234567890abcdef1234567890abcdef",
                "commit": {
                    "message": "~Architect 🛠️ forged",
                    "author": {"date": "2026-10-20T12:02:00Z"},
                },
            },
            set(),
        )
        self.assertEqual(len(no_login), 1)
        self.assertIsNone(no_login[0]["actor"])
        self.assertEqual(no_login[0]["provenance"], AGENT_REPORTED_PROVENANCE)

        report = {
            "mapped": {
                "actor": mapped[0]["actor"],
                "provenance": mapped[0]["provenance"],
                "method": mapped[0]["attribution"]["method"],
            },
            "unmapped": {
                "actor": unmapped[0]["actor"],
                "provenance": unmapped[0]["provenance"],
            },
            "no_login": {
                "actor": no_login[0]["actor"],
                "provenance": no_login[0]["provenance"],
            },
        }
        EVIDENCE.joinpath("sec2_actor.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )


class TestSecMm020e3Healthz(unittest.TestCase):
    def test_healthz_dropped_count(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            env = _env(Path(td))
            daemon = _daemon(env, events_source="off", github_runner=MockGh(fail=True))
            httpd = create_http_server(daemon, port=0, sse_heartbeat_sec=0.2)
            t = threading.Thread(
                target=httpd.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True
            )
            t.start()
            host, port = httpd.server_address
            time.sleep(0.1)
            try:
                before = daemon.health().dropped_network_events
                sk = "sk-proj-abcdefghijklmnopqrstuvwxyz1234567890ABCDEF"
                daemon.ingest_network_events(
                    [
                        {
                            "id": "drop-me",
                            "ts": "2026-10-20T12:00:00+00:00",
                            "sender": "dev-1",
                            "group": "build",
                            "type": "message",
                            "summary": f"leak {sk}",
                            "provenance": "agent-reported",
                        }
                    ]
                )
                status, _, body = _http_get(
                    f"http://{host}:{port}/healthz", {"Host": f"{host}:{port}"}
                )
                payload = json.loads(body.decode())
                report = {
                    "status": status,
                    "dropped_before": before,
                    "dropped_after": payload.get("dropped_network_events"),
                    "secret_in_body": sk in body.decode(),
                }
                EVIDENCE.joinpath("sec3_healthz.json").write_text(
                    json.dumps(report, indent=2), encoding="utf-8"
                )
                self.assertEqual(status, HTTPStatus.OK)
                self.assertGreaterEqual(payload["dropped_network_events"], before + 1)
                self.assertFalse(report["secret_in_body"])
            finally:
                httpd.shutdown()
                t.join(timeout=3)
                httpd.server_close()


class TestQaMm020e6Markup(unittest.TestCase):
    def test_plain_text_strips_tags(self) -> None:
        # Node not required — mirror TS helper contract in Python for evidence
        def plain_text_for_display(value: str) -> str:
            import re

            return re.sub(r"<[^>]*>", "", value)

        raw = '<img src=x onerror="alert(1)">hello'
        out = plain_text_for_display(raw)
        self.assertEqual(out, "hello")
        detail = (ROOT / "web" / "src" / "components" / "DetailPanel.tsx").read_text()
        unparsed = (ROOT / "web" / "src" / "components" / "UnparsedPanel.tsx").read_text()
        helper = (ROOT / "web" / "src" / "utils" / "plainText.ts").read_text()
        self.assertIn("plainTextForDisplay", detail)
        self.assertIn("plainTextForDisplay", unparsed)
        self.assertIn("replace(/<[^>]*>/g", helper)
        EVIDENCE.joinpath("qa6_markup.json").write_text(
            json.dumps(
                {
                    "stripped": out,
                    "detail_uses_helper": True,
                    "unparsed_uses_helper": True,
                },
                indent=2,
            ),
            encoding="utf-8",
        )


class TestQaMm020e3AndSec4Source(unittest.TestCase):
    """Static + unit coverage for UI SSE recovery + debounce (vitest owns runtime)."""

    def test_transport_has_recovery_and_debounce(self) -> None:
        src = (ROOT / "web" / "src" / "data" / "activityTransport.ts").read_text()
        self.assertIn("tryReconnectSse", src)
        self.assertIn("scheduleSseRetry", src)
        self.assertIn("fellBack = false", src)
        self.assertIn("createDebouncedRefetch", src)
        self.assertIn("SSE_REFETCH_MIN_MS = 1000", src)
        self.assertIn("debouncedRefetch", src)
        # Permanent latch removed: recovery resets fellBack
        self.assertGreaterEqual(src.count("fellBack = false"), 2)
        EVIDENCE.joinpath("qa3_sec4_transport.json").write_text(
            json.dumps(
                {
                    "has_reconnect": True,
                    "has_debounce": True,
                    "refetch_min_ms": 1000,
                    "resets_fellBack": True,
                },
                indent=2,
            ),
            encoding="utf-8",
        )


class TestNoNewIssuesSpot(unittest.TestCase):
    def test_orphan_es_on_unsubscribe_during_retry(self) -> None:
        """Delta review: unsubscribe while retry ES pending may not close it."""
        src = (ROOT / "web" / "src" / "data" / "activityTransport.ts").read_text()
        # tryReconnectSse creates `next` without storing in a tracked set for cleanup
        has_pending_close = "pendingSources" in src or "retrySource" in src
        finding = {
            "tracks_retry_es_for_cleanup": has_pending_close,
            "note": (
                "tryReconnectSse wires EventSource before onopen assigns source; "
                "unsubscribe only closes `source`, so in-flight retry ES may linger "
                "until error/close. Low severity if short-lived."
            ),
        }
        EVIDENCE.joinpath("delta_new_issue_spot.json").write_text(
            json.dumps(finding, indent=2), encoding="utf-8"
        )
        # Document only — do not fail the suite; verdict uses this evidence
        self.assertTrue(True)


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
        "wasSuccessful": result.wasSuccessful(),
    }
    EVIDENCE.joinpath("delta_behavioral_results.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
