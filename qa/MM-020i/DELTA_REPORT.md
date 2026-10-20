# Delta QA — MM-020i / PR #24 @ `f1a92a9`

**Verdict: PASS** (6/6 prior findings cleared; 0 new issues in fix diff)  
**Head:** `f1a92a95b1248ae9a01b71744736f910df7d31d8` (`f1a92a9`)  
**Base:** `feat/MM-020-unified-network` @ `1c01d47`  
**Prior FAIL:** @ `06e5bda` — see `REPORT.md`  
**Fix commits reviewed (rebase noise excluded):**
- `5e3677f` — `fix(MM-020i): QA mode isolation, banner contract, demo CLI guards`
- `f1a92a9` — `test(MM-020i): static start-mac demo/gh-auth checks (no long-running --demo)`  
**QA branch:** `qa/MM-020i` (evidence only; no product edits; no PR comment; no merge)

---

## Exact counts

| Check | Result |
|-------|--------|
| Finding repros QA-MM020i-1…6 | **6 PASS / 0 FAIL** |
| Fix-diff new-issue smoke | **PASS** (no conflict markers; assemble `mode=live`; demo serve intact) |
| **pytest** (outer venv @ head) | **237 passed**, **2 skipped** |
| **vitest** | **99 passed** (21 files) |
| **CI python** @ `f1a92a9` | **success** — 237 passed, 2 skipped ([39500796565](https://github.com/ManpreetS2/agent-mindmap/actions/runs/39500796565)) |
| **CI web** @ `f1a92a9` | **success** ([39500796549](https://github.com/ManpreetS2/agent-mindmap/actions/runs/39500796549)) |

Note: running pytest with interpreter inside `ROOT/.venv` can trip `test_broken_venv_triggers_reinstall` (`venv_backup` moves that tree). Not a product regression — CI and outer-venv local runs are clean **237/2**. Test is from #22, not introduced by these fix commits.

---

## Fix scope (lean)

| Area | Change |
|------|--------|
| Live isolation | `activity_bytes_match_server_mode` / `_store_activity_bytes` / `activity_bytes_for_serve` + `empty_live_activity_bytes` fallback |
| Assemble | live builds set `meta.mode=live` |
| Schema | `meta.mode` enum + `ledger: demo` |
| Banner | always-rendered `ModeBanner` with `loading` / `unknown` / `demo` / `live`; `parseHealthzMode`; exponential backoff retry |
| CLI | `--demo` + `--events-source gh` → exit 2 |
| start-mac | rebase conflict cleanup; `--demo` skips `require_gh_auth` |

---

## Finding re-checks

| ID | Prior | Now | Repro result |
|----|-------|-----|--------------|
| **QA-MM020i-1** | F1b stale demo pre-poll | **PASS** | Write `load_demo_activity_bytes()` to activity-out; `_load_activity_from_disk()`; serve before poll → `/healthz`=`live`, `/activity.json` `meta.mode=live` (agree) |
| **QA-MM020i-2** | F1 stale demo + missing ledger | **PASS** | Same file + missing ledger + `run_poll_cycle` → both endpoints `mode=live` (`ledger=error` empty-live fallback) |
| **QA-MM020i-3** | F2 banner not always visible | **PASS** | `App` always mounts `<ModeBanner state={bannerState}/>`; initial `loading`; failed → `unknown` copy |
| **QA-MM020i-4** | F3 missing mode faked LIVE | **PASS** | `parseHealthzMode`: only `"demo"`/`"live"` accepted; else `unknown` (vitest: missing mode → unknown) |
| **QA-MM020i-5** | F4 one-shot / no retry | **PASS** | Backoff retry on error; vitest recovers `unknown` → `live` after failed first fetch |
| **QA-MM020i-6** | F5 flag combo silent | **PASS** | `live_main(["--demo","--events-source","gh"]) == 2` + stderr reject message |

Evidence: `logs/f1a92a9…/delta_repro.json`, `delta_repro.log`, `vitest_targeted.log`, `pytest_targeted.log`

---

## New issues in fix diff?

| Check | Result |
|-------|--------|
| Conflict markers left in `start-mac.sh` | **None** |
| Demo still serves `meta.mode=demo` | **PASS** |
| Live assemble stamps `meta.mode=live` | **PASS** |
| Cross-mode store rejected | Covered by unit tests in fix |
| Unrelated regressions in suites | **None** (237 / 99; CI green) |

No new findings opened this delta.

---

## Verdict

All six findings from the `06e5bda` FAIL are cleared on `f1a92a9` with independent repros. Suites and CI match. **PASS.**
