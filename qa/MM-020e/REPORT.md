# QA Report — MM-020e (PR #20) complete pass @ 239a8e9

| Field | Value |
|-------|-------|
| **Verdict** | **FAIL** |
| **PR** | https://github.com/ManpreetS2/agent-mindmap/pull/20 |
| **Verified head** | `239a8e98909fc40bb5f6d4ba649631298ce84b8a` |
| **Prior FAIL** | `9a30965` (QA-MM020e-1/2 title + review `raw` leaks) |
| **Base** | `feat/MM-020-unified-network` |
| **Evidence branch** | `qa/MM-020e` |
| **Fresh checkout** | `/tmp/qa-mm020e-final/checkout` |
| **Date (UTC)** | 2026-10-20 |
| **Mode** | verify-only — evidence only; no product changes, no PR comments, no merges |

## Verdict

**FAIL.** Prior HIGH findings **QA-MM020e-1 / QA-MM020e-2** (secrets in PR title / review / comment / commit → `raw` / activity.json) are **fixed** at `239a8e9` via centralized `_event()` → `sanitize_pr_summary` → `tools.secret_scan`. Suite/CI are green (**200 passed, 1 skipped** ×3; vitest **85**; typecheck/build OK; CI success on head).

This pass still fails the AC matrix on:

1. **SSE does not recover** after poll fallback (check 4).
2. **SSE slot leak** via `UnboundLocalError` on client disconnect during the initial event push (check 5 / 020d surface).

Exact finding counts: **2 HIGH**, **1 MEDIUM**, **1 LOW**. Closed prior: **2 HIGH** (title/review raw).

## Delta vs 9a30965 FAIL

| Item | At 9a30965 | At 239a8e9 |
|------|------------|------------|
| Commit subject → `raw` | Fixed (SEC-MM020e-1) | Still fixed (via `_event`) |
| PR title / review / comment → `raw` | **FAIL** (residual) | **PASS** — events dropped; secret absent from activity.json / NetworkEvent |
| Central sanitizer | Per-path commit only | **One gate** in `_event()`; callers use `_append_unique` |
| Live SSE + UI EventSource | Not wired | Wired (`poll_github_once` → `build_pr_lane_events` → log; App `createSseTransport`) |

Commits after prior FAIL tip: `afa7b73` (central `_event` sanitize), `239a8e9` (live SSE + UI transport).

## Checks

| # | Check | Result | Evidence |
|---|-------|--------|----------|
| 1 | QA-MM020e-1/2 whole-class secret refusal; central sanitizer; shared `secret_scan`; no `sk-` FP | **PASS** | `whole_class_secrets.json`, `central_sanitizer.json`, `sk_false_positives.json`, `tests/test_pr_lanes.py::test_qa_mm020e_secret_raw_dropped_on_all_paths` |
| 2 | PR lanes (`github-verified`, stable ids, dedupe) | **PASS** | `pr_lanes.json`, `test_pr_lane_events_*` |
| 3 | Live SSE e2e: UI path, order, Last-Event-ID | **PASS** | `sse_e2e.json`; `test_sse_replay_last_event_id_and_dedupe`; App → `createSseTransport` → onmessage → `activity.json` refetch (no full reload) |
| 4 | SSE first → poll fallback → **recover to SSE** | **FAIL** | `sse_fallback_recovery.json`, `FINDING_SSE_NO_RECOVERY.txt` |
| 5 | Abuse / edge: malformed, oversized, unicode, bursts | **FAIL** (limiter leak) / otherwise OK | `abuse_edge.json`, `sse_limiter_leak.json`, `sse_limiter_repro*.txt` |
| 6 | No regressions 020a–d/f; pytest×3; vitest; typecheck; build; CI on head | **PASS** (with SSE traceback noise from F2) | `pytest_counts.json`, `pytest_x3.txt`, `vitest.txt`, `ci_checks.txt` |

Harness: `qa/MM-020e/harness/test_qa_mm020e_final.py` — **7/7 OK**.

### Check 1 detail (closed prior FAIL)

Probed sources into `_event()` / activity sink:

| Source | Secret lands in `raw` or any field? |
|--------|-------------------------------------|
| PR title | No — `pr_opened` dropped |
| Review body | No — event dropped |
| Comment body (email) | No — event dropped |
| Commit subject | No — event dropped |
| Branch name `feat/<sk-…>` | No — not stored; `task_id` null; clean title event OK |
| PR body nested (title clean) | No secret in event blob |
| Prebuilt dirty event → `build_pr_lane_events` | Refused (`summary` sanitize) |
| `activity.json` on disk | Secret absent; `task-runner` benign present |

Centralization: AST confirms single `sanitize_pr_summary` call inside `_event`; poller has no local `sk-`/AKIA regex; import is `tools.secret_scan.looks_like_secret`. Benign `task-runner` / `SK-` uppercase / short `sk-` do not false-positive.

### Check 4 detail

`createSseTransport` (`web/src/data/activityTransport.ts`):

- Prefers EventSource `/events` (**SSE first**) — PASS.
- On `onerror` / missing EventSource → `startPollFallback()` — PASS.
- Sets `fellBack = true` **permanently**; never resets; no reconnect/recover path — **FAIL** “recovers back to SSE”.

### Check 3 detail

