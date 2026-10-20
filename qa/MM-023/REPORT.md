# QA Report — MM-023 / PR #23 (MM-020e2) @ 0e65cd0

| Field | Value |
|-------|-------|
| **Verdict** | **PASS** |
| **PR** | https://github.com/ManpreetS2/agent-mindmap/pull/23 |
| **Title** | MM-020e2: merged_by merger attribution + SSE unsubscribe cleanup |
| **Head** | `0e65cd07f157413760c7f460a278e4476eeaf1d8` |
| **Base** | `feat/MM-020-unified-network` @ `b2baf35` |
| **Diff scope** | 4 files (+200 / −59) |
| **Evidence branch** | `qa/MM-023` |
| **Mode** | verify-only |

## Verdict

**PASS.** All three requested behaviors reproduce. Suite: **207 passed, 1 skipped** (pytest); vitest **92 passed**; CI **success** on head. **Findings: 0.**

## Checks

| # | Check | Result | Evidence |
|---|-------|--------|----------|
| 1 | Merger from `merged_by.login` — mapped → `github-verified`; else `agent-reported` (incl. squash SHA absent from commits, missing `merged_by`) | **PASS** | `logs/…/merged_by.json` |
| 2 | `_resolve_merger` removed; no dangling refs | **PASS** | `resolve_merger_refs.txt` → `(none)` |
| 3 | QA-MM020e-7: unsubscribe before `onopen` closes pending reconnect ES | **PASS** | `qa7_transport.json`; vitest `QA-MM020e-7` (3 tests) |
| 4 | No new issues; pytest ×1; vitest; CI | **PASS** | counts below |

### (1) Merger attribution

| Case | actor | provenance | method |
|------|-------|------------|--------|
| `merged_by.login=ManpreetS2` (mapped) | `manpreet` | `github-verified` | `github_login` |
| `merged_by.login=dependabot[bot]` | `null` | `agent-reported` | `github_login_unmapped` |
| Missing `merged_by` | `null` | `agent-reported` | `unknown` |
| Squash SHA not in `/commits`, `merged_by` present | `manpreet` | `github-verified` | (login) |

Repro: MockGh PR with `merged_at` + crafted `merged_by` / empty commits → `poll_github` → inspect `type=="merged"`.

### (2) Dead code removal

`_resolve_merger` and `_LEDGER_STYLE_MERGED_RE` deleted from `ingest/github_poller.py`. Repo-wide `rg _resolve_merger` → no hits. Replacement: `_merged_by_login(pr)`.

### (3) QA-MM020e-7

`pendingReconnect` tracked; `dispose()` / `closePendingReconnect()` close it; cancelled `onopen` closes ES. Vitest: unsubscribe after fallback retry → `openFakeEventSources().length === 0` (including after further timer advance).

## Findings

None.

## Counts

| Run | Result |
|-----|--------|
| pytest @ `0e65cd0` | **207 passed, 1 skipped** |
| vitest | **92 passed** (19 files); transport focus **11/11** |
| CI pytest | **success** — https://github.com/ManpreetS2/agent-mindmap/actions/runs/39497533486 |
| CI web | **success** — https://github.com/ManpreetS2/agent-mindmap/actions/runs/39497533514 |
| Behavioral harness | **3/3 OK** |

## Diff touch list

`ingest/github_poller.py`, `tests/test_github_poller.py`, `web/src/data/activityTransport.ts`, `web/src/test/activityTransport.test.ts`.
