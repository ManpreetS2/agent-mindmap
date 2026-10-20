# Delta QA — MM-020e (PR #20) @ d8c8ea0

| Field | Value |
|-------|-------|
| **Verdict** | **PASS** |
| **Range** | `239a8e9` → `d8c8ea0` (fix-only; no full re-audit) |
| **Head** | `d8c8ea001ae9b4a45be482161ae59126d22cc60b` |
| **PR** | https://github.com/ManpreetS2/agent-mindmap/pull/20 |
| **Evidence** | `qa/MM-020e/` (this file + `logs/d8c8ea0…/`) |
| **Mode** | verify-only |

## Verdict

**PASS.** All seven named fixes reproduce behaviorally. Suite: **204 passed, 1 skipped** (pytest ×1); vitest **89 passed**; CI **success** on head. Diff adds **1 LOW** residual (orphan EventSource on unmount during SSE retry) — not a FAIL.

Closed from prior FAIL @ `239a8e9`: F1 (SSE recovery), F2 (slot leak), F3 (uncapped log summaries), N1 (markup display).

## Fix confirmations

| ID | Result | Behavioral repro |
|----|--------|------------------|
| **QA-MM020e-3** | **PASS** | Transport retries EventSource after poll fallback; `onopen` clears poll and sets `fellBack = false`. Vitest `QA-MM020e-3 SSE recovery` + source has `tryReconnectSse` / `scheduleSseRetry`. |
| **QA-MM020e-4** | **PASS** | Abort storm during initial push → `sse_limiter.active_count() == 0` (`qa4_slots.json`: `{"active": 0}`). Also `tests/test_live.py::test_qa_mm020e4_sse_slots_released_after_mid_push_abort`. |
| **QA-MM020e-5** | **PASS** | Oversized summary capped to 240; secret summary rejected + increments drop counter (`qa5_cap.json`). |
| **QA-MM020e-6** | **PASS** | `plainTextForDisplay` strips tags; used in DetailPanel + UnparsedPanel. Vitest `plainText.test.ts`: `'<img…>hello'` → `'hello'`. |
| **SEC-MM020e-2** | **PASS** | Commit body `~DEV 2` ignored; actor from `author.login` → `manpreet` + `github-verified`. Unmapped / missing login → `actor=null`, `agent-reported` (`sec2_actor.json`). |
| **SEC-MM020e-3** | **PASS** | `/healthz` returns `dropped_network_events >= 1` after secret ingest; secret text absent from body (`sec3_healthz.json`). |
| **SEC-MM020e-4** | **PASS** | `SSE_REFETCH_MIN_MS = 1000` + `createDebouncedRefetch`; vitest burst of 120 messages → ≤2 fetches in 500ms, total &lt;20 over ~2.5s. |

## New issues in diff

| ID | Severity | Notes |
|----|----------|-------|
| **N1** | **LOW** | `tryReconnectSse` creates an EventSource before `onopen` assigns `source`. Unsubscribe only closes `source`, so an in-flight retry ES may linger until error. Short-lived; no FAIL. |
| **N2** | **LOW** (nit) | `_resolve_merger` left unused after merger switched to commit-author login. Dead code only. |

No HIGH/MEDIUM regressions found in the delta.

## Counts

| Check | Result |
|-------|--------|
| pytest @ `d8c8ea0` | **204 passed, 1 skipped** |
| vitest | **89 passed** (19 files); focus suite 10/10 (transport + plainText) |
| CI pytest | **success** — https://github.com/ManpreetS2/agent-mindmap/actions/runs/39496275031 |
| CI web | **success** — https://github.com/ManpreetS2/agent-mindmap/actions/runs/39496275051 |
| Delta harness | **7/7 OK** |

## Diff touch list (14 files)

`ingest/github_poller.py`, `ingest/live.py`, `schema/activity.schema.json`, `shared/types.ts`, fixtures/tests, `activityTransport.ts` (+tests), `plainText.ts` (+tests), DetailPanel, UnparsedPanel.
