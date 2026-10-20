# QA Report — MM-020f (PR #19) multi-group graph UI

**Verdict: FAIL** (1 high, 1 medium, 1 low)  
**Target head:** `153142044f3609b4e2afe9c176ef7dd738de6835` (`1531420`)  
**PR head at verify time:** `1531420` (unchanged from requested)  
**PR:** https://github.com/ManpreetS2/agent-mindmap/pull/19  
**Base:** `feat/MM-020-unified-network`  
**QA branch:** `qa/MM-020f`  
**Environment:** Linux 6.12.94+, Python 3.12.3, Node v22.23.3, Playwright 1.49.1 Chromium headless, Vite 5.4.21  
**Fresh checkout:** `/tmp/qa-mm020f/checkout` @ `1531420`

---

## Acceptance sources

- PR #19 body: cluster layout, glass/neon frames, message edges, group filter + legend, MiniMap/drag/reduced-motion; scope `web/`
- `docs/MM-020-audit.md` §0 / §7 MM-020f / §8: one identity across groups (Director/Architect), group edges, localhost
- Prior QA invariants (MM-012): QA-MM012-1 missing activity, verdict fallback, self-loops, XSS, a11y, bind, outbound
- QA-MM020a-1: duplicate `groups.json` members must not duplicate chips/nodes in UI

---

## Checks @ `1531420`

| Check | Result | Evidence |
|-------|--------|----------|
| `python3 -m pytest -q` (no generated `web/public/activity.json`) | **112 passed**, 1 skipped | `logs/1531420…/pytest.txt` |
| Note: pytest with generated 1.1.0 `public/activity.json` | 1 fail on legacy-fixture assert (env artifact; file gitignored) | `logs/…/pytest_with_generated_activity.txt` |
| `cd web && npm test` (vitest) | **67 passed** (16 files) | `logs/…/vitest.txt` |
| `tsc` root + web | clean | `logs/…/typecheck-*.txt` |
| `cd web && npm run build` | success | `logs/…/build.txt` |
| CI web workflow @ head | **success** (run 39394328429) | `logs/…/ci_checks.txt` |
| Dev server bind `127.0.0.1` only | **PASS** (`LISTEN 127.0.0.1:5173`) | `logs/…/dev_bind.txt`, `dev_bind_proc.txt` |
| Demo multi-group UI + filter | **PASS** | `screenshots/01-demo-multigroup.png` |
| Director/Architect single shared nodes | **PASS** (1 each; 14 unique ids) | `screenshots/02-shared-nodes-membership.png` |
| Membership edges (secondary groups) | **PASS** (4) | Playwright |
| Group filter each / combo / all / cannot-none | **PASS** (counts correct) | `screenshots/03–06-*.png` |
| Filter survives refresh | **N/A** (not required by PR/docs; state resets) | `filter_persist.json` |
| Node positions stable after event append (dragged) | **FAIL** | `screenshots/08–09`, `position_deltas.json` |
| QA-MM012-1 missing → LedgerErrorView | **FAIL** (JSON parse via Vite SPA 200) | `screenshots/10-missing-activity.png` |
| Empty / malformed activity.json | **PASS** (error + Retry) | `screenshots/11–12` |
| Verdict fallback | **PASS** | `screenshots/13-verdict-fallback.png` |
| No self-loops | **PASS** | Playwright + activity edges |
| XSS group/agent/message | **PASS** | `screenshots/14-xss-payload.png` |
| Keyboard + group-filter a11y | **PASS** | `screenshots/15-keyboard.png` |
| No console errors / no outbound | **PASS** | `console_errors.json`, `outbound_requests.json` |
| QA-MM020a-1 duplicate members → UI | **PASS** (chips/nodes unique) | `screenshots/16-duplicate-membership.png` |

Machine-readable: `logs/1531420…/playwright_report.json`  
Harness: `scripts/qa_mm020f_playwright.mjs`

---

## PR claims vs observed

