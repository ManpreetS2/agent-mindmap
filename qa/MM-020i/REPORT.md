# QA Report — MM-020i / PR #24 (DEMO mode, DEV 1) @ `06e5bda`

**Verdict: FAIL** (1 high, 4 medium, 1 low)  
**Head:** `06e5bdaf4efeb7db0d958d59a730b88c9f467e86` (`06e5bda`)  
**PR:** https://github.com/ManpreetS2/agent-mindmap/pull/24  
**Base:** `feat/MM-020-unified-network` @ `be2f241` (#23 merged)  
**Head branch:** `feat/MM-020i`  
**QA branch:** `qa/MM-020i`  
**Fresh checkout:** `/tmp/qa-mm020i/checkout` @ `06e5bda`  
**Environment:** Linux 6.12.94+, Python 3.12.3, Node (web tooling), Playwright Chromium

Verify-only: no product edits; no PR comments; no merge. Evidence only on this branch.

---

## Exact counts

| Check | Result |
|-------|--------|
| **pytest** (clean @ `06e5bda`) | **218 passed**, **1 skipped** |
| **vitest** (`web/`) | **94 passed** (20 files) |
| **typecheck** web | clean (`tsc --noEmit`) |
| **build** web | clean (`vite build`) |
| **CI python** @ head | **success** [39498335791](https://github.com/ManpreetS2/agent-mindmap/actions/runs/39498335791) |
| **CI web** @ head | **success** [39498335538](https://github.com/ManpreetS2/agent-mindmap/actions/runs/39498335538) |
| Behavioral harness checks | **22 PASS / 5 FAIL** → **6 findings** |
| Browser screenshots | DEMO + LIVE captured (see below) |

Self-test on PR (original comment @ `56d83b5`: 215 pytest / 91 vitest; rebase comment @ `06e5bda`: 218 / 94) — **independently confirmed** 218 / 94 on this head. Self-test did **not** cover banner always-visible / default-LIVE fakery, or live serving stale `meta.mode=demo` when rebuild fails.

---

## (1) `--demo` SSE `/events` + Last-Event-ID + poll fallback — PASS

| Check | Result |
|-------|--------|
| `/healthz` → `mode=demo` | PASS |
| SSE order `demo-evt-1` … `demo-evt-3` | PASS |
| SSE payloads include `mode=demo` | PASS |
| `Last-Event-ID: demo-evt-1` → starts at `demo-evt-2` | PASS |
| Poll fallback `GET /activity.json` → `meta.mode=demo`, `meta.ledger=demo` | PASS |
| Malformed JSONL lines skipped; valid kept | PASS (independent) |
| Missing `sample-activity.json` → `DemoFixtureError` | PASS |
| Empty events file / missing jsonl → demo still starts, 0 events | PASS (unit + edge) |

Evidence: `logs/06e5bda…/demo_sse.json`, `behavioral_run.log`, `pytest_demo.log`

---

## (2) LIVE/DEMO header bar — PARTIAL (screenshots PASS; contract FAIL)

Browser (Playwright Chromium) against real servers:

| Mode | Banner text | `data-mode` | Screenshot |
|------|-------------|-------------|------------|
| DEMO | `DEMO MODE — fixture data only` | `demo` | `screenshots/mode-banner-demo.png` |
| LIVE | `LIVE MODE — ingested data` | `live` | `screenshots/mode-banner-live.png` |

When `/healthz` succeeds, the bar is full-width, top-of-viewport, and unmistakable (amber DEMO vs green LIVE).

Contract failures (see findings F2–F4):

- Banner is **not** always visible: `App.tsx` renders `null` while `serverMode === null` (before fetch / on fetch failure).
- `useServerMode` maps any non-`"demo"` value (including missing `mode`) to **`"live"`** → can fake LIVE.
- One-shot `/healthz` fetch only — no retry; a failed first fetch leaves the bar hidden forever.

---

## (3) DEMO/LIVE never mix — PARTIAL (demo isolation PASS; live stale FAIL)

### Demo isolation — PASS

| Check | Result |
|-------|--------|
| Boom / tracking `gh` runner never called | PASS (`calls=[]`) |
| Poison ledger path never `read_bytes` | PASS |
| Stale live `activity.json` on disk ignored after `bootstrap_demo` | PASS |
| `/healthz` and activity `meta.mode=demo` | PASS |
| Demo does not write `--activity-out` | PASS |

### Live isolation — PASS on clean start; FAIL on stale demo file

| Check | Result |
|-------|--------|
| Clean live: no `demo-evt-*`, `meta.mode != demo`, `/healthz mode=live` | PASS |
| Happy-path CLI: `_load_activity_from_disk` then `run_poll_cycle` before listen overwrites stale demo snapshot when ledger OK | PASS (rebuild) |
| **Stale `meta.mode=demo` on disk + failed ledger rebuild** → healthz=`live` but `/activity.json` still `meta.mode=demo` / `ledger=demo` | **FAIL → F1 (high)** |
| Pre-poll load of demo bytes serves `mode=demo` under live healthz | FAIL → F1b (medium; CLI happy path remediates via rebuild) |

### Mode reporting

| Check | Result |
|-------|--------|
| `/healthz` reports `mode` in demo and live | PASS |
| SSE `data:` includes `mode` in demo | PASS |

Evidence: `logs/06e5bda…/no_mix.json`

---

## (4) `make refresh-demo` — PASS

| Check | Result |
|-------|--------|
| CLI `--activity-out` nested path only | PASS (sentinel live path untouched) |
| `make refresh-demo ACTIVITY_OUT=…` | PASS |
| Does not clobber unrelated live output | PASS |

Evidence: `logs/06e5bda…/refresh_demo.json`

---

## (5) `start-mac.sh --demo` on Linux — PASS (macOS DEFERRED)

| Check | Result |
|-------|--------|
| `./scripts/start-mac.sh --demo` → `/healthz` `mode=demo` on `:8787` | PASS |
| `GET /` UI 200 | PASS |
| Bind reachable at `127.0.0.1:8787` (`BIND_HOST=127.0.0.1`) | PASS |
| `plutil` / `launchctl` / macOS `open` / Keychain | **DEFERRED** (macOS-only) |

Evidence: `logs/06e5bda…/start_mac_demo.json`, `bind_host.txt`

---

## (6) Edge cases

| Case | Result |
|------|--------|
| Missing `sample-activity.json` | PASS — `DemoFixtureError` |
| Malformed JSONL | PASS — skipped; valid kept |
| Symlink `--activity-out` | PASS — exit 2, refuse |
| `--demo` + `--events-source gh` | Accepted; stays `mode=demo`, polls suppressed → **F5 (low)** |
| Port in use | PASS — nonzero exit, `Address already in use` |

Evidence: `logs/06e5bda…/edges.json`

---

## (7) Regressions 020a–020f / #23 + suites / CI — PASS

| Check | Result |
|-------|--------|
| Full pytest includes demo + prior live/SSE/UI coverage | **218 passed**, 1 skipped |
| Full vitest includes ModeBanner + MM-020f edge/group tests | **94 passed** |
| typecheck / build | clean |
| CI on `06e5bda` | python + web both **success** |
| Base ancestry `be2f241` ⊂ `06e5bda` | confirmed |

No regression signal vs #23 / 020a–020f in this pass.

---

## Findings (this pass) — 6 total

### F1 — Live serves stale `meta.mode=demo` when rebuild fails (HIGH)

| Field | Value |
|-------|-------|
| **id** | `LIVE-stale-demo-activity-meta` |
| **component** | `LiveDaemon._load_activity_from_disk` + `_maybe_rebuild` |
| **expected** | Live mode never serves activity with `meta.mode=demo` (strip/reject/rebuild-or-fail-closed) |
| **actual** | If `activity-out` contains bytes from `load_demo_activity_bytes()` (or any `meta.mode=demo` snapshot) and ledger rebuild fails (`ledger is None` → `_maybe_rebuild` returns False), `/healthz` reports `mode=live` while `/activity.json` still has `meta.mode=demo`, `ledger=demo` |
| **repro** | Write `load_demo_activity_bytes()` to `activity.json`; start live with missing ledger path; `GET /healthz` then `GET /activity.json` |
| **evidence** | `logs/…/no_mix.json`, `behavioral_run.log` |
| **severity** | high |
| **confidence** | high |

### F1b — Pre-poll load serves demo meta under live healthz (MEDIUM)

| Field | Value |
|-------|-------|
| **id** | `LIVE-stale-demo-activity-meta-prepoll` |
| **component** | `_load_activity_from_disk` |
| **expected** | Live must not expose `meta.mode=demo` even before first rebuild |
| **actual** | After `_load_activity_from_disk()` only: healthz=`live`, activity `meta.mode=demo`. Normal `main()` runs `run_poll_cycle()` before listen (happy path remediates when ledger OK); still shows the load path does not sanitize mode |
| **repro** | Same stale file; call `_load_activity_from_disk()`; serve; `GET /activity.json` before `run_poll_cycle` |
| **evidence** | `logs/…/no_mix.json` |
| **severity** | medium |
| **confidence** | high |

### F2 — Mode banner not always visible (MEDIUM)

| Field | Value |
|-------|-------|
| **id** | `BANNER-not-always-visible` |
| **component** | `web/src/App.tsx` |
| **expected** | LIVE/DEMO bar always visible |
| **actual** | `const banner = serverMode ? <ModeBanner …/> : null` — hidden until `/healthz` resolves; stays hidden if fetch fails |
| **repro** | Read `App.tsx`; or block `/healthz` and load UI |
| **evidence** | `logs/…/banner_contract.json`; source |
| **severity** | medium |
| **confidence** | high |

### F3 — Missing/unknown mode faked as LIVE (MEDIUM)

| Field | Value |
|-------|-------|
| **id** | `BANNER-default-live` |
| **component** | `web/src/hooks/useServerMode.ts` |
| **expected** | Unknown/missing mode must not be presented as LIVE |
| **actual** | `body.mode === "demo" ? "demo" : "live"` — any non-demo (including omitted `mode`) becomes LIVE |
| **repro** | Serve `/healthz` JSON without `mode`; UI shows `LIVE MODE — ingested data` |
| **evidence** | `logs/…/banner_contract.json`; hook source |
| **severity** | medium |
| **confidence** | high |

### F4 — Banner `/healthz` fetched once; no retry (MEDIUM)

| Field | Value |
|-------|-------|
| **id** | `BANNER-no-refetch` |
| **component** | `useServerMode` |
| **expected** | Banner stays correct / recovers (retry or subscribe to mode) |
| **actual** | Single fetch on mount; no interval, no retry on failure — failed first fetch → permanent hidden banner; SSE already carries `mode` but UI ignores it |
| **repro** | Read `useServerMode.ts`; fail `/healthz` once on load |
| **evidence** | `logs/…/banner_contract.json` |
| **severity** | medium |
| **confidence** | high |

### F5 — `--demo` + `--events-source` accepted without reject/warn (LOW)

| Field | Value |
|-------|-------|
| **id** | `DEMO-flag-combo` |
| **component** | CLI `ingest.live` |
| **expected** | Reject conflicting flags **or** document ignore; must not enable live events ingest |
| **actual** | Combination accepted; server runs `mode=demo` (polling suppressed by `demo_mode`) — safe but silent |
| **repro** | `python -m ingest.live --demo --events-source gh --port …` |
| **evidence** | `logs/…/edges.json` |
| **severity** | low |
| **confidence** | high |

---

## Deferred (not FAIL)

| Item | Why deferred |
|------|----------------|
| `plutil -lint` / `launchctl bootstrap` | macOS-only |
| macOS GUI `open` / Dock / Keychain | macOS-only |
| Owner-machine LaunchAgent KeepAlive with `--demo` | Needs Mac |

---

## Verdict rationale

Core DEMO path works: fixture SSE order + Last-Event-ID, poll `/activity.json`, `/healthz` mode, demo never touches gh/ledger, `make refresh-demo` isolation, `start-mac.sh --demo` on Linux binds `127.0.0.1:8787` in DEMO, suites **218** / **94**, typecheck/build clean, CI green on head. **FAIL** because live can still serve a stale demo activity snapshot (`meta.mode=demo`) when rebuild fails while advertising LIVE (high), and the mode banner is not always visible / can be faked as LIVE / does not retry (three mediums), plus a low flag-combo nit.

---

## Notes

- Harness: `qa/MM-020i/scripts/qa_mm020i_behavioral.py`, `qa_mm020i_screenshots.py`
- Log dir: `qa/MM-020i/logs/06e5bdaf4efeb7db0d958d59a730b88c9f467e86/`
- Screenshots: `qa/MM-020i/screenshots/mode-banner-{demo,live}.png`
