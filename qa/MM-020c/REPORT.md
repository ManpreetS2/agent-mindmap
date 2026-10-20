# QA Report — MM-020c (PR #18) events mirror + gh fetch

| Field | Value |
|-------|-------|
| **Verdict** | **FAIL** |
| **PR** | https://github.com/ManpreetS2/agent-mindmap/pull/18 |
| **Verified head SHA** | `9cb0c58b8cf543296684549e5a91ffc2193f2639` (unchanged from requested `9cb0c58`) |
| **Base** | `feat/MM-020-unified-network` @ `82f20667ea2a2336701ed549a7caaa77fc0c2249` |
| **Evidence branch** | `qa/MM-020c` |
| **Fresh checkout** | `/tmp/qa-mm020c/checkout` |
| **Environment** | Linux 6.12.94+, Python 3.12.3, Node v22.23.3 |
| **Date (UTC)** | 2026-10-20 |
| **Method** | Verify-only; behavioral harness; no product changes; no PR comments |

## Verdict summary

Core mirror/fetch mechanics largely work: **140 passed, 1 skipped**, CI green on head, 7-day retention/boundary/timezone OK, flush idempotent for identical sha256, QA-MM020b-2 secret types refused in mirrored fields, `gh` argv is read-only, no token echo in mirror CLI output.

**FAIL** on Security false-positive requirement: the mirror `sk-` regex matches benign substrings (`task-runner` → `sk-runner`, etc.), so those events are dropped and CLI flush returns `secret_detected`. Stronger patterns are **not** in the shared `_looks_like_secret` scanner (ledger still misses `sk-`/`AKIA`/…); they exist as **local** extensions in `events_mirror` and (separately) on current PR #17 emitter tip.

## Checks

| # | Check | Result | Evidence |
|---|-------|--------|----------|
| 1 | 7-day overwrite / exact boundary / TZ | **PASS** | `behavioral_console` retention test |
| 2 | Flush idempotent; crash partial → no dup ids; state atomic | **PASS** (payload CLI uses non-atomic `write_text`; state uses tmp+replace) | harness + `payload_write_atomicity.txt` |
| 3 | Secret refusal (QA-MM020b-2 + fields) | **PASS** for real secrets | `secret_refusal_results.json`, `secret_every_field.txt` |
| 3b | False-positive benign words must NOT refuse | **FAIL** | `false_positive_sk_results.json`, `false_positive_cli_flush.txt` |
| 4 | gh read-only (mock argv) | **PASS** | `gh_argv_calls.json` |
| 5 | No token exposure | **PASS** (mirror CLI / argv) | `token_exposure.json` |
| 6 | 140 tests claim + CI | **PASS** — **140 passed, 1 skipped**; CI success `39395637232` | `pytest_counts.json`, `ci_checks.txt` |
| 7 | No regressions MM-020a / MM-020b | **PASS** 020a tests; 020b emitter **absent** on this branch (expected); scanner comparison vs PR17 tip documented | `pytest_events_mm020a.txt`, scanner scope JSON |
| — | Typecheck / build env | **PASS** after `web/npm ci` | `typecheck.txt` |
| — | Stronger patterns scope | **Mirror + PR17-local only; not shared/ledger** | `scanner_scope_*.json` |

Harness: `qa/MM-020c/harness/test_qa_mm020c_behavioral.py`

---

## Security additions — false positives (`sk-` regex)

| Benign input | Regex match | `looks_like_mirror_secret` | shared `_looks_like_secret` | Prepare / CLI |
|--------------|-------------|----------------------------|-----------------------------|---------------|
| `task-runner` | `sk-runner` | true | false | dropped; CLI `secret_detected` |
| `risk-based` | `sk-based` | true | false | same |
| `ask-me` | `sk-me` | true | false | same |
| `desk-top` | `sk-top` | true | false | same |
| `Mask-RCNN` | `sk-RCNN` | true | false | same |

Pattern (behavioral extract): `sk-[A-Za-z0-9_\-]+` with `IGNORECASE` — matches any `…sk-…` substring inside longer tokens.

CLI evidence (`false_positive_cli_flush.txt`): all five lines dropped with `QA-MM020b-2` warnings; stdout `{"flush": false, "reason": "secret_detected", ...}`; no payload written.

---

## Stronger patterns — where applied (behavioral)

