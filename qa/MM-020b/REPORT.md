# QA Report — MM-020b (PR #17) re-verify @ `692216d`

| Field | Value |
|-------|-------|
| **Verdict** | **FAIL** |
| **PR** | https://github.com/ManpreetS2/agent-mindmap/pull/17 |
| **Verified head SHA** | `692216de5f944a870887bc7bf37779f618797cc2` (`692216d`) |
| **Base** | `feat/MM-020-unified-network` |
| **Evidence branch** | `qa/MM-020b` |
| **Fresh checkout** | `/tmp/qa-mm020b-r2/checkout` @ exact SHA |
| **Environment** | Linux 6.12.94+, Python 3.12.3, Node v22.23.3 |
| **Date (UTC)** | 2026-10-20 |
| **Method** | Behavioral tests only for SEC closure (no product source inspection for flags/constants) |

## Verdict

**FAIL.** Suite/CI claims hold, and most of SEC-MM020b-1/2 is closed by behavioral tests, but **pre-existing JSONL file modes are not handled** (remain `0o644` / `0o666` after append). Prior sanitization / unknown-recipient gaps also remain.

### SEC closure status (this re-verify)

| Note | Claim to close | Result |
|------|----------------|--------|
| SEC-MM020b-1 | Opened with `O_NOFOLLOW` | **CLOSED** — `sys.audit("open")` flags `0xa0441` include `os.O_NOFOLLOW`; symlink path raises `SymlinkRefusedError`, target untouched |
| SEC-MM020b-1 | Symlinked target refused | **CLOSED** |
| SEC-MM020b-1 | New file mode `0o600` | **CLOSED** — `stat` after create |
| SEC-MM020b-1 | Pre-existing file mode handled | **OPEN** — stays `0o644` / `0o666` after emit |
| SEC-MM020b-2 | Cap 240 (239/240/241) | **CLOSED** |
| SEC-MM020b-2 | Multibyte / emoji cap | **CLOSED** |
| SEC-MM020b-2 | Docstring states 240 contract | **CLOSED** — module `__doc__` contains `SUMMARY_MAX_CHARS (240)` |

## Suite + CI

| Check | Result | Evidence |
|-------|--------|----------|
| Exact pytest counts | **123 passed, 1 skipped** (claim holds) | `logs/692216d…-r2/pytest.txt`, `pytest_counts.json` |
| Typecheck | PASS | `typecheck.txt` |
| Web build | PASS | `build.txt` |
| CI on head | pytest **success** run `39394298787` @ `692216d` | `ci_checks.txt`, `ci_run_head.json` |

## Behavioral SEC tests (QA-authored)

Harness: `qa/MM-020b/harness/test_sec_mm020b_behavioral.py`  
Log: `logs/692216d…-r2/sec_behavioral_run.txt` / `sec_behavioral_results.json`

| Test | Result |
|------|--------|
| `test_symlinked_target_is_refused` | PASS |
| `test_o_nofollow_via_sys_audit_open_flags` | PASS (`O_NOFOLLOW` bit set) |
| `test_new_file_created_mode_0o600` | PASS |
| `test_preexisting_file_mode_handled` (0o644→expect 0o600) | **FAIL** (after=`0o644`) |
| `test_preexisting_world_writable_tightened_or_refused` (0o666) | **FAIL** (after=`0o666`) |
| `test_summary_len_239_240_241` | PASS |
| `test_multibyte_and_emoji_cap` | PASS |
| `test_docstring_states_240_contract` | PASS |
| `test_refuse_not_redact_nothing_written` | PASS |

`strace` was unavailable in the environment; `O_NOFOLLOW` was confirmed via Python `sys.addaudithook` on the `open` audit event instead (`o_nofollow_audit_hook.txt`).

## Regression harness (prior AC matrix)

`harness/qa_verify_mm020b.py` → `harness_stdout.txt` / `harness_results.json`

No regression on: opt-in call-gating, 8×500 process + 8×200 thread concurrent appends, PIPE_BUF, partial trailing line skip pattern, ghp_/Bearer refuse-not-redact, mention non-inference, MM-020a `networkEvent` shape.

Still failing product expectations from prior report: secret denylist gaps (`sk-`, `AKIA`, JWT, private key, email accepted); unknown recipients accepted without flag.

---

## Findings

### F1 — Pre-existing file mode not handled (SEC-MM020b-1 incomplete)

| | |
|---|---|
| **Component** | JSONL append path (`emit_message` / `append_event`) |
| **Expected** | Pre-existing file mode is also handled (tightened to `0o600` or refused if unsafe) |
| **Actual** | New files are `0o600`. Pre-existing `0o644` stays `0o644`; pre-existing `0o666` stays `0o666` after successful append |
| **Repro** | See `test_preexisting_file_mode_handled` in `harness/test_sec_mm020b_behavioral.py` |
| **Evidence** | `sec_behavioral_run.txt`, `preexisting_mode_detail.txt` |
| **Environment** | Python 3.12.3, umask-sensitive create only |
| **Severity** | **MEDIUM** |
| **Confidence** | **HIGH** |

### F2 — Summary secret denylist gaps (regression carry-forward)

| | |
|---|---|
| **Component** | `sanitize_summary` / shared `_looks_like_secret` |
| **Expected** | `sk-`, `AKIA`, JWT, private key blocks, emails must not appear in JSONL |
| **Actual** | Still accepted into `summary` (capped at 240). `ghp_` / `github_pat_` / Bearer refused with clear error and no write |
| **Repro** | `qa_verify_mm020b.py` → `raw_text_and_unscanned_secrets` |
| **Evidence** | `harness_results.json` |
| **Severity** | **HIGH** |
| **Confidence** | **HIGH** |

### F3 — Unknown recipients not rejected or flagged (carry-forward)

| | |
|---|---|
| **Component** | `emit_message(..., recipients=...)` |
| **Expected** | Unknown recipients rejected or flagged |
| **Actual** | `["dev-1","not-a-real-bot"]` written as-is; `@mentions` still not inferred |
| **Evidence** | `recipients_explicit_unknown_accepted` |
| **Severity** | **MEDIUM** |
| **Confidence** | **HIGH** |

### Informational — SEC items closed by this re-verify

| ID | Observation | Evidence |
|----|-------------|----------|
| SEC-MM020b-1 symlink / O_NOFOLLOW | Closed | audit hook + symlink tests |
| SEC-MM020b-1 new file `0o600` | Closed | `test_new_file_created_mode_0o600` |
| SEC-MM020b-2 240 cap + docstring | Closed | 239/240/241 + emoji tests; module `__doc__` |
| Refuse-not-redact | Still correct | `SecretRefusedError` / CLI stderr; no file |

## How to re-run

```bash
git fetch origin feat/MM-020b
git checkout 692216de5f944a870887bc7bf37779f618797cc2
python3 -m pytest -q          # 123 passed, 1 skipped
python3 qa/MM-020b/harness/test_sec_mm020b_behavioral.py
# point ROOT inside that harness at the fresh checkout if needed
```