- `poll_github_once` → `build_pr_lane_events` → `ingest_network_events` → `GET /events`.
- Ordered delivery matches `network_events_after(None)`.
- `Last-Event-ID` resumes at next id; newly ingested id appears on resume.
- UI: `App.tsx` uses `createSseTransport`; `useActivityFeed` applies snapshots from subscribe (refetch on SSE message) without page reload. Vitest covers message → refetch and poll fallback.

## Findings

### F1 — SSE transport never recovers to EventSource after poll fallback

| | |
|---|---|
| **Severity** | **HIGH** |
| **Confidence** | **HIGH** |
| **Component** | `web/src/data/activityTransport.ts` (`createSseTransport`) |
| **Expected** | SSE first; on SSE down → poll; when SSE is healthy again → resume SSE |
| **Actual** | First `onerror` latches `fellBack = true`, closes EventSource, starts poll forever for that subscription |
| **Repro** | 1) Open App with EventSource available. 2) Force `/events` error (stop daemon or inject `FakeEventSource.emitError()`). 3) Observe poll ticks. 4) Restore `/events`. 5) No new EventSource is opened; `fellBack` stays true. Static proof: `fellBack = true` once; no second `fellBack = false` / reconnect. |
| **Evidence** | `logs/239a8e9…/sse_fallback_recovery.json`, `FINDING_SSE_NO_RECOVERY.txt`, `activityTransport.ts:108–134` |

### F2 — Client disconnect during initial SSE push → `UnboundLocalError` + connection-slot leak

| | |
|---|---|
| **Severity** | **HIGH** |
| **Confidence** | **HIGH** |
| **Component** | `ingest/live.py` `_handle_sse` |
| **Expected** | Broken pipe / reset during push is handled; `sse_limiter.release()` always runs |
| **Actual** | Initial `_push_sse_events` (before `conn = self.connection`) can raise `BrokenPipeError`/`ConnectionResetError`. `finally` references unbound `conn` → `UnboundLocalError`, so **`release()` is skipped** and slots stick |
| **Repro** | Seed ≥20 network events; open `GET /events`; hard-close the socket mid-push; repeat. Observe server traceback `UnboundLocalError: conn`; `sse_limiter.active_count()` remains elevated (evidence: **7 / 8** after abort storm). Further aborts can exhaust `MAX_SSE_CONNECTIONS` (8) → **503** for healthy clients |
| **Evidence** | `sse_limiter_leak.json`, `sse_limiter_repro.txt`, `sse_limiter_repro2.txt`; also noisy tracebacks during `pytest` live SSE tests |
| **Note** | Regression surface on MM-020d SSE; exposed/exercised by MM-020e PR-lane volume on `/events` |

### F3 — `NetworkEventLog` accepts uncapped oversized summaries on non-PR-lane ingest

| | |
|---|---|
| **Severity** | **MEDIUM** |
| **Confidence** | **HIGH** |
| **Component** | `ingest/live.py` `NetworkEventLog.append_many` |
| **Expected** | Abuse budget / size discipline consistent with 240-char PR summary policy for streamed payloads |
| **Actual** | Arbitrary ingest (test/helper / events mirror path) stores `summary` of length ≫240; PR-lane path caps via `sanitize_pr_summary` |
| **Repro** | `daemon.ingest_network_events([{..., "summary": "x"*10000}])` — accepted and streamed on `/events` |
| **Evidence** | `abuse_edge.json` (`oversized` capped in sanitize; burst summaries with 300+ chars accepted into log) |

### N1 — XSS markup may still be stored in sanitized `raw` (informational)

| | |
|---|---|
| **Severity** | **LOW** |
| **Confidence** | **HIGH** |
| **Component** | DetailPanel + `_event` |
| **Actual** | No `dangerouslySetInnerHTML` in `web/src`; React text binding escapes. Non-secret markup subjects can remain in `raw` after whitespace/cap sanitize |
| **Evidence** | Prior `xss_ui_scan` pattern; DetailPanel `{lastActivity.event.raw}` |

## Suite / CI counts

| Run | Result |
|-----|--------|
| pytest ×3 @ `239a8e9` | **200 passed, 1 skipped** (each run) |
| vitest | **85 passed** (18 files) |
| `npm run typecheck` | exit 0 |
| `npm run build` | exit 0 |
| CI pytest | **success** — https://github.com/ManpreetS2/agent-mindmap/actions/runs/39412511015 |
| CI web | **success** — https://github.com/ManpreetS2/agent-mindmap/actions/runs/39412511670 |
| Regression subset (020a/b/c/e + live + secret_scan + ledger_mirror) | **106 passed, 1 skipped** |
| Behavioral harness | **7 passed** |

## Closed findings (from prior FAIL @ 9a30965)

- **QA-MM020e-1** — Unsanitized PR title → `event.raw` / activity.json — **CLOSED**
- **QA-MM020e-2** — Unsanitized review/comment body → `event.raw` / activity.json — **CLOSED**

## How to re-run

```bash
git fetch origin feat/MM-020e
git checkout 239a8e98909fc40bb5f6d4ba649631298ce84b8a
python3 -m pytest -q          # expect 200 passed, 1 skipped
cd web && npm ci && npm run typecheck && npm run test && npm run build
# harness (point ROOT inside script if needed):
python3 qa/MM-020e/harness/test_qa_mm020e_final.py
```