| Surface | `sk-` / `AKIA` / JWT / PEM / email | `ghp_` |
|---------|-------------------------------------|--------|
| Shared `ingest.github_poller._looks_like_secret` | **No** | **Yes** |
| MM-020c `tools.events_mirror.looks_like_mirror_secret` | **Yes** (local) | **Yes** (via shared) |
| MM-010 `tools.ledger_mirror` flush scan | **No** | **Yes** |
| PR #17 emitter tip `1bdb7af` `sanitize_summary` | **Yes** (local `_free_text_looks_like_secret`, not shared) | **Yes** |

**Conclusion:** Stronger patterns are **not** in the shared scanner. They are duplicated locally in the events mirror (this PR) and in the current PR #17 emitter. Ledger flush does **not** get them. PR17 tip also false-positive-refuses `task-runner`.

---

## Findings

### F1 — `sk-` false positives refuse mirror flush (Security)

| | |
|---|---|
| **Component** | `tools/events_mirror.looks_like_mirror_secret` / `_MIRROR_SECRET_EXTRA_RE` |
| **Expected** | Benign words `task-runner`, `risk-based`, `ask-me`, `desk-top`, `Mask-RCNN` must **not** refuse a flush |
| **Actual** | All five match `sk-…` substrings; events dropped (`secrets_seen`); CLI `--force` still returns `reason=secret_detected`, no payload |
| **Repro** | `python3 qa/MM-020c/harness/test_qa_mm020c_behavioral.py` → `test_false_positive_benign_words_must_not_refuse`; see `false_positive_cli_flush.txt` |
| **Evidence** | `logs/9cb0c58…/false_positive_sk_results.json`, `sk_regex_match_detail.txt`, `false_positive_cli_flush.txt` |
| **Severity** | **HIGH** |
| **Confidence** | **HIGH** |

### F2 — Stronger secret patterns not in shared scanner / ledger

| | |
|---|---|
| **Component** | `ingest.github_poller._looks_like_secret` vs mirror/emitter locals |
| **Expected** | Clarify whether stronger patterns are shared with PR17 emitter + ledger flush |
| **Actual** | Shared scanner unchanged (ghp_/Bearer only). Ledger accepts `sk-`/`AKIA`/JWT/PEM/email content. Mirror and PR17 emitter each implement local extensions |
| **Repro** | `test_shared_scanner_lacks_stronger_patterns`, `test_pr17_emitter_has_local_stronger_not_via_shared` |
| **Evidence** | `scanner_scope_shared_ledger_mirror.json`, `scanner_scope_pr17_emitter.json` |
| **Severity** | **MEDIUM** (inconsistent protection; ledger gap) |
| **Confidence** | **HIGH** |

### F3 — CLI payload write is not tmp+replace (atomicity gap)

| | |
|---|---|
| **Component** | `tools/events_mirror.main` payload output |
| **Expected** | Writes atomic |
| **Actual** | `save_state` uses tmp+`replace`; payload uses `Path.write_text` directly. Prepare/dedupe path still prevents duplicate ids after partial **input** recovery |
| **Evidence** | `payload_write_atomicity.txt` |
| **Severity** | **LOW** |
| **Confidence** | **HIGH** |

### Informational — passing areas

| Topic | Notes |
|-------|-------|
| Retention | Exact 7-day boundary retained; 1s outside dropped; `Z`, offsets, non-UTC OK |
| Idempotent flush | Same sha256 → `unchanged` even with `--force` |
| Secret TP | ghp_/pat/sk-/AKIA/Bearer/JWT/PEM/email refused; no secret material in warnings; summary/group/sender/recipients/related_id covered via whole-line scan |
| gh read-only | Mocked runner only sees allowlisted `contents/events.jsonl?ref=data/events` |
| Token | `GH_TOKEN` in env not present in mirror stdout/stderr/payload/argv |
| Counts | **140 passed, 1 skipped**; CI success on `9cb0c58` |
| MM-020a | `tests/test_mm020a_membership.py` green |
| MM-020b | `event_emit.py` not on branch; no direct regression surface; scanner compared to PR17 tip `1bdb7af` |

## How to re-run

```bash
git fetch origin feat/MM-020c
git checkout 9cb0c58b8cf543296684549e5a91ffc2193f2639
python3 -m pytest -q          # 140 passed, 1 skipped
# point ROOT in harness at this checkout:
python3 qa/MM-020c/harness/test_qa_mm020c_behavioral.py
```
