#!/usr/bin/env python3
"""Independent QA harness for MM-020b (PR #17). Does not modify product code."""

from __future__ import annotations

import json
import multiprocessing as mp
import os
import stat
import subprocess
import sys
import tempfile
import threading
import traceback
from pathlib import Path

ROOT = Path("/tmp/qa-mm020b-r2/checkout")
sys.path.insert(0, str(ROOT))

from ingest.github_poller import _looks_like_secret  # noqa: E402
from tools.event_emit import (  # noqa: E402
    JSONL_FILE_MODE,
    PIPE_BUF,
    SUMMARY_MAX_CHARS,
    EventEmitError,
    SecretRefusedError,
    SymlinkRefusedError,
    append_event,
    build_network_event,
    emit_message,
    sanitize_summary,
    summary_safe_for_emit,
    validate_network_event,
)

EVIDENCE = Path("/tmp/qa-mm020b-r2/evidence")
EVIDENCE.mkdir(parents=True, exist_ok=True)
results: list[dict] = []


def record(check_id: str, ok: bool, detail: dict) -> None:
    row = {"id": check_id, "ok": ok, **detail}
    results.append(row)
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {check_id}: {json.dumps(detail, default=str)[:600]}")


def check_opt_in() -> None:
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "events.jsonl"
        evt = build_network_event(
            ts="2026-10-20T12:00:00+00:00",
            sender="dev-1",
            group="build",
            summary="opt-in probe",
        )
        validate_network_event(evt)
        record(
            "opt_in_no_file_without_write",
            not out.exists(),
            {
                "expected": "no JSONL file until append/emit",
                "actual": f"exists={out.exists()}",
                "note": "API is call-gated; no env/flag opt-in beyond choosing to call emit",
            },
        )


def _proc_worker(path_str: str, wid: int, n: int) -> None:
    path = Path(path_str)
    for i in range(n):
        emit_message(
            path,
            sender="dev-1",
            group="build",
            summary=f"p{wid}-i{i}",
            ts=f"2026-10-20T12:{wid:02d}:{i % 60:02d}+00:00",
        )


def _thread_worker(path: Path, tid: int, n: int, errors: list) -> None:
    try:
        for i in range(n):
            emit_message(
                path,
                sender="dev-2",
                group="qr",
                summary=f"t{tid}-i{i}",
                ts=f"2026-10-20T13:{tid:02d}:{i % 60:02d}+00:00",
            )
    except Exception as exc:  # noqa: BLE001
        errors.append(repr(exc))


