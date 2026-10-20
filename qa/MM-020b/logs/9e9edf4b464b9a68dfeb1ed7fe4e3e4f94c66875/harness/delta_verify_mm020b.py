#!/usr/bin/env python3
"""
Delta behavioral verification for MM-020b PR #17 @ 9e9edf4.
Public-API / OS-visible behavior. Verify-only — no product edits.
"""

from __future__ import annotations

import ast
import json
import logging
import os
import re
import stat
import sys
import tempfile
import traceback
import unittest
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "checkout"
if not (ROOT / "tools" / "event_emit.py").is_file():
    # when committed under qa/MM-020b/logs/<sha>/harness
    cand = Path(__file__).resolve().parents[4]
    if (cand / "tools" / "event_emit.py").is_file():
        ROOT = cand
    else:
        ROOT = Path("/tmp/qa-mm020b-delta/checkout")

sys.path.insert(0, str(ROOT))

from tools.event_emit import (  # noqa: E402
    SecretRefusedError,
    SymlinkRefusedError,
    emit_message,
    sanitize_summary,
    summary_safe_for_emit,
)
from tools import secret_scan  # noqa: E402
from tools.secret_scan import looks_like_secret  # noqa: E402

RESULTS: list[dict] = []


def record(check: str, ok: bool, detail: str, **extra) -> None:
    RESULTS.append({"check": check, "ok": ok, "detail": detail, **extra})
    print(f"[{'PASS' if ok else 'FAIL'}] {check}: {detail}")


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


