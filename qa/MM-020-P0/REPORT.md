# QA Report — MM-020-P0 combined verify

**Verdict: FAIL** (3 high, 3 medium)  
**Local merge:** `1ce590c679b3a1f2e0377525c5a76baf79de6f37` = `feat/MM-020-unified-network` + backend PR [#30](https://github.com/ManpreetS2/agent-mindmap/pull/30) @ `4bcb907f5eaa47e68f164d548b6717f07cd3d291` + web PR [#29](https://github.com/ManpreetS2/agent-mindmap/pull/29) @ `e3d4db59b04237563150d0ea5b5d6817e1a6a403`  
**QA branch:** `qa/MM-020-P0` (evidence only)  
**Fresh checkout:** `/tmp/qa-mm020p0/checkout`  
**Runtime:** `./scripts/start-mac.sh` LIVE on `127.0.0.1:8787` + stub `gh` (ledger 404, mutable `events.jsonl`, MockGh PRs)  
**Environment:** Linux 6.12 (Playwright Chromium); macOS-only Dock/`open` **DEFERRED**

Verify-only: no product edits; no PR opened; no PR comments; no merge pushed.

> Note: PR #30 tip later moved to `dbee348` (SEC follow-up). This pass verified the requested SHAs `4bcb907` + `e3d4db5` only.

---

## Checklist (1)–(9)

| # | Item | Result |
|---|------|--------|
| 1 | Missing ledger → SOURCE UNAVAILABLE + `ledger_error`; GitHub/network still render; not 0 events/edges; GitHub not skipped; nodes UNKNOWN not fake IDLE | **PARTIAL** — banners/meta/events/edges/github=ok **PASS**; nodes stay **IDLE** → **F1** |
| 2 | Live network event appears without reload | **FAIL** → **F2** |
| 3 | POST `/refresh` → 202; burst → 429 + countdown; Retry disabled; server stopped → "server unreachable" | **PASS** |
| 4 | Kill SSE → DISCONNECTED in single status bar; no duplicate bars | **PARTIAL** — single bar **PASS**; DISCONNECTED after SSE abort **FAIL** → **F3** (appears when server stopped — see unreachable shot) |
| 5 | Header agent-mindmap not Fencepost; Fencepost events have repo tag + filter | **PARTIAL** — header `Project: Agent-Mindmap` (CSS capitalize of `agent-mindmap`, not Fencepost) **PASS**; repo tag/filter **FAIL** → **F4** |
| 6 | Edges only from real recipients; nothing inferred/fabricated | **PASS** (3 message edges, 0 fabricated) |
| 7 | `start-mac.sh` rebuilds dist when `web/src` or `shared/` newer; otherwise not | **PASS** (`NEEDS_REBUILD` / `NO_REBUILD`) |
| 8 | `/refresh` Host/Origin gate: bad Host 403; `Origin: null` 403; foreign Origin 403; same-origin allowed; GET/other methods correct | **PASS** (403/403/403/429/404/405) |
| 9 | MM-020g leftovers: 3 team groups + Owner standalone; Bug fixer not in Radar; drag persists; message edges; no UNKNOWN sender when known | **PARTIAL** — groups/message edges/known senders **PASS**; Bug fixer still in Radar → **F5**; drag no persist → **F6** |

---

## Exact counts

| Check | Result |
|-------|--------|
| Local merge | clean (#30 then #29) → `1ce590c` |
| `./scripts/start-mac.sh` LIVE | **PASS** — `mode=live` on `127.0.0.1:8787` |
| E2E harness (raw) | **28 PASS / 7 FAIL / 2 INFO** (one FAIL = casing false positive on header; product findings below = **6**) |
| **pytest** (merged tree) | **260 passed**, **2 skipped** |
| **vitest** (merged `web/`) | **126 passed** (25 files) |
| **typecheck** | clean (`web` + root `tsc --noEmit`) |
| **build** | clean (`npm run build` in `web/`) |
| **CI python** @ `4bcb907` | **success** — 260 passed, 2 skipped ([39507516641](https://github.com/ManpreetS2/agent-mindmap/actions/runs/39507516641)) |
| **CI web** @ `4bcb907` | **success** — 99 passed / 21 files ([39507516660](https://github.com/ManpreetS2/agent-mindmap/actions/runs/39507516660)) — backend-tree web only |
| **CI web** @ `e3d4db5` | **success** — 126 passed / 25 files ([39508069319](https://github.com/ManpreetS2/agent-mindmap/actions/runs/39508069319), also [39507073629](https://github.com/ManpreetS2/agent-mindmap/actions/runs/39507073629)) |
| Findings this pass | **6** (3 high, 3 medium) |

---

## Screenshots

| Path | Content |
|------|---------|
| `qa/MM-020-P0/screenshots/p0-overview.png` | LIVE + SOURCE UNAVAILABLE; IDLE nodes; Bug fixer in Radar; Agent-Mindmap header |
| `qa/MM-020-P0/screenshots/p0-rate-limit.png` | Refresh rate-limited countdown + Retry in status bar |
| `qa/MM-020-P0/screenshots/p0-disconnected.png` | After SSE abort — still no DISCONNECTED |
| `qa/MM-020-P0/screenshots/p0-disconnected-reprobe.png` | Reprobe after SSE kill — still SOURCE UNAVAILABLE only |
| `qa/MM-020-P0/screenshots/p0-after-drag.png` | After Director handle drag |
| `qa/MM-020-P0/screenshots/p0-unreachable.png` | Server stopped — "server unreachable" **and** DISCONNECTED (incidental) |
| `qa/MM-020-P0/screenshots/p0-final.png` | End-of-pass overview |

---

## Key proofs (passing)

### (1) partial — ledger missing honesty + non-empty graph

- `meta.ledger=unavailable`, `ledger_error="ledger not found at data/ledger"`, `github=ok` (not skipped)
- UI: `SOURCE UNAVAILABLE — ledger: unavailable — ledger not found at data/ledger`
- `/activity.json`: **12 events**, **3 edges** (all `message`); timeline shows PR/NOTE/MSG
- Nodes: **14× IDLE** (fail — F1)

### (3) refresh / rate limit / unreachable

- First POST `/refresh` → **202** `{"queued": true}`
- Burst → **429** `{"retry_after_s": 5}`; UI shows countdown; Retry disabled
- Server stopped → UI: `Refresh failed (server unreachable)`

### (6)(7)(8)

- Message edges trace to real recipients; fabricated=0
- `web_sources_newer_than_dist`: touch `web/src` → rebuild; fresh dist → no rebuild
- Host/Origin: bad Host **403**, `Origin: null` **403**, foreign **403**, same-origin **429** (allowed past gate), GET **404**, PUT **405**

### (9) partial

- Groups: `owner` + `build` + `qr` + `radar` (3 teams + Owner standalone)
- Message edges present; no UNKNOWN sender on known p0 network events
- Bug fixer **not** in `radar.members` config, but still `node.group=radar` and rendered inside Radar frame (F5)
- Drag moves via `.agent-node-drag-handle`; reload snaps back (F6)

---

## Findings (every finding this pass)

### F1 — Nodes default IDLE instead of UNKNOWN when ledger missing (HIGH)

| Field | Value |
|-------|-------|
| **id** | `P0-1-unknown-status` |
| **severity** | high |
| **expected** | With ledger missing, node status UNKNOWN (not fake IDLE) |
| **actual** | All 14 nodes `status=IDLE` in `/activity.json` and UI badges |
| **repro** | Start LIVE with no `data/ledger`; `GET /activity.json`; inspect `nodes[].status` and graph badges |
| **evidence** | `logs/.../activity_no_ledger.json`, `screenshots/p0-overview.png` |

### F2 — Appended network event not visible without reload (HIGH)

| Field | Value |
|-------|-------|
| **id** | `P0-2-live-event` |
| **severity** | high |
| **expected** | New network event (e.g. `p0-live-new`) appears in `/activity.json` / UI after append + refresh/SSE, no full reload |
| **actual** | After append to stub `events.jsonl` + POST `/refresh`, new id never appeared in activity ids |
| **repro** | Append line to stub events feed; POST `/refresh` (or wait for poll); `GET /activity.json` and search for new id |
| **evidence** | `logs/.../e2e_run.log` check `(2)`, `logs/.../live_events.jsonl` |

### F3 — Killing SSE does not show DISCONNECTED (HIGH)

| Field | Value |
|-------|-------|
| **id** | `P0-4-disconnected` |
| **severity** | high |
| **expected** | DISCONNECTED in the single MindmapStatusBar after SSE kill |
| **actual** | After `/events` abort, bar stays on SOURCE UNAVAILABLE only. DISCONNECTED **does** appear when the whole server is stopped (with "server unreachable") |
| **repro** | Open LIVE UI; abort `/events` in DevTools/Playwright; watch status bar ≥15s |
| **evidence** | `screenshots/p0-disconnected.png`, `p0-disconnected-reprobe.png`; contrast `p0-unreachable.png` |

### F4 — Fencepost repo tag and repo filter missing in UI (MEDIUM)

| Field | Value |
|-------|-------|
| **id** | `P0-5-repo-filter` |
| **severity** | medium |
| **expected** | Fencepost-attributed events show a repo tag; UI offers a repo filter |
| **actual** | Activity data has `repo=ManpreetS2/fencepost` on 9 events, but UI filters are only group/type/bot/task — no Fencepost chip/tag/heading |
| **repro** | LIVE with multi-repo stub GH events; inspect timeline filters and event chips |
| **evidence** | `screenshots/p0-overview.png`, e2e `bodyProbe.hasFencepost=false` |

### F5 — Bug fixer still rendered in Research / Radar (MEDIUM)

| Field | Value |
|-------|-------|
| **id** | `P0-9-bug-fixer-radar` |
| **severity** | medium |
| **expected** | Bug fixer not in Radar cluster (MM-020g leftover) |
| **actual** | `groups.json` radar.members omits `bug-fixer`, but `bots.json` still has `"group": "radar"`; activity node `group=radar`, `groups=[]`; UI draws Bug fixer inside RESEARCH / RADAR |
| **repro** | LIVE UI; inspect Radar frame membership |
| **evidence** | `screenshots/p0-overview.png`, `config/bots.json` note on bug-fixer |

### F6 — Dragged positions do not persist across reload (MEDIUM)

| Field | Value |
|-------|-------|
| **id** | `P0-9-drag-persist` |
| **severity** | medium |
| **expected** | Dragged node position persists after reload |
| **actual** | Director moved (`moved=true`); after reload coords snap back (`persisted=false`) |
| **repro** | Drag Director via `.agent-node-drag-handle`; reload; compare bounding box |
| **evidence** | `logs/.../drag.json`, `screenshots/p0-after-drag.png` |

---

## Non-findings / clarifications

- Header **Agent-Mindmap** is CSS `text-transform: capitalize` on meta `project=agent-mindmap` — meets “not Fencepost”; not filed as a defect.
- Single MindmapStatusBar count stayed **1** before/after SSE abort and while unreachable.
- CI web @ `4bcb907` reports 99 tests because that commit is backend-scoped; merged local + `e3d4db5` CI both show **126**.

---

## Deferred

| Item | Why |
|------|-----|
| macOS Dock / `open` / LaunchAgent | Linux agent host |
| Real `gh auth` against GitHub.com | stubbed for deterministic P0 |
| Re-verify after PR #30 tip `dbee348` | out of requested SHA scope |
