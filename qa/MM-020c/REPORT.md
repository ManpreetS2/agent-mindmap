# QA Report — MM-020c (PR #18) delta re-verify @ `4cab4d9`

| Field | Value |
|-------|-------|
| **Verdict** | **PASS** |
| **PR** | https://github.com/ManpreetS2/agent-mindmap/pull/18 |
| **Verified head** | `4cab4d92ef448f476c559c0a737026818ca22d39` |
| **Prior FAIL head** | `9cb0c58b8cf543296684549e5a91ffc2193f2639` |
| **Base** | `feat/MM-020-unified-network` @ `82f2066` |
| **Evidence branch** | `qa/MM-020c` |
| **Fresh checkout** | `/tmp/qa-mm020c-d2/checkout` |
| **Environment** | Linux 6.12.94+, Python 3.12.3, Node v22.23.3 |
| **Date (UTC)** | 2026-10-20 |

## Verdict

**PASS.** Delta fixes close the earlier FAIL items (sk- false positives, fragmented scanners, non-atomic payload write). Suite claim holds (**146 passed, 1 skipped**); CI green on head. Residual notes below are intentional denylist breadth (ordinary emails; JWT-shaped three-segment strings), not reopen of the prior FAIL.

## Delta vs `9cb0c58` FAIL

| Prior finding | @ `9cb0c58` | @ `4cab4d9` |
|---------------|-------------|-------------|
| F1 sk- false positives (`task-runner`, …) | FAIL | **Closed** — all pass; CLI flushes |
| F2 stronger patterns not shared / ledger gap | FAIL | **Closed** — `tools/secret_scan.py` single owner |
| F3 payload non-atomic `write_text` | FAIL | **Closed** — `atomic_write` temp+fsync+`os.replace` |

## Checks

| # | Check | Result | Evidence |
|---|-------|--------|----------|
| 1 | No sk- false positives; real sk-/sk-proj-/sk-ant- refused; length min | **PASS** | `delta_sk_false_positives.json`, `delta_sk_real_keys.json` |
| 2 | Single source `tools/secret_scan.py`; no leftover local copies | **PASS** | `delta_single_source_surfaces.json`, `delta_no_leftover_local_patterns.txt` |
| 3 | Full set (AKIA/JWT/PEM/email/…) on every surface | **PASS** | `delta_full_pattern_surfaces.json` |
| 3b | New FP probe (docs email, base64) | See notes | `delta_new_false_positives.json` |
| 4 | Atomic payload write | **PASS** | `delta_atomic_payload.json` |
| 5 | 146 tests + CI | **PASS** — **146 passed, 1 skipped**; CI `39396769104` success | `pytest_counts.json`, `ci_checks.txt` |
| 6 | Regressions (retention, idempotent flush, gh read-only) | **PASS** | delta harness |
| — | Typecheck | **PASS** | `typecheck.txt` |

Harness: `qa/MM-020c/harness/test_qa_mm020c_delta.py` (11/11 OK).

### (1) sk- false positives / real keys

Benign (all surfaces false; mirror retains; CLI `--force` flushes):  
`task-runner`, `risk-based`, `ask-me`, `desk-top`, `Mask-RCNN`, `Tasks`, `sketch-pad`, `SK-PROJ-…` (uppercase).

Real keys: `sk-`+19 chars **allowed**; `sk-`+20 / +21, `sk-proj-…`, `sk-ant-…` **refused** on secret_scan, ledger, and events_mirror.

### (2) Single source

`events_mirror`, `ledger_mirror`, and `ingest.github_poller._looks_like_secret` all call `tools.secret_scan.looks_like_secret`. Ripgrep for old local denylists outside `secret_scan.py`: **none**.

### (3) Full pattern set + new FP look

AKIA, JWT, PEM, email, ghp_, Bearer refused on secret_scan / wrapper / ledger / mirror prepare.

New FP probe:

| Input | Hit? | Kind |
|-------|------|------|
| `support@example.com` in sentence | **yes** | email |
| `a@b.co` | **yes** | email |
| Generic base64 lorem / json | **no** | — |
| Three-segment `eyJ…` (JWT-shaped) | **yes** | jwt |
| Plain sentence | **no** | — |

Ordinary emails being refused matches AC “email refused on every surface”; document as residual product friction if docs ever need emails in mirrored text.

### (4) Atomic write

CLI payload path invokes `os.replace(*.tmp → payload)`. Crash before replace leaves destination unchanged (tmp may remain). After successful write, `.tmp` is gone.

### (5) Counts / CI

```
146 passed, 1 skipped
```

CI pytest **success** on `4cab4d9` — https://github.com/ManpreetS2/agent-mindmap/actions/runs/39396769104

---

## Findings

### N1 — Ordinary emails still match denylist (informational)

| | |
|---|---|
| **Component** | `tools/secret_scan.py` email rule |
| **Expected** | Full pattern set includes email refusal (AC); watch for docs false positives |
| **Actual** | `support@example.com` / `a@b.co` → `looks_like_secret=true` on all surfaces |
| **Repro** | `test_new_false_positives_email_and_base64` |
| **Evidence** | `logs/4cab4d9…/delta_new_false_positives.json` |
| **Severity** | **LOW** (by design for this AC; product friction if emails needed in summaries) |
| **Confidence** | **HIGH** |

### N2 — JWT-shaped base64 three-segment strings match (informational)

| | |
|---|---|
| **Component** | jwt rule `\beyJ…(?:\.… ){2}` |
| **Expected** | Refuse JWTs; generic base64 should pass |
| **Actual** | Generic base64 passes; crafted three-segment `eyJ` blobs match `jwt` |
| **Evidence** | same file |
| **Severity** | **LOW** |
| **Confidence** | **HIGH** |

No HIGH/MEDIUM open defects relative to this delta’s acceptance criteria.

## How to re-run

```bash
git fetch origin feat/MM-020c
git checkout 4cab4d92ef448f476c559c0a737026818ca22d39
python3 -m pytest -q   # 146 passed, 1 skipped
python3 qa/MM-020c/harness/test_qa_mm020c_delta.py  # set ROOT to checkout
```
