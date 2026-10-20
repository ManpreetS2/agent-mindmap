# QA Report — MM-010 (PR #11) ledger mirror

**Verdict: PASS**  
**Target head:** `0c500c1d272989bd415d14b3d6510703c44f2ce2`  
**Base:** `main` @ `63e1bdf515b98bb1517addcf43b4373ea248778d`  
**PR head at verify time:** `0c500c1` (rebased from `50f210c`; Architect: no code change — **confirmed**)  
**QA branch:** `qa/MM-010`  
**Environment:** Linux, Python 3.12.3, Node v22.23.3, gh 2.102.0  
**Fresh checkout:** `/tmp/qa-mm010/repo` @ `0c500c1`

---

## Rebase vs `50f210c` (Architect claim)

**Conclusion: rebase-only. No MM-010 product code change.**

| Evidence | Result |
|----------|--------|
| Tree delta `50f210c` → `0c500c1` | Only **adds** `.github/workflows/python.yml` + `requirements-dev.txt` |
| Those two blobs | Identical to `main` `63e1bdf` (inherited from new base / CI #9) |
| All MM-010 product blobs | **IDENTICAL** (`tools/ledger_mirror.py`, `ingest/ledger_fetch.py`, `ingest/build.py`, tests, schema, README, `web/src`, …) |
| feat commit `patch-id --stable` | OLD `3be3f32` == NEW `e1e5be8` → `226e6862…` |
| fix commit `patch-id --stable` | OLD `50f210c` == NEW `0c500c1` → `4fa977d4…` |

Evidence: `logs/0c500c1/rebase_vs_50f210c.txt`

---

## Checks @ `0c500c1`

| Check | Result | Evidence |
|-------|--------|----------|
| `python3 -m pytest -q` | **83 passed** | `logs/0c500c1/pytest.txt` |
| `cd web && npm test` | **40 passed** | `logs/0c500c1/vitest.txt` |
| tsc (root + web) | clean | `logs/0c500c1/typecheck-*.txt` |
| `cd web && npm run build` | success | `logs/0c500c1/build.txt` |
| Fixtures vs schema | PASS | `logs/0c500c1/fixture_validation.txt` |
| Required ledger path / no default | PASS | `logs/0c500c1/missing_ledger_path.txt` |
| Malformed ledger (local + gh) | PASS | `logs/0c500c1/malformed_ledger_*.txt` |
| Idempotent mirror + ingest | PASS | `logs/0c500c1/idempotent_*.txt` |
| PR joins `(repo, number)` | PASS | `logs/0c500c1/pr_join_repo_number.txt` |
| Merger ledger/~Bot; `merged_by` ignored | PASS | `logs/0c500c1/merger_*.txt`, `merged_by_*.txt` |
| gh read-only; no secrets; write paths | PASS | `logs/0c500c1/gh_readonly_static.txt`, `repo_secret_scan.txt`, `write_paths_*.txt` |
| SEC-MM010-1 secret-block (+ `--force`) | PASS | `logs/0c500c1/sec_mm010_1_fix.txt`, `secret_block_pytest.txt` (3 passed) |
| Clean payload still flushes | PASS | `logs/0c500c1/sec_mm010_1_clean_flush.txt` |
| **CI run 39387114238** | **success** / **83 passed** | `logs/0c500c1/ci_39387114238.txt` |

Machine-readable: `logs/0c500c1/qa_report.json`  
Script: `scripts/qa_mm010_verify.py`

---

## CI run 39387114238

- URL: https://github.com/ManpreetS2/agent-mindmap/actions/runs/39387114238  
- Workflow: `python` / job `pytest`  
- `headSha`: `0c500c1d272989bd415d14b3d6510703c44f2ce2`  
- Conclusion: **success**  
- Log: `83 passed in 1.86s`

---

## Findings @ `0c500c1`

**None.**

---

## Prior heads (context only)

| Head | Role | Notes |
|------|------|-------|
| `3be3f32` | baseline | pytest 80; SEC-MM010-1 open |
| `50f210c` | prior PASS | SEC-MM010-1 fixed; pytest 83 |
| `0c500c1` | **verdict target** | rebase onto `63e1bdf`; product identical to `50f210c` |

---

## Notes

- Independent QA: no product edits; no push to `feat/MM-010-ledger-mirror`; no comments on PR #11; no merge.
- Architecture file `build/mindmap/architecture.md` still not in this repo; AC from PR body/report + README.