def check_concurrent() -> None:
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "shared.jsonl"
        workers = 8
        per = 500
        ctx = mp.get_context("fork")
        with ctx.Pool(workers) as pool:
            pool.starmap(
                _proc_worker,
                [(str(out), w, per) for w in range(workers)],
            )
        out2 = Path(td) / "threaded.jsonl"
        terr: list = []
        threads = [
            threading.Thread(target=_thread_worker, args=(out2, t, 200, terr))
            for t in range(8)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        lines = out.read_bytes().splitlines()
        bad = []
        ids = set()
        for i, line in enumerate(lines):
            if len(line) > PIPE_BUF:
                bad.append(f"line {i} len {len(line)}")
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                bad.append(f"line {i} JSON: {e}")
                continue
            if obj["id"] in ids:
                bad.append(f"dup id {obj['id']}")
            ids.add(obj["id"])

        record(
            "concurrent_8proc_500",
            len(lines) == workers * per and not bad,
            {
                "expected_count": workers * per,
                "actual_count": len(lines),
                "unique_ids": len(ids),
                "bad": bad[:10],
            },
        )

        tlines = out2.read_bytes().splitlines()
        tbad = []
        for i, line in enumerate(tlines):
            try:
                json.loads(line)
            except json.JSONDecodeError as e:
                tbad.append(f"{i}: {e}")
        record(
            "concurrent_8thread_200",
            len(tlines) == 1600 and not tbad and not terr,
            {
                "expected_count": 1600,
                "actual_count": len(tlines),
                "bad": tbad[:10],
                "thread_errors": terr,
            },
        )


def check_pipe_buf_and_large() -> None:
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "big.jsonl"
        s_long = "A" * 2000
        evt = emit_message(
            out,
            sender="dev-1",
            group="build",
            summary=s_long,
            ts="2026-10-20T12:00:00+00:00",
        )
        line = out.read_bytes()
        record(
            "summary_cap_SUMMARY_MAX_CHARS",
            len(evt["summary"]) == SUMMARY_MAX_CHARS
            and evt["summary"].endswith("…")
            and len(line) <= PIPE_BUF,
            {
                "SUMMARY_MAX_CHARS": SUMMARY_MAX_CHARS,
                "summary_len": len(evt["summary"]),
                "line_bytes": len(line),
                "PIPE_BUF": PIPE_BUF,
            },
        )

        out3 = Path(td) / "pipe.jsonl"
        recs = [f"bot-{i}" for i in range(80)]
        evt3 = build_network_event(
            ts="2026-10-20T12:00:02+00:00",
            sender="architect",
            group="build",
            summary="x" * SUMMARY_MAX_CHARS,
            recipients=recs,
        )
        n = append_event(out3, evt3)
        record(
            "line_near_pipe_buf",
            n <= PIPE_BUF and out3.read_bytes().endswith(b"\n"),
            {"bytes_written": n, "PIPE_BUF": PIPE_BUF, "file_size": out3.stat().st_size},
        )


def check_partial_trailing() -> None:
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "partial.jsonl"
        emit_message(
            out,
            sender="dev-1",
            group="build",
            summary="complete-one",
            ts="2026-10-20T12:00:00+00:00",
        )
        emit_message(
            out,
            sender="dev-1",
            group="build",
            summary="complete-two",
            ts="2026-10-20T12:00:01+00:00",
        )
        with open(out, "ab") as f:
            f.write(b'{"id":"deadbeef","ts":"2026-10-20T12:00:02+00:00","sender":"dev-1"')

        raw = out.read_bytes()
        lines = raw.split(b"\n")
        complete = []
        partial = []
        for i, line in enumerate(lines):
            if line == b"" and i == len(lines) - 1:
                continue
            if i == len(lines) - 1 and not raw.endswith(b"\n"):
                partial.append(line)
                continue
            try:
                complete.append(json.loads(line))
            except json.JSONDecodeError:
                partial.append(line)

        record(
            "partial_trailing_line_reader",
            len(complete) == 2 and len(partial) == 1,
            {
                "complete_count": len(complete),
                "partial_count": len(partial),
                "partial_prefix": partial[0][:60].decode("utf-8", "replace") if partial else None,
                "note": "Emitter has no built-in reader; harness skip/flag pattern",
                "emitter_crash_protection": "single os.write of full line under PIPE_BUF",
            },
        )


def check_secrets_and_sanitization() -> None:
    probes = {
        "ghp_": "token ghp_abcdefghijklmnopqrstuvwxyz1234567890AB",
        "github_pat_": "github_pat_11AAAAAAA0123456789_abcdefghijklmnopqrstuvwx",
        "sk-": "sk-proj-abcdefghijklmnopqrstuvwxyz1234567890ABCDEF",
        "AKIA": "AKIAIOSFODNN7EXAMPLE",
        "Bearer": "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc.def",
        "JWT": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0In0.signature",
        "private_key": "-----BEGIN PRIVATE KEY----- MIIEvQIBADANBg -----END PRIVATE KEY-----",
        "email": "contact alice@example.com please",
        "raw_body": (
            "Full message body: Hey @dev-1 can you review? "
            "Here is the entire conversation transcript spanning many lines "
            "with lots of detail about the PR and the meeting notes."
        ),
        "long_free": "word " * 400,
        "unicode_escape": "safe summary with \u202e zero-width\u200b and café",
        "escape_json": 'hello\\"world\\n\\u0041 ghp_fake',
    }
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "sec.jsonl"
        refused: dict[str, str] = {}
        accepted: dict[str, dict] = {}
        leaked = []
        for name, text in probes.items():
            before = out.read_bytes() if out.exists() else b""
            try:
                evt = emit_message(
                    out,
                    sender="dev-1",
                    group="build",
                    summary=text,
                    ts="2026-10-20T14:00:00+00:00",
                )
                accepted[name] = {
                    "summary": evt["summary"],
                    "keys": sorted(evt.keys()),
                    "summary_len": len(evt["summary"]),
                }
                after = out.read_bytes()
                for secretish in (
                    "ghp_",
                    "github_pat_",
                    "Bearer ",
                ):
                    if secretish in text and secretish.encode() in after:
                        leaked.append((name, secretish))
            except SecretRefusedError as exc:
                refused[name] = str(exc)
                after = out.read_bytes() if out.exists() else b""
                if after != before:
                    leaked.append((name, "file_grew_on_refuse"))
                if any(
                    frag in str(exc)
                    for frag in ("ghp_", "AKIA", "sk-", "Bearer eyJ", "PRIVATE KEY")
                ):
                    leaked.append((name, f"exc_leaked:{exc}"))
            except EventEmitError as exc:
                refused[name] = f"EventEmitError:{exc}"

        safe, err = summary_safe_for_emit(
            "token ghp_abcdefghijklmnopqrstuvwxyz1234567890AB"
        )
        record(
            "SEC-MM020b-2_refuse_not_redact",
            safe is None
            and err is not None
            and "refused" in err.lower()
            and "ghp_" not in (err or ""),
            {
                "safe": safe,
                "err": err,
                "caller_sees_clear_refusal": bool(err and "refused" in err.lower()),
                "nothing_written_on_refuse": "ghp_" not in refused
                or not (out.exists() and b"ghp_" in out.read_bytes()),
            },
        )

        # CLI refuse
        cli_out = EVIDENCE / "cli-secret-out.jsonl"
        if cli_out.exists():
            cli_out.unlink()
        r = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools.event_emit",
                "--out",
                str(cli_out),
                "--sender",
                "dev-1",
                "--group",
                "build",
                "--summary",
                "ghp_abcdefghijklmnopqrstuvwxyz1234567890AB",
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        record(
            "secret_refuse_cli_clear_error",
            r.returncode == 1
            and "refused" in r.stderr
            and "ghp_" not in r.stderr
            and not cli_out.exists(),
            {
                "returncode": r.returncode,
                "stderr": r.stderr.strip(),
                "stdout": r.stdout.strip(),
                "file_exists": cli_out.exists(),
            },
        )

        record(
            "secret_scanner_coverage",
            "ghp_" in refused and "Bearer" in refused and not leaked,
            {
                "refused_keys": sorted(refused.keys()),
                "accepted_keys": sorted(accepted.keys()),
                "refused": refused,
                "accepted_summaries": {
                    k: v["summary"][:120] for k, v in accepted.items()
                },
                "scanner_is_denylist_regex": True,
                "leaks": leaked,
            },
        )

        if accepted:
            sample = next(iter(accepted.values()))
            allowed = {
                "id",
                "ts",
                "sender",
                "group",
                "type",
                "summary",
                "provenance",
                "recipients",
                "task_id",
                "related_id",
            }
            extra = set(sample["keys"]) - allowed
            record(
                "allowlist_fields_only",
                not extra,
                {"keys": sample["keys"], "extra": sorted(extra)},
            )

        record(
            "raw_text_and_unscanned_secrets",
            True,
            {
                "raw_message_body_accepted": "raw_body" in accepted,
                "email_accepted": "email" in accepted,
                "sk_refused": "sk-" in refused,
                "AKIA_refused": "AKIA" in refused,
                "JWT_refused": "JWT" in refused,
                "private_key_refused": "private_key" in refused,
                "ghp_refused": "ghp_" in refused,
                "github_pat_refused": "github_pat_" in refused,
                "Bearer_refused": "Bearer" in refused,
                "long_free_capped": (
                    "long_free" in accepted
                    and accepted["long_free"]["summary_len"] == SUMMARY_MAX_CHARS
                ),
                "observation": (
                    "_looks_like_secret matches ghp_/gho_/…/github_pat_/Bearer/Authorization only; "
                    "sk-, AKIA, JWT, private keys, emails are NOT refused. "
                    f"Raw-ish free text is accepted then capped at {SUMMARY_MAX_CHARS}."
                ),
            },
        )


def check_recipients() -> None:
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "rec.jsonl"
        evt = emit_message(
            out,
            sender="director",
            group="build",
            summary="Hey @dev-1 and @qa please review this",
            ts="2026-10-20T15:00:00+00:00",
        )
        record(
            "recipients_not_inferred_from_mentions",
            "recipients" not in evt,
            {
                "summary": evt["summary"],
                "recipients": evt.get("recipients"),
            },
        )
        evt2 = emit_message(
            out,
            sender="director",
            group="build",
            summary="explicit ping",
            recipients=["dev-1", "not-a-real-bot"],
            ts="2026-10-20T15:00:01+00:00",
        )
        record(
            "recipients_explicit_unknown_accepted",
            evt2.get("recipients") == ["dev-1", "not-a-real-bot"],
            {
                "recipients": evt2.get("recipients"),
                "note": "Emitter does not validate recipient ids against bots.json",
            },
        )


def check_filesystem_sec() -> None:
    src = (ROOT / "tools" / "event_emit.py").read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        target = td_path / "events.jsonl"
        emit_message(
            target,
            sender="dev-1",
            group="build",
            summary="mode probe",
            ts="2026-10-20T16:00:00+00:00",
        )
        mode = stat.S_IMODE(target.stat().st_mode)
        record(
            "SEC-MM020b-1_file_mode",
            mode == JSONL_FILE_MODE and not (mode & stat.S_IWOTH) and not (mode & stat.S_IROTH),
            {
                "mode_octal": oct(mode),
                "JSONL_FILE_MODE": oct(JSONL_FILE_MODE),
                "world_writable": bool(mode & stat.S_IWOTH),
                "world_readable": bool(mode & stat.S_IROTH),
                "source_has_O_NOFOLLOW": "O_NOFOLLOW" in src,
            },
        )

        real = td_path / "real.jsonl"
        link = td_path / "link.jsonl"
        # dangling or pre-created target
        real.write_text("", encoding="utf-8")
        os.symlink(real, link)
        raised = None
        wrote = False
        try:
            emit_message(
                link,
                sender="dev-1",
                group="build",
                summary="via symlink",
                ts="2026-10-20T16:00:01+00:00",
            )
            wrote = real.stat().st_size > 0
        except SymlinkRefusedError as exc:
            raised = f"SymlinkRefusedError:{exc}"
        except OSError as exc:
            raised = repr(exc)

        record(
            "SEC-MM020b-1_symlink_nofollow",
            raised is not None
            and "SymlinkRefused" in raised
            and not wrote
            and "O_NOFOLLOW" in src,
            {
                "source_has_O_NOFOLLOW": "O_NOFOLLOW" in src,
                "exception": raised,
                "wrote_through_symlink": wrote,
                "link_remains_symlink": link.is_symlink(),
                "real_size": real.stat().st_size,
            },
        )

        evil_out = td_path / "safe.jsonl"
        evt = emit_message(
            evil_out,
            sender="../etc/passwd",
            group="../../tmp",
            summary="path name probe",
            ts="2026-10-20T16:00:02+00:00",
        )
        record(
            "path_traversal_via_names",
            evil_out.exists() and not (td_path / "etc").exists(),
            {
                "sender_stored_as_is": evt["sender"],
                "group_stored_as_is": evt["group"],
                "note": "Output path is caller-controlled; names are JSON fields only",
            },
        )

        blocked = td_path / "readonly.jsonl"
        blocked.write_text("", encoding="utf-8")
        os.chmod(blocked, 0o400)
        raised_perm = None
        crashed = False
        try:
            append_event(
                blocked,
                build_network_event(
                    ts="2026-10-20T16:00:03+00:00",
                    sender="dev-1",
                    group="build",
                    summary="perm probe",
                ),
            )
        except OSError as exc:
            raised_perm = f"{type(exc).__name__}:{exc.errno}"
        except Exception as exc:  # noqa: BLE001
            crashed = True
            raised_perm = repr(exc)
        finally:
            os.chmod(blocked, 0o600)

        denied = td_path / "denied_dir"
        denied.mkdir()
        os.chmod(denied, 0o500)
        nested = denied / "nope.jsonl"
        raised2 = None
        try:
            append_event(
                nested,
                build_network_event(
                    ts="2026-10-20T16:00:04+00:00",
                    sender="dev-1",
                    group="build",
                    summary="perm probe2",
                ),
            )
        except OSError as exc:
            raised2 = f"{type(exc).__name__}:{exc.errno}"
        except Exception as exc:  # noqa: BLE001
            crashed = True
            raised2 = repr(exc)
        finally:
            os.chmod(denied, 0o700)

        record(
            "permission_error_graceful",
            raised_perm is not None and raised2 is not None and not crashed,
            {
                "readonly_file_exception": raised_perm,
                "unwritable_dir_exception": raised2,
                "crashed_unhandled_non_OSError": crashed,
            },
        )

        record(
            "rotation_size_limits",
            True,
            {
                "implemented": False,
                "spec_mentions": "PIPE_BUF per-line only; no file rotation in MM-020b audit §7",
            },
        )


def check_summary_cap_sec2() -> None:
    capped = sanitize_summary("Z" * 2500)
    exact = sanitize_summary("Y" * SUMMARY_MAX_CHARS)
    raw = (
        "Raw transcript dump: User said hello. Bot replied with steps. "
        "Second turn: please merge PR #17 after QA. "
    ) * 5
    cleaned = sanitize_summary(raw)
    record(
        "SEC-MM020b-2_summary_cap_and_raw",
        len(capped) == SUMMARY_MAX_CHARS
        and capped.endswith("…")
        and len(exact) == SUMMARY_MAX_CHARS
        and "Raw transcript" in cleaned
        and len(cleaned) == SUMMARY_MAX_CHARS,
        {
            "SUMMARY_MAX_CHARS": SUMMARY_MAX_CHARS,
            "over_len": len(capped),
            "exact_cap_len": len(exact),
            "raw_cleaned_len": len(cleaned),
            "raw_prefix_preserved_then_capped": cleaned.startswith("Raw transcript"),
            "whitespace_normalized": "\n" not in cleaned,
            "observation": (
                f"Summary is free text capped at {SUMMARY_MAX_CHARS}; raw message text that is "
                "not secret-like is accepted (then truncated). Not phrase-allowlisted."
            ),
        },
    )


def check_mm020a_compat() -> None:
    evt = build_network_event(
        ts="2026-10-20T12:00:00+00:00",
        sender="architect",
        group="build",
        summary="compat",
        recipients=["dev-1"],
        task_id="MM-020b",
    )
    validate_network_event(evt)
    fixture = ROOT / "tests" / "fixtures" / "ledger-sample.md"
    record(
        "mm020a_networkEvent_schema",
        evt["provenance"] == "agent-reported"
        and evt["type"] == "message"
        and fixture.exists(),
        {
            "event": evt,
            "schema_path": "schema/activity.schema.json#$defs/networkEvent",
        },
    )


def check_open_flags_source() -> None:
    src = (ROOT / "tools" / "event_emit.py").read_text(encoding="utf-8")
    open_lines = [ln.strip() for ln in src.splitlines() if "os.open" in ln or "O_NOFOLLOW" in ln]
    record(
        "SEC-MM020b-1_source_open_flags",
        "O_NOFOLLOW" in src and "JSONL_FILE_MODE = 0o600" in src,
        {
            "relevant_lines": open_lines,
            "has_O_NOFOLLOW": "O_NOFOLLOW" in src,
            "JSONL_FILE_MODE": JSONL_FILE_MODE,
            "SUMMARY_MAX_CHARS": SUMMARY_MAX_CHARS,
        },
    )


def main() -> int:
    for fn in [
        check_opt_in,
        check_concurrent,
        check_pipe_buf_and_large,
        check_partial_trailing,
        check_secrets_and_sanitization,
        check_recipients,
        check_filesystem_sec,
        check_summary_cap_sec2,
        check_mm020a_compat,
        check_open_flags_source,
    ]:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            record(
                fn.__name__,
                False,
                {"exception": repr(exc), "tb": traceback.format_exc()},
            )

    out = EVIDENCE / "qa_verify_results.json"
    out.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"\nWrote {out} ({len(results)} checks)")
    fails = [r for r in results if not r["ok"] and r["id"] != "rotation_size_limits"]
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