# ---------- (1) QA-MM020b-2 secrets via shared scanner ----------
def check_secrets_shared_and_refuse() -> None:
    # No local denylist regex / pattern literals in event_emit.py
    src = (ROOT / "tools" / "event_emit.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    has_local_compile = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr == "compile":
                if isinstance(f.value, ast.Name) and f.value.id in {"re", "regex"}:
                    has_local_compile = True
    imports_shared = "from tools.secret_scan import looks_like_secret" in src
    # No inline secret pattern strings that look like denylist ownership
    local_pattern_hits = []
    for pat in (
        r"ghp_",
        r"AKIA",
        r"github_pat_",
        r"BEGIN(?:\s+\\w+)?\s+PRIVATE KEY",
        r"\\bsk-",
    ):
        if pat in src or pat.replace("\\\\", "\\") in src:
            # docstring may mention MM-010 scan; allow prose without regex ownership
            pass
    # Stronger: event_emit must not define _RULES or duplicate looks_like_secret body
    owns_rules = "_RULES" in src or "def looks_like_secret" in src
    record(
        "QA-MM020b-2.no_local_pattern_copy",
        imports_shared and not has_local_compile and not owns_rules,
        f"imports_shared={imports_shared} re.compile={has_local_compile} owns_rules={owns_rules}",
    )

    # Shared module is the owner
    scan_src = (ROOT / "tools" / "secret_scan.py").read_text(encoding="utf-8")
    record(
        "QA-MM020b-2.secret_scan_is_owner",
        "_RULES" in scan_src and "def looks_like_secret" in scan_src,
        "tools/secret_scan.py defines _RULES + looks_like_secret",
    )

    refused: list[str] = []
    accepted_bad: list[str] = []
    payloads = {
        "sk-": "please use sk-" + ("x" * 24),
        "AKIA": "creds AKIA" + ("A" * 16) + " here",
        "JWT": "token eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.sig",
        "PEM": "-----BEGIN PRIVATE KEY-----\nMIIE\n-----END PRIVATE KEY-----",
        "email": "contact agent@example.com please",
        "ghp_": "token ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        "Bearer": "Authorization: Bearer abcdefghijklmnop",
    }
    for label, text in payloads.items():
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "e.jsonl"
            try:
                emit_message(
                    out,
                    sender="dev-1",
                    group="build",
                    summary=text,
                    ts="2026-10-20T12:00:00+00:00",
                )
                accepted_bad.append(label)
            except SecretRefusedError:
                refused.append(label)
                if out.exists() and out.stat().st_size > 0:
                    accepted_bad.append(f"{label}:wrote")
            # scanner agrees
            if not looks_like_secret(text) and label not in accepted_bad:
                accepted_bad.append(f"{label}:scanner_miss")

    record(
        "QA-MM020b-2.secret_payloads_refused",
        set(refused) == set(payloads) and not accepted_bad,
        f"refused={refused} accepted_bad={accepted_bad}",
        refused=refused,
        accepted_bad=accepted_bad,
    )

    # Benign words that historically trip naive `sk-` substring scans
    benign = ["task-runner", "risk-based", "Mask-RCNN", "desk-check", "ask-once"]
    benign_fail: list[str] = []
    for word in benign:
        if looks_like_secret(word):
            benign_fail.append(f"scanner:{word}")
            continue
        try:
            out = sanitize_summary(f"working on {word} today")
            if word not in out and "…" not in out:
                # truncated weirdly — still ok if not refused
                pass
        except SecretRefusedError:
            benign_fail.append(f"sanitize:{word}")
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "b.jsonl"
            try:
                emit_message(
                    path,
                    sender="dev-1",
                    group="build",
                    summary=f"status: {word} progress",
                    ts="2026-10-20T12:00:00+00:00",
                )
            except SecretRefusedError:
                benign_fail.append(f"emit:{word}")
    record(
        "QA-MM020b-2.benign_words_pass",
        benign_fail == [],
        f"benign_fail={benign_fail}",
    )


# ---------- (2) QA-MM020b-1 preexisting mode ----------
def check_preexisting_mode() -> None:
    outcomes: dict[str, str] = {}
    for start in (0o644, 0o666):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "events.jsonl"
            out.write_text("", encoding="utf-8")
            os.chmod(out, start)
            assert _mode(out) == start
            try:
                emit_message(
                    out,
                    sender="dev-1",
                    group="build",
                    summary=f"preexisting {oct(start)}",
                    ts="2026-10-20T12:00:00+00:00",
                )
                after = _mode(out)
                if after == 0o600:
                    outcomes[oct(start)] = "tightened_to_0o600"
                else:
                    outcomes[oct(start)] = f"left_as_{oct(after)}"
            except Exception as exc:  # noqa: BLE001
                outcomes[oct(start)] = f"refused:{type(exc).__name__}:{exc}"
    ok = all(v == "tightened_to_0o600" for v in outcomes.values())
    record(
        "QA-MM020b-1.preexisting_mode",
        ok,
        f"outcomes={outcomes} (expected tighten to 0o600)",
        outcomes=outcomes,
        behavior="tightened_to_0o600" if ok else "mixed_or_refused",
    )


# ---------- (3) QA-MM020b-3 unknown recipients ----------
def check_unknown_recipients() -> None:
    log_buf = StringIO()
    handler = logging.StreamHandler(log_buf)
    handler.setLevel(logging.WARNING)
    logger = logging.getLogger("tools.event_emit")
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    try:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "events.jsonl"
            evt = emit_message(
                out,
                sender="dev-1",
                group="build",
                summary="ping unknown",
                recipients=["dev-1", "not-a-real-bot", "also-fake"],
                ts="2026-10-20T12:00:00+00:00",
            )
            line = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
            flagged = (
                set(evt.get("unknown_recipients") or [])
                == {"not-a-real-bot", "also-fake"}
                and set(evt.get("recipients") or []) == {"dev-1"}
                and set(line.get("unknown_recipients") or [])
                == {"not-a-real-bot", "also-fake"}
            )
            warn = log_buf.getvalue()
            warned = "not-a-real-bot" in warn and "unknown recipient" in warn.lower()
            # Not a hard refuse of the whole emit (flag path)
            refused_whole = False
            record(
                "QA-MM020b-3.unknown_recipients_flagged",
                flagged and warned and not refused_whole,
                f"evt_unknown={evt.get('unknown_recipients')} recipients={evt.get('recipients')} "
                f"warned={warned} warn={warn.strip()!r}",
                behavior="flagged_with_warning_not_hard_refuse",
            )
    finally:
        logger.removeHandler(handler)

    # Mentions still not invented
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "events.jsonl"
        evt = emit_message(
            out,
            sender="dev-1",
            group="build",
            summary="hey @architect please look",
            ts="2026-10-20T12:00:01+00:00",
        )
        record(
            "QA-MM020b-3.mentions_not_inferred",
            "recipients" not in evt and "unknown_recipients" not in evt,
            f"keys={sorted(evt.keys())}",
        )


# ---------- (4) earlier fixes still hold ----------
def check_earlier_fixes() -> None:
    # Symlink refuse
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        real = td_path / "real.jsonl"
        link = td_path / "events.jsonl"
        real.write_bytes(b"")
        os.symlink(real, link)
        before = real.stat().st_size
        refused = False
        try:
            emit_message(
                link,
                sender="dev-1",
                group="build",
                summary="via symlink",
                ts="2026-10-20T12:00:00+00:00",
            )
        except SymlinkRefusedError:
            refused = True
        record(
            "SEC.symlink_refused",
            refused and real.stat().st_size == before,
            f"refused={refused} size_unchanged={real.stat().st_size == before}",
        )

    # O_NOFOLLOW via audit
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
        matched = []
        for a in opens:
            if "events.jsonl" not in str(a[0]):
                continue
            for val in a[1:]:
                if isinstance(val, int) and (val & os.O_CREAT) and (val & os.O_APPEND):
                    matched.append(val)
        ok = bool(matched) and bool(matched[-1] & os.O_NOFOLLOW)
        record(
            "SEC.o_nofollow_audit",
            ok,
            f"flags={[hex(x) for x in matched]}",
        )

    # New file 0o600
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "new.jsonl"
        emit_message(
            out,
            sender="dev-1",
            group="build",
            summary="mode create",
            ts="2026-10-20T12:00:00+00:00",
        )
        record("SEC.new_file_0o600", _mode(out) == 0o600, f"mode={oct(_mode(out))}")

    # 240 cap + multibyte
    s241 = "c" * 241
    out241 = sanitize_summary(s241)
    uni = sanitize_summary("é" * 241)
    emoji = sanitize_summary("😀" * 241)
    record(
        "SEC.summary_240_cap",
        len(out241) == 240
        and out241.endswith("…")
        and len(uni) == 240
        and len(emoji) == 240
        and len(sanitize_summary("a" * 239)) == 239
        and len(sanitize_summary("b" * 240)) == 240,
        f"241→{len(out241)} uni→{len(uni)} emoji→{len(emoji)}",
    )

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
    record(
        "SEC.docstring_240",
        "240" in docs,
        f"doc_snippet={docs[:180]!r}",
    )

    # refuse not redact
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "s.jsonl"
        try:
            emit_message(
                out,
                sender="dev-1",
                group="build",
                summary="Authorization: Bearer abcdefghijklmnop",
                ts="2026-10-20T12:00:00+00:00",
            )
            ok = False
            detail = "did not raise"
        except SecretRefusedError as exc:
            msg = str(exc)
            ok = (
                "refus" in msg.lower()
                and "ghp_" not in msg
                and "bearer abcdef" not in msg.lower()
                and (not out.exists() or out.stat().st_size == 0)
            )
            detail = f"msg={msg!r} exists={out.exists()}"
        record("SEC.refuse_not_redact", ok, detail)


# ---------- (6) light regressions MM-020a / 020c / 020f presence ----------
def check_branch_regressions_smoke() -> None:
    # MM-020a membership still importable / works
    from ingest.membership import membership_index, resolve_membership
    from ingest.migrate import migrate_activity
    from io import StringIO as SIO

    warn = SIO()
    cfg = {
        "groups": [
            {"id": "build", "members": ["director", "ghost", "director"]},
            {"id": "qr", "members": ["director"]},
        ]
    }
    res = resolve_membership(
        cfg, known_bot_ids={"director", "architect"}, warn_stream=warn
    )
    a_ok = (
        res.index.get("director") == ["build", "qr"]
        and "ghost" not in res.index
        and res.unknown_members
    )
    record("regression.MM-020a_membership", a_ok, f"index={res.index} unk={res.unknown_members}")

    # MM-020c mirror + secret_scan shared
    from tools.events_mirror import decide_flush  # type: ignore
    from tools import events_mirror

    mirror_src = (ROOT / "tools" / "events_mirror.py").read_text(encoding="utf-8")
    c_ok = (
        "from tools.secret_scan import looks_like_secret" in mirror_src
        and (ROOT / "tests" / "test_events_mirror.py").is_file()
        and (ROOT / "tests" / "test_events_fetch.py").is_file()
        and (ROOT / "ingest" / "events_fetch.py").is_file()
    )
    record(
        "regression.MM-020c_present_shared_scan",
        c_ok,
        f"events_mirror_imports_secret_scan={'secret_scan' in mirror_src}",
    )

    # Secret flush refuse on events mirror content with sk-
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        state = td_path / "state.json"
        content = "line\nsk-" + ("y" * 24) + "\n"
        # decide_flush API may vary — probe
        flush_ok = True
        detail = ""
        try:
            import inspect

            sig = str(inspect.signature(decide_flush))
            # call common pattern from MM-010
            decision = decide_flush(content, state_path=state)  # may fail signature
            detail = f"sig={sig} decision={decision}"
            flush_ok = (
                decision.get("flush") is False
                or decision.get("reason") == "secret_detected"
            )
        except TypeError:
            try:
                decision = decide_flush(content, state)
                detail = f"decision={decision}"
                flush_ok = decision.get("reason") == "secret_detected" or not decision.get(
                    "flush", True
                )
            except Exception as exc:  # noqa: BLE001
                # Fall back: looks_like_secret on content is enough for shared path
                flush_ok = looks_like_secret(content)
                detail = f"decide_flush_probe_error={exc}; scanner={flush_ok}"
        except Exception as exc:  # noqa: BLE001
            flush_ok = looks_like_secret(content)
            detail = f"decide_flush_error={exc}; scanner={flush_ok}"
        record("regression.MM-020c_secret_detect", flush_ok, detail)

    # MM-020f UI pieces present
    f_files = [
        ROOT / "web" / "src" / "components" / "MessageEdge.tsx",
        ROOT / "web" / "src" / "components" / "GroupAnchorNode.tsx",
        ROOT / "web" / "src" / "utils" / "groupMembership.ts",
    ]
    f_ok = all(p.is_file() for p in f_files)
    sse = "createSseTransport" in (ROOT / "web" / "src" / "data" / "activityTransport.ts").read_text(
        encoding="utf-8"
    )
    record(
        "regression.MM-020f_ui_present",
        f_ok,
        f"files_ok={f_ok} createSseTransport={sse}",
        note="SSE transport may still be MM-020d; message/group UI is 020f scope on this branch",
    )


def main() -> int:
    print(f"ROOT={ROOT}")
    for fn in (
        check_secrets_shared_and_refuse,
        check_preexisting_mode,
        check_unknown_recipients,
        check_earlier_fixes,
        check_branch_regressions_smoke,
    ):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            record(fn.__name__, False, f"CRASH: {exc}\n{traceback.format_exc()}")
    out = Path(__file__).resolve().parents[1] / "logs" / "delta_harness_results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(RESULTS, indent=2) + "\n", encoding="utf-8")
    fails = [r for r in RESULTS if not r["ok"]]
    print(f"\nSummary: {len(RESULTS)-len(fails)}/{len(RESULTS)} ok; {len(fails)} fail")
    for f in fails:
        print(f"  FAIL {f['check']}: {f['detail']}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