| Claim | Observed |
|-------|----------|
| Dagre-per-cluster; one node identity for multi-membership | PASS |
| Glass/neon group frames | PASS (screenshots) |
| Message edges distinct + legend includes message/membership | PASS (legend + DOM edges) |
| Group filter | PASS (per-group, combo, all, ≥1 enforced) |
| MiniMap, dragging, reduced-motion preserved | MiniMap+drag present; drag **position not preserved on poll** → FAIL finding |
| Scope `web/` only | Confirmed by PR diff intent; no product edits by QA |

Note: Full MM-020f audit AC also lists SSE transport (depends on MM-020d). This PR does not claim SSE delivery; not scored as a regression here.

---

## Findings @ `1531420`

### QA-MM020f-position-reset — Dragged nodes reset when new events arrive

| Field | Value |
|-------|-------|
| **component** | `web/src/components/AgentGraph.tsx` (`useEffect` syncing `builtNodes` → `setNodes`) |
| **expected** | After user drag, node coordinates stay put when `activity.json` gains events via poll |
| **actual** | Director dragged to ~`(188, 313)`; after append+~12s poll, reset to layout ~`(40, 216)` (Δ≈148×97). Root cause: `layoutChanged` compares previous (possibly dragged) positions to new layout positions, so any drag looks like a layout change and replaces nodes with `builtNodes`. |
| **repro** | `make refresh-demo`; `cd web && npm run dev`; drag Director; append a message event+edge to `web/public/activity.json`; wait >10s; compare `.react-flow__node[data-id=director]` transform |
| **evidence** | `logs/…/screenshots/08-after-drag-director.png`, `09-after-event-append.png`, `position_deltas.json`, `positions_after_drag.json`, `positions_after_append.json` |
| **environment** | Linux, Vite 5.4.21, Playwright 1.49.1, head `1531420` |
| **severity** | high |
| **confidence** | high |

### QA-MM012-1 — Missing `activity.json` under Vite does not hit `LedgerErrorView`

| Field | Value |
|-------|-------|
| **component** | `loadActivity` + Vite SPA host |
| **expected** | Missing file → 404/422 → `LedgerErrorView` (“Can't read …”) + Retry |
| **actual** | Vite serves `index.html` with **HTTP 200** for `/activity.json`; UI shows JSON parse error + Retry |
| **repro** | `rm web/public/activity.json`; `curl -i http://127.0.0.1:5173/activity.json`; reload UI |
| **evidence** | `screenshots/10-missing-activity.png`, `missing_activity_fetch.json` |
| **environment** | Vite 5.4.21, Playwright, head `1531420` |
| **severity** | medium |
| **confidence** | high |

Notes: Empty + malformed paths OK. Same host-fallback finding as MM-012 QA; still open on this head. Live daemon path (true 404) not re-scored here.

### QA-MM020a-1-note — `membership_index` does not dedupe duplicate members

| Field | Value |
|-------|-------|
| **component** | `ingest/membership.py` `membership_index` |
| **expected** | (UI AC) duplicate `groups.json` members must not create duplicate chips/nodes — **UI PASS**. Optional ingest hardening: unique group ids per bot |
| **actual** | With `director` listed thrice under `build.members`, index → `["build","build","build","qr","radar"]`. UI still one Director node and unique filter chips (`collectGroupIds` uses a `Set`) |
| **repro** | Duplicate bot id in a group's `members`; call `membership_index`; load activity with repeated `node.groups` |
| **evidence** | `qa_mm020a1_membership_index.json`, `qa_mm020a1_ui.json`, `screenshots/16-duplicate-membership.png` |
| **environment** | Python ingest + Playwright @ `1531420` |
| **severity** | low |
| **confidence** | high |

---

## Verdict rationale

Automated suites and CI are green; multi-group identity, filters, membership edges, XSS/a11y/localhost checks pass. **FAIL** because dragged node positions reset on live poll updates (high) — directly contradicts the stated position-stability acceptance check for this verify. QA-MM012-1 remains medium (pre-existing host behavior).

---

## Notes

- Independent QA: no product edits; no push to `feat/MM-020f-multigroup-graph`; no GitHub comments on PR #19; no merge; no QA PR opened.
- Artifacts only on `qa/MM-020f`.
