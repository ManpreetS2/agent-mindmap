# Delta QA — MM-020f (PR #19) @ `62cf9b5`

**Verdict: PASS**  
**Head:** `62cf9b55fbc9e875cd13f17af390799ae855a5f9` (`62cf9b5`)  
**Prior FAIL head:** `153142044f3609b4e2afe9c176ef7dd738de6835` (`1531420`)  
**Rebased on:** `82f2066` (MM-020a tip)  
**PR:** https://github.com/ManpreetS2/agent-mindmap/pull/19  
**QA branch:** `qa/MM-020f`  
**Fresh checkout:** `/tmp/qa-mm020f-delta/checkout`  
**Environment:** Linux 6.12.94+, Python 3.12.3, Node v22.23.3, Playwright 1.49.1, Vite 5.4.21

---

## Delta vs prior FAIL

| Prior finding | @ `1531420` | @ `62cf9b5` |
|---------------|-------------|-------------|
| **QA-MM020f-1** dragged positions reset on poll | FAIL (Δ≈148×97) | **PASS** — Director + Architect + DEV 1 stable at **0px** across **two** polls; new node `qa-newcomer` placed; filter toggle keeps drag ≤1px |
| **QA-MM012-1** missing file → JSON parse under Vite | FAIL | **PASS** — `LedgerErrorView` (“Can't read build/task-ledger.md”) + Retry on vite-dev **and** vite-preview; empty/malformed also LedgerErrorView |

Fix commit: `62cf9b5` — `mergeFlowNodes` + `loadActivity` HTML/invalid-JSON → `LedgerLoadError`.

---

## Automated counts @ `62cf9b5`

| Check | Result |
|-------|--------|
| **pytest** | **117 passed**, 1 skipped (`EXIT:0`) |
| **vitest** | **81 passed** (18 files) (`EXIT:0`) |
| **typecheck** (root + web) | clean (`EXIT:0`) |
| **build** (`web` vite) | success (`EXIT:0`) |
| **CI web** | **success** — run [39396184415](https://github.com/ManpreetS2/agent-mindmap/actions/runs/39396184415) @ `62cf9b5` |
| **CI pytest** | **not triggered** on this head (path filters: tip only changes `web/**`; `python.yml` does not match). Local pytest green — see `ci_pytest_status.txt` |

Compare prior verify @ `1531420`: pytest 112 / vitest 67 (rebased stack + new unit tests for merge/loadActivity).

---

## Browser checks

### (1) QA-MM020f-1 position stability — PASS

- Dragged **Director**, **Architect**, **DEV 1**.
- Appended events; waited ≥10s (**poll 1**): all three Δ = **0 / 0** px.
- Appended again + added `qa-newcomer`; waited ≥10s (**poll 2**): dragged nodes still **0 / 0**; newcomer present at layout `(856, 216)`.
- Filter Build-only then All groups: dragged coords unchanged within **1px**.

Evidence: `screenshots/02–06`, `positions_after_drag.json`, `positions_after_poll{1,2}.json`, `filter_vs_drag_positions.json`.

### (2) QA-MM012-1 missing / empty / malformed — PASS

| Case | vite-dev | vite-preview |
|------|----------|--------------|
| Missing `activity.json` | LedgerErrorView (not JSON parse) | LedgerErrorView |
| Empty file | LedgerErrorView | LedgerErrorView |
| Malformed `{not-json` | LedgerErrorView | LedgerErrorView |

Note: `LedgerErrorView` copy uses `LEDGER_ERROR_PATH` = `build/task-ledger.md` (by design), not the string `activity.json`. Fetch still returns Vite SPA HTML 200; client now maps that to `LedgerLoadError`.

Evidence: `screenshots/09–11` (dev), `13–15` (preview); `preview_bind.txt` (`127.0.0.1:4173`).

### (3) Regression set — PASS

| Check | Result |
|-------|--------|
| Group filters + counts (Build / Q&R / all) | PASS |
| Director / Architect single shared nodes | PASS (1 each) |
| XSS via label/message | PASS (`__xss=false`) |
| Keyboard `/` + group-filter a11y + skip link | PASS |
| Dev bind `127.0.0.1:5173` | PASS |
| Preview bind `127.0.0.1:4173` | PASS |
| Console errors (demo) | PASS |
| Outbound beyond localhost | PASS |

---

## Findings @ `62cf9b5`

**No product findings.**

Harness note: an initial assert required the substring `activity.json` inside LedgerErrorView text and briefly marked QA-MM012-1 FAIL; screenshots/`Can't read build/task-ledger.md` confirm LedgerErrorView. Corrected in `playwright_report.json` (see `verdict_note`).

---

## Verdict rationale

Prior high/medium fails are fixed and re-verified in headless Playwright (incl. two-poll drag stability and production preview). Suites green; CI web green; CI pytest path-skipped but local 117/1. **PASS**.

---

## Notes

- Verify-only: no product edits; no push to PR branch; no GitHub comments; no merge; no QA PR.
- Evidence only on `qa/MM-020f` under `logs/62cf9b5…/` + this `DELTA_REPORT.md`.
