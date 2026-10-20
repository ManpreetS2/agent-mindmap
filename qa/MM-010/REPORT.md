# QA Report — MM-010 (PR #11) ledger mirror

**Verdict: PASS**  
**Target head:** `50f210c965a052ed4d41b2a83f72f75c672d2d30`  
**PR head at verify time:** `50f210c965a052ed4d41b2a83f72f75c672d2d30` (moved from `3be3f32`; tested new head)  
**QA branch:** `qa/MM-010`  
**Environment:** Linux, Python 3.12.3, Node v22.23.3, gh 2.102.0  
**Fresh checkout:** `/tmp/qa-mm010/repo` @ `50f210c`  
**Architecture spec:** `build/mindmap/architecture.md` not in this repo (GitHub 404). Acceptance criteria taken from PR #11 body, the MM-010 report comment, and in-repo README “Ledger mirror contract (MM-010)” / attribution rules.

---

## Baseline (3be3f32 only — not verdict target)

| Check | Result |
|-------|--------|
| pytest | **80 passed** |
| vitest | 40 passed |
| tsc + build | clean |
| SEC-MM010-1 | **FAIL** — `tools/ledger_mirror.py` did not call `_looks_like_secret`; secretish `ghp_…` content still wrote `--payload` |

Evidence: `qa/MM-010/logs/3be3f32-baseline/`

---

## Checks @ 50f210c

| Check | Result | Evidence |
|-------|--------|----------|
| `python3 -m pytest -q` | **83 passed** (matches claim) | `logs/50f210c/pytest.txt` |
| `cd web && npm test` | **40 passed** | `logs/50f210c/vitest.txt` |
| `npx tsc --noEmit` (root + web) | clean | `logs/50f210c/typecheck-*.txt` |
| `cd web && npm run build` | success | `logs/50f210c/build.txt` |
| All activity fixtures vs schema | PASS (7 files) | `logs/50f210c/fixture_validation.txt` |
| Missing/required ledger path (no fixture default) | PASS (exit 2) | `logs/50f210c/missing_ledger_path.txt` |
| Malformed ledger (local) | PASS | `logs/50f210c/malformed_ledger_path.txt` |
| Malformed ledger (gh base64) | PASS → `meta.ledger=error` | `logs/50f210c/malformed_ledger_gh.txt` |
| Idempotent mirror re-run | PASS (`unchanged` even with `--force`) | `logs/50f210c/idempotent_mirror.txt` |
| Idempotent ingest re-run | PASS | `logs/50f210c/idempotent_ingest.txt` |
| PR joins keyed on `(repo, number)` | PASS (two distinct #5 merges) | `logs/50f210c/pr_join_repo_number.txt` |
| Merger from ledger / ~Bot signature only | PASS | `logs/50f210c/merger_from_signature.txt` |
| `merged_by` ignored | PASS (no merge edge) | `logs/50f210c/merged_by_ignored.txt` |
| gh calls read-only | PASS (`gh api --include` only) | `logs/50f210c/gh_readonly_static.txt` |
| No secrets in repo | PASS (test/scanner only) | `logs/50f210c/repo_secret_scan.txt` |
| Writes only intended paths (gh mocked) | PASS | `logs/50f210c/write_paths_and_gh_mock.txt` |
| **SEC-MM010-1 fix** | **PASS** | see below |

Machine-readable: `logs/50f210c/qa_report.json`  
Repro script: `scripts/qa_mm010_verify.py`

---

## SEC-MM010-1 fix verification @ 50f210c

**Expected:** Flush path calls `_looks_like_secret`; secret-like payload blocks flush even with `--force`; nothing written/pushed; output shows line numbers only (never secret value); clean payloads still flush.

**Actual:** Confirmed.

| Sub-check | Result |
|-----------|--------|
| Imports/calls `_looks_like_secret` via `secret_line_numbers` | PASS |
| Dirty ledger + `--force` → `flush=false`, `reason=secret_detected` | PASS |
| Output includes `lines` (ints only); secret token absent from stdout/stderr/JSON | PASS |
| `--payload` and `--state` not created on refuse | PASS |
| Tool has no network/`gh`/subprocess (nothing pushed) | PASS |
| Clean ledger still flushes (`reason=state_change`) and writes payload | PASS |

Excerpt (`logs/50f210c/sec_mm010_1_fix.txt`):

```
calls_scanner=True
cli_out={'flush': False, 'lines': [...], 'reason': 'secret_detected', 'sha256': '...'}
secret_in_stdout_stderr=False
payload_exists=False
state_exists=False
```

Clean flush excerpt (`logs/50f210c/sec_mm010_1_clean_flush.txt`): `flush=True`, `reason=state_change`, payload written.

---

## Findings

**None on target head `50f210c`.**

(Baseline-only observation on `3be3f32`: SEC-MM010-1 was open; fixed in `50f210c`.)

---

## Notes

- Independent QA: no product code changes; no pushes to `feat/MM-010-ledger-mirror`; no GitHub PR comments; no merge.
- `make refresh` still requires `MINDMAP_LEDGER` or `--ledger-source gh`; no fixture default (QA-MM004-3).
- Mirror tool still does not push to `data/ledger` itself (local decide + payload only); secret refuse prevents payload write that bots would push.
