#!/usr/bin/env python3
"""
Behavioral SEC-MM020b-1 / SEC-MM020b-2 tests for PR #17 @ 692216d.

These tests exercise the public API and OS-visible effects only.
They do not inspect tools/event_emit.py source for flags or constants.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path("/tmp/qa-mm020b-r2/checkout")
sys.path.insert(0, str(ROOT))

from tools.event_emit import (  # noqa: E402
    SecretRefusedError,
    SymlinkRefusedError,
    emit_message,
    sanitize_summary,
    summary_safe_for_emit,
)


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


class TestSecMm020b1SymlinkAndMode(unittest.TestCase):
    """SEC-MM020b-1: O_NOFOLLOW behavior + 0o600 create / existing mode handling."""

    def test_symlinked_target_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            real = td_path / "real.jsonl"
            link = td_path / "events.jsonl"
            real.write_bytes(b"")
            os.symlink(real, link)
            before = real.stat().st_size
            with self.assertRaises(SymlinkRefusedError) as ctx:
                emit_message(
                    link,
                    sender="dev-1",
                    group="build",
                    summary="via symlink",
                    ts="2026-10-20T12:00:00+00:00",
                )
            self.assertIn("symlink", str(ctx.exception).lower())
            self.assertEqual(real.stat().st_size, before)
            self.assertTrue(link.is_symlink())
            # Dangling symlink also refused
            dangling = td_path / "dangling.jsonl"
            os.symlink(td_path / "missing.jsonl", dangling)
            with self.assertRaises(SymlinkRefusedError):
                emit_message(
                    dangling,
                    sender="dev-1",
                    group="build",
                    summary="dangling",
                    ts="2026-10-20T12:00:01+00:00",
                )

    def test_o_nofollow_via_sys_audit_open_flags(self) -> None:
        """Confirm os open flags include O_NOFOLLOW via sys.audit (no source read)."""
        opens: list[tuple] = []

        def hook(event: str, args: tuple) -> None:
            if event == "open":
                opens.append(tuple(args))

        sys.addaudithook(hook)
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "events.jsonl"
            opens.clear()
            emit_message(
                out,
                sender="dev-1",
                group="build",
                summary="audit probe",
                ts="2026-10-20T12:00:00+00:00",
            )
            matched_flags: list[int] = []
            for a in opens:
                if "events.jsonl" not in str(a[0]):
                    continue
                for idx, val in enumerate(a[1:], start=1):
                    if isinstance(val, int) and (val & os.O_CREAT) and (val & os.O_APPEND):
                        matched_flags.append(val)
            self.assertTrue(matched_flags, f"no open flags for target; events={opens!r}")
            flags = matched_flags[-1]
            self.assertTrue(flags & os.O_NOFOLLOW, f"O_NOFOLLOW missing; flags={hex(flags)}")
            self.assertTrue(flags & os.O_APPEND)
            self.assertTrue(flags & os.O_CREAT)

    def test_new_file_created_mode_0o600(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "events.jsonl"
            self.assertFalse(out.exists())
            emit_message(
                out,
                sender="dev-1",
                group="build",
                summary="mode create",
                ts="2026-10-20T12:00:00+00:00",
            )
            mode = _mode(out)
            self.assertEqual(
                mode,
                0o600,
                f"expected 0o600, got {oct(mode)}",
            )
            self.assertFalse(mode & stat.S_IROTH)
            self.assertFalse(mode & stat.S_IWOTH)
            self.assertFalse(mode & stat.S_IRGRP)
            self.assertFalse(mode & stat.S_IWGRP)

    def test_preexisting_file_mode_handled(self) -> None:
        """Document/assert behavior when JSONL already exists with a looser mode."""
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "events.jsonl"
            out.write_text("", encoding="utf-8")
            os.chmod(out, 0o644)
            self.assertEqual(_mode(out), 0o644)
            emit_message(
                out,
                sender="dev-1",
                group="build",
                summary="preexisting mode",
                ts="2026-10-20T12:00:00+00:00",
            )
            after = _mode(out)
            # Record actual behavior: either tightened to 0o600 or left as-is.
            # SEC expectation: pre-existing file's mode is also handled (tightened).
            self.assertTrue(out.stat().st_size > 0)
            self.assertEqual(
                after,
                0o600,
                f"pre-existing 0o644 not tightened; after={oct(after)}",
            )

    def test_preexisting_world_writable_tightened_or_refused(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "events.jsonl"
            out.write_text("", encoding="utf-8")
            os.chmod(out, 0o666)
            emit_message(
                out,
                sender="dev-1",
                group="build",
                summary="world writable preexisting",
                ts="2026-10-20T12:00:01+00:00",
            )
            after = _mode(out)
            self.assertEqual(
                after,
                0o600,
                f"pre-existing 0o666 not handled; after={oct(after)}",
            )


class TestSecMm020b2SummaryCap(unittest.TestCase):
    """SEC-MM020b-2: 240-char cap + docstring contract + refuse path."""

    def test_docstring_states_240_contract(self) -> None:
        # Contract via published docs on the API objects (not by opening .py files).
        docs = " ".join(
            filter(
                None,
                [
                    sanitize_summary.__doc__,
                    emit_message.__doc__,
                    sys.modules["tools.event_emit"].__doc__,
                ],
            )
        )
        self.assertTrue(docs.strip(), "expected non-empty docstring(s)")
        lowered = docs.lower()
        self.assertTrue(
            "240" in docs or "summary_max_chars" in lowered,
            f"docstring must state 240-char contract; got:\n{docs}",
        )
        # Prefer explicit 240 mention
        self.assertIn("240", docs)

    def test_summary_len_239_240_241(self) -> None:
        s239 = "a" * 239
        s240 = "b" * 240
        s241 = "c" * 241
        out239 = sanitize_summary(s239)
        out240 = sanitize_summary(s240)
        out241 = sanitize_summary(s241)
        self.assertEqual(len(out239), 239)
        self.assertEqual(out239, s239)
        self.assertEqual(len(out240), 240)
        self.assertEqual(out240, s240)
        self.assertEqual(len(out241), 240)
        self.assertTrue(out241.endswith("…"))
        self.assertEqual(out241[:239], "c" * 239)

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "events.jsonl"
            for label, text, expect_len, expect_ellipsis in (
                ("239", s239, 239, False),
                ("240", s240, 240, False),
                ("241", s241, 240, True),
            ):
                evt = emit_message(
                    path,
                    sender="dev-1",
                    group="build",
                    summary=text,
                    ts=f"2026-10-20T12:00:0{label[0]}+00:00",
                )
                self.assertEqual(len(evt["summary"]), expect_len, label)
                self.assertEqual(evt["summary"].endswith("…"), expect_ellipsis, label)

    def test_multibyte_and_emoji_cap(self) -> None:
        # Multibyte unicode (each char length 1 in Python str)
        uni = "é" * 241
        capped = sanitize_summary(uni)
        self.assertEqual(len(capped), 240)
        self.assertTrue(capped.endswith("…"))
        self.assertEqual(capped[0], "é")

        emoji = "😀" * 241
        capped_e = sanitize_summary(emoji)
        self.assertEqual(len(capped_e), 240)
        self.assertTrue(capped_e.endswith("…"))
        self.assertEqual(capped_e[0], "😀")

        # Mixed: 200 ascii + 50 emoji = 250 chars → 240
        mixed = ("x" * 200) + ("🚀" * 50)
        self.assertEqual(len(mixed), 250)
        capped_m = sanitize_summary(mixed)
        self.assertEqual(len(capped_m), 240)
        self.assertTrue(capped_m.endswith("…"))

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "events.jsonl"
            evt = emit_message(
                path,
                sender="dev-1",
                group="build",
                summary=emoji,
                ts="2026-10-20T12:00:00+00:00",
            )
            self.assertEqual(len(evt["summary"]), 240)
            line = path.read_bytes()
            # Still valid JSONL
            obj = json.loads(line.splitlines()[0])
            self.assertEqual(len(obj["summary"]), 240)

    def test_refuse_not_redact_nothing_written(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "secret.jsonl"
            with self.assertRaises(SecretRefusedError) as ctx:
                emit_message(
                    out,
                    sender="dev-1",
                    group="build",
                    summary="Authorization: Bearer abcdefghijklmnop",
                    ts="2026-10-20T12:00:00+00:00",
                )
            msg = str(ctx.exception).lower()
            self.assertIn("refus", msg)
            self.assertNotIn("ghp_", msg)
            self.assertNotIn("bearer abcdef", msg)
            self.assertFalse(out.exists())
            safe, err = summary_safe_for_emit(
                "token ghp_abcdefghijklmnopqrstuvwxyz1234567890AB"
            )
            self.assertIsNone(safe)
            self.assertIsNotNone(err)
            self.assertIn("refus", (err or "").lower())
            self.assertNotIn("ghp_", err or "")


if __name__ == "__main__":
    # Verbose result for evidence logs
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    # Machine-readable summary
    summary = {
        "testsRun": result.testsRun,
        "failures": [(str(t), str(e)) for t, e in result.failures],
        "errors": [(str(t), str(e)) for t, e in result.errors],
        "skipped": [(str(t), str(r)) for t, r in result.skipped],
        "wasSuccessful": result.wasSuccessful(),
    }
    out = Path("/tmp/qa-mm020b-r2/evidence/sec_behavioral_results.json")
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("\nWROTE", out)
    raise SystemExit(0 if result.wasSuccessful() else 1)
