# QA Report — MM-020g E2E proof @ `56d348f`

**Verdict: FAIL** (1 high, 3 medium, 1 low)  
**Head:** `56d348f25b5295d641b338fce6c0648e2f06bb7d` (`56d348f`) — tip of `feat/MM-020-unified-network` (includes MM-020i #24)  
**PR / criteria source:** [PR #16](https://github.com/ManpreetS2/agent-mindmap/pull/16) + [`docs/MM-020-audit.md` §8](https://github.com/ManpreetS2/agent-mindmap/blob/56d348f25b5295d641b338fce6c0648e2f06bb7d/docs/MM-020-audit.md) (MM-020g = “All §8 cases green”)  
**This pass checklist:** owner E2E items (1)–(7) via real `./scripts/start-mac.sh` LIVE + `--demo`  
**QA branch:** `qa/MM-020g`  
**Fresh checkout:** `/tmp/qa-mm020g/checkout`  
**Environment:** Linux 6.12 (macOS-only steps **DEFERRED**); stub `gh` = `tests/fixtures/gh_mock_cli.py`

Verify-only: no product edits; no PR opened; no PR comments; no merge.

---

## Acceptance criteria tested

### From audit §8.1 Happy path

| # | Criterion | LIVE | DEMO |
|---|-----------|------|------|
| 1 | Groups with shared membership | **4 groups** (Owner+Build+Q&R+Radar) — see F1 | same config; DEMO layout incomplete — F2 |
| 2 | Director **one** node, multi-group | **PASS** (1 node, `groups=[build,qr,radar]`) | **FAIL** — F2 |
| 3 | Bot-to-bot **message** edge + `agent-reported` | **FAIL** — F4 (0 message edges) | **FAIL** — F4 |
| 4 | Cross-group handoff visible | **PASS** (`architect→qa-verifier` handoff) | same-group handoff only in fixture |
| 5 | UI SSE; animate only real ids | SSE delivers; vitest covers animation gating | SSE `demo-evt-1..3` ordered |

### From audit §8.2 Automated (CI + local)

| Case | Result |
|------|--------|
| Reconnect / Last-Event-ID | **PASS** (pytest + DEMO curl replay) |
| Duplicates by id | **PASS** (pytest SSE dedupe / PR lane tests) |
| Missing attribution → UNKNOWN | **PASS** (`test_activity_event_to_network_unknown_sender`) |
| Simultaneous writers | **PASS** (`test_concurrent_append_no_lost_lines`) |
| Unconfigured rooms | **PASS** (`test_unknown_group_passthrough_no_throw`) |
| SEC-MM011-1 Host/Origin | **PASS** (pytest + E2E forged Host → 403 on `/activity.json` + `/events`) |

### Owner checklist (1)–(7)

| # | Item | Result |
|---|------|--------|
| 1 | start-mac LIVE + DEMO; UI + banner | **PASS** both (`--demo` no longer exits 2) |
| 2 | Exactly 3 groups; Director/Architect once | Groups **FAIL** F1; identity unique **PASS** both modes |
| 3 | Select, drag, detail; drag persists | Select/detail **PASS**; drag moves via handle **PASS**; **persist FAIL** F3 |
| 4 | Live updates / SSE order / Last-Event-ID / poll fallback | **PASS** (API + browser SSE abort stays up; vitest SSE→poll→SSE) |
| 5 | Timeline, filters, sources | **PASS** |
| 6 | No fabricated / no LIVE↔DEMO mix | **PASS** isolation; DEMO fixture gaps under F2 |
| 7 | Honest errors (gh auth, ledger missing, port busy) | **PASS** |

---

## Exact counts

| Check | Result |
|-------|--------|
| `./scripts/start-mac.sh` LIVE | **PASS** — `mode=live` on `127.0.0.1:8787` |
| `./scripts/start-mac.sh --demo` | **PASS** — `mode=demo` (exit 2 regression cleared) |
| E2E harness checks | **32 PASS / 5 FAIL / 6 INFO** (pre-consolidation; see findings) |
| **pytest** | **239 passed**, **2 skipped** |
| **vitest** | **99 passed** (21 files) |
| **typecheck** | clean |
| **build** | clean |
| **CI python** @ head | **success** — 239 passed, 2 skipped ([39502219008](https://github.com/ManpreetS2/agent-mindmap/actions/runs/39502219008)) |
| **CI web** @ head | **success** — 99 passed ([39502219022](https://github.com/ManpreetS2/agent-mindmap/actions/runs/39502219022)) |
| Findings this pass | **5** (1 high, 3 medium, 1 low) |

---

## Screenshots

| Path | Content |
|------|---------|
| `qa/MM-020g/screenshots/mode-demo-overview.png` | DEMO banner + graph |
| `qa/MM-020g/screenshots/mode-demo-detail.png` | DEMO detail panel |
| `qa/MM-020g/screenshots/mode-demo-timeline.png` | DEMO timeline/filters |
| `qa/MM-020g/screenshots/mode-demo-drag-handle.png` | DEMO after successful handle-drag |
| `qa/MM-020g/screenshots/mode-live-overview.png` | LIVE banner + **4** group frames |
| `qa/MM-020g/screenshots/mode-live-detail.png` | LIVE detail panel |
| `qa/MM-020g/screenshots/mode-live-timeline.png` | LIVE timeline/filters |

---

## Mode proofs (summary)

### DEMO (`./scripts/start-mac.sh --demo`)

- `/healthz` `mode=demo`; banner `DEMO MODE — fixture data only`
- SSE order `demo-evt-1..3`; Last-Event-ID resume; SEC Host forgery → 403
- `meta.mode=demo`, `ledger=demo`, github skipped; no live mix
- Director/Architect once in DOM; **multi-group missing** (F2)
- Source line: `Source: ledger + GitHub (skipped)` + honest GitHub-skipped banner

### LIVE (`./scripts/start-mac.sh` + stub `gh` + `MINDMAP_LEDGER=tests/fixtures/ledger-sample.md`)

- `/healthz` `mode=live`; banner `LIVE MODE — ingested data`
- Activity `meta.mode=live`, github/ledger ok; no `demo-evt-*`
- Director/Architect once with `groups=[build,qr,radar]`; cross-group handoff present
- Source: `Source: ledger + GitHub (ok)`
- Negatives: port busy / missing ledger / gh unauthenticated → nonzero + clear stderr (**PASS**)

### Deferred (macOS-only)

| Item | Why |
|------|-----|
| `plutil` / `launchctl bootstrap` / LaunchAgent KeepAlive | macOS-only |
| Real `gh auth` against GitHub.com (no stub) | needs owner credentials |
| Dock / `open` browser integration | macOS-only |

---

## Findings (every finding this pass)

### F1 — Exactly-3-groups checklist unmet; UI shows 4 (MEDIUM)

| Field | Value |
|-------|-------|
| **id** | `QA-MM020g-1-groups-count` |
| **severity** | medium |
| **expected** | Exactly 3 groups render (this pass); audit §8.1 still says 2 |
| **actual** | `config/groups.json` defines **4**: `owner`, `build`, `qr`, `radar`. LIVE UI shows four labeled clusters; filters list Owner + Build + Quality & Release + Research / Radar |
| **repro** | `./scripts/start-mac.sh`; open `http://127.0.0.1:8787/`; count group frames / filter chips |
| **evidence** | `screenshots/mode-live-overview.png`, `logs/…/groups_observation.json` |

### F2 — DEMO lacks multi-group Director/Architect (§8.1 #2) (HIGH)

| Field | Value |
|-------|-------|
| **id** | `QA-MM020g-2-demo-multigroup` |
| **severity** | high |
| **expected** | Director one node belonging to Build+Q&R(+Radar); membership visible |
| **actual** | DEMO `/activity.json` is `schema_version` **1.0.0** with `director.groups` / `architect.groups` **null**; UI parks both only in **BUILD**; no membership links. LIVE is correct. `load_demo_activity_bytes` does not apply `membership_index` |
| **repro** | `./scripts/start-mac.sh --demo`; `GET /activity.json` → inspect nodes; compare DEMO vs LIVE screenshots |
| **evidence** | `logs/…/activity_demo.json`, `screenshots/mode-demo-overview.png` |

### F3 — Drag position does not persist across reload (MEDIUM)

| Field | Value |
|-------|-------|
| **id** | `QA-MM020g-3-drag-persist` |
| **severity** | medium |
| **expected** | Drag moves node and position persists |
| **actual** | Drag via `.agent-node-drag-handle` moves (dx≈144). Full reload restores layout defaults (session-only `draggedIdsRef`, no durable store) |
| **repro** | DEMO; drag Director by handle; reload; compare bounding box |
| **evidence** | `logs/…/drag_handle.json`, `screenshots/mode-demo-drag-handle.png` |

### F4 — §8.1 bot-to-bot message edge missing in E2E data (MEDIUM)

| Field | Value |
|-------|-------|
| **id** | `QA-MM020g-4-message-edge` |
| **severity** | medium |
| **expected** | One message edge sender→recipient with `provenance: agent-reported` |
| **actual** | 0 `type=message` edges/events in DEMO and LIVE activity from start-mac + ledger fixture + gh mock |
| **repro** | start-mac LIVE; `GET /activity.json`; filter `type==message` |
| **evidence** | `logs/…/activity_live.json`, `activity_demo.json` |

### F5 — Bug fixer still rendered in Research/Radar cluster (LOW)

| Field | Value |
|-------|-------|
| **id** | `QA-MM020g-5-bug-fixer-in-radar` |
| **severity** | low |
| **expected** | MM-020a: Bug fixer out of Research unless added to `groups.json` members |
| **actual** | `bug-fixer.group=radar` so LIVE places the node inside Research / Radar frame while `radar.members` omits it |
| **repro** | LIVE UI; locate Bug fixer vs `config/groups.json` `radar.members` |
| **evidence** | `screenshots/mode-live-overview.png` |

---

## Verdict rationale

Core LIVE path and `start-mac` both modes work: banners correct, unique Director/Architect, SSE + Last-Event-ID + SEC Host checks, poll fallback survivability, timeline/filters/sources, honest negatives, suites **239** / **99**, CI green. **FAIL** because DEMO does not deliver §8.1 multi-group identity (high), the pass’s “exactly 3 groups” bar is unmet (4 render), drag does not persist across reload, and the §8.1 message-edge happy path is absent from the E2E fixtures/data.

---

## Notes

- Harness: `qa/MM-020g/scripts/e2e_mm020g.py`
- Logs: `qa/MM-020g/logs/56d348f25b5295d641b338fce6c0648e2f06bb7d/`
- Stub gh on `PATH` for LIVE; DEMO skips `require_gh_auth`
