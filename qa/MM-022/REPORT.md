# QA Report — MM-022 / PR #22 (Mac startup, DevOps) @ `3119867`

**Verdict: FAIL** (3 medium, 2 low)  
**Head:** `3119867f461fcba59819544faec7d635a8c11d17` (`3119867`)  
**PR:** https://github.com/ManpreetS2/agent-mindmap/pull/22  
**Base:** `feat/MM-020-unified-network`  
**Head branch:** `cursor/mm020-mac-startup`  
**QA branch:** `qa/MM-022`  
**Fresh checkout:** `/tmp/qa-mm022/checkout`  
**Environment:** Linux 6.12.94+, Python 3.12.3, Node v22.23.3, shellcheck 0.9.0, xmllint

---

## Exact counts

| Check | Result |
|-------|--------|
| **shellcheck** `scripts/start-mac.sh` `scripts/install-launchagent.sh` | **exit 0** (clean) |
| **xmllint** `ops/com.manpreet.mindmap.plist` (+ rendered) | **exit 0** |
| **pytest** (clean) | **195 passed**, **2 skipped** |
| **vitest** | **81 passed** (18 files) |
| **typecheck** web | clean |
| **CI python** | **success** [39495331687](https://github.com/ManpreetS2/agent-mindmap/actions/runs/39495331687) @ `3119867` |
| **CI web** | **not triggered** (path filter: PR does not touch `web/**`) |

Behavioral script checks: see `logs/3119867…/behavioral.txt` — server start /healthz / UI / bind / port-busy / install idempotency all exercised on Linux with fixture ledger + mock `gh`.

---

## (1) Scripts — mostly PASS, with findings below

| Check | Result |
|-------|--------|
| `set -euo pipefail` on both scripts | PASS |
| Quoting / shellcheck | PASS (shellcheck exit 0) |
| `install-launchagent.sh` idempotent (run twice) | PASS (rc 0/0; overwrites plist) |
| Missing deps / bad ledger / gh auth fail → honest stderr + nonzero exit | PASS |
| Busy port → exit 1 + `lsof` detail | PASS |
| Second start while running → exit 1 | PASS |
| Bind via live daemon | PASS — `127.0.0.1:8787` only (no `0.0.0.0`) |
| Never runs `gh auth login` (only tells user to) | PASS |
| No secrets logged/hardcoded | PASS |
| No hardcoded user paths (`$HOME` / `REPO_ROOT` / placeholders) | PASS |
| Stop/cleanup (SIGTERM / Ctrl+C via `exec` python) | PASS — port freed |

---

## (2) launchd plist — PASS on Linux-validatable parts

| Check | Result |
|-------|--------|
| XML well-formed (`xmllint`) | PASS |
| After `sed` render: no `REPLACE_WITH_*` left | PASS |
| `Label` = `com.manpreet.mindmap` | PASS |
| `ProgramArguments` = `/bin/bash` + `…/scripts/start-mac.sh` | PASS |
| `WorkingDirectory` / log paths / `EnvironmentVariables` | PASS (see finding F4 on env) |
| `RunAtLoad` = true | PASS |
| `KeepAlive.SuccessfulExit` = false | PASS |
| **`plutil -lint`** | **DEFERRED** (macOS-only) |
| **`launchctl bootstrap` / `bootout`** | **DEFERRED** (owner Mac run) |

Evidence: `plist_xmllint.txt`, `plist_keys.json`

---

## (3) CI path filters

| Workflow | Paths relevant to this PR | Triggered @ `3119867`? |
|----------|---------------------------|------------------------|
| `python.yml` | Adds `scripts/**` + shellcheck step | **Yes** — success |
| `python.yml` | **`ops/**` not listed** | N/A for this SHA (scripts/tests also changed) |
| `web.yml` | `web/**`, `fixtures/**`, `shared/**` | **No** — correct (PR does not touch those) |

Finding **F1**: `ops/**` missing despite PR body claiming it was added.

---

## (4) Linux start as far as it can go — PASS (with good venv)

With a complete `.venv` (`pip install -e '.[dev]'`) + fixture ledger + mock `gh`:

| Check | Result |
|-------|--------|
| Server listens | PASS `127.0.0.1:8787` |
| `GET /healthz` | PASS 200; `errors: []`; `last_build` set |
| `GET /` UI | PASS 200 |
| `GET /activity.json` | PASS 200 |

Evidence: `healthz.json`, `ui.html`, `live_stderr.txt`, `behavioral_run.txt`

Incomplete-`.venv` case: see finding **F3**.

---

## (5) Docs (fresh Mac setup) — partial

New **“Run on a Mac (MM-020-OPS)”** section is accurate for: prerequisites, `./scripts/start-mac.sh`, `MINDMAP_LEDGER`, `--rebuild`, stop via Ctrl+C, `install-launchagent.sh` printing bootstrap/bootout.

Finding **F2**: older **Running live (MM-011)** macOS autostart steps still describe copying the plist and replacing placeholders so `ProgramArguments` use **`.venv/bin/python`** — that no longer matches `ops/com.manpreet.mindmap.plist` (now `/bin/bash` + `start-mac.sh`).

---

## (6) Regressions / CI

| Check | Result |
|-------|--------|
| Full pytest | **195 passed**, 2 skipped |
| Full vitest | **81 passed** |
| CI on head | python **success**; web not triggered (expected) |
| Real `gh` against GitHub | **DEFERRED** |

---

## Findings (this pass)

### F1 — `ops/**` omitted from `python.yml` path filters (MEDIUM)

| Field | Value |
|-------|-------|
| **component** | `.github/workflows/python.yml` |
| **expected** | PR body: path filters include `ops/**` and `scripts/**` so plist/script changes run shellcheck/pytest |
| **actual** | Diff adds only `scripts/**`. A PR that only changes `ops/com.manpreet.mindmap.plist` would **not** trigger python CI / shellcheck |
| **repro** | `git diff feat/MM-020-unified-network...3119867 -- .github/workflows/python.yml` — no `ops/**` line |
| **evidence** | `ci_path_filters.txt`, workflow file |
| **severity** | medium |
| **confidence** | high |

### F2 — README MM-011 launchd instructions stale vs new plist (MEDIUM)

| Field | Value |
|-------|-------|
| **component** | `README.md` (“Running live” macOS autostart) |
| **expected** | Docs match `ops/com.manpreet.mindmap.plist` + `install-launchagent.sh` |
| **actual** | Still says replace placeholders for **`.venv/bin/python` in `ProgramArguments`**; current plist invokes `/bin/bash` + `scripts/start-mac.sh`. Conflicts with the new “Run on a Mac” section |
| **repro** | Read README § Run on a Mac vs § Running live steps 3–5; compare to `ops/com.manpreet.mindmap.plist` |
| **evidence** | README excerpts; `plist_keys.json` |
| **severity** | medium |
| **confidence** | high |

### F3 — Existing `.venv` skips `pip install`; broken env still starts (MEDIUM)

| Field | Value |
|-------|-------|
| **component** | `scripts/start-mac.sh` `ensure_venv_python` |
| **expected** | Idempotent startup ensures deps are installed (or fails clearly before listen) |
| **actual** | If `.venv/bin/python` exists, script **never** runs `pip install -e '.[dev]'`. An empty/partial venv starts the daemon; `/healthz` can show `build failed: ModuleNotFoundError` and `/activity.json` → **404** while `/` still 200 |
| **repro** | `python3.12 -m venv .venv` (no pip install); `MINDMAP_LEDGER=… PATH=mockgh:$PATH ./scripts/start-mac.sh`; curl `/healthz` and `/activity.json` |
| **evidence** | `incomplete_venv.txt`, earlier `healthz` with ModuleNotFoundError |
| **severity** | medium |
| **confidence** | high |

### F4 — `MINDMAP_EVENTS_SOURCE` in plist is ignored (LOW)

| Field | Value |
|-------|-------|
| **component** | `ops/com.manpreet.mindmap.plist` + `ingest.live` |
| **expected** | Env var in plist either wired or omitted |
| **actual** | Plist sets `MINDMAP_EVENTS_SOURCE=gh`; `live.py` only takes `--events-source` (default `gh`) and never reads that env name. Harmless today (defaults match) but dead/misleading config |
| **repro** | `rg MINDMAP_EVENTS_SOURCE ingest/live.py` → no matches; plist has the key |
| **evidence** | `events_env_note.txt`, `plist_keys.json` |
| **severity** | low |
| **confidence** | high |

### F5 — Port preflight skipped if `lsof` missing (LOW)

| Field | Value |
|-------|-------|
| **component** | `scripts/start-mac.sh` `check_port_free` |
| **expected** | Busy-port failure is reliable on supported platforms |
| **actual** | If `lsof` is absent, the function returns without checking; conflict surfaces later as Python bind error (less clear). macOS usually has `lsof` |
| **repro** | Read `check_port_free`: only runs `lsof` inside `command -v lsof` |
| **evidence** | `scripts/start-mac.sh`; `behavioral.txt` INFO line |
| **severity** | low |
| **confidence** | high |

---

## Deferred (not FAIL)

| Item | Why deferred |
|------|----------------|
| `plutil -lint` on rendered LaunchAgent | macOS-only binary; Linux used `xmllint` instead |
| `launchctl bootstrap` / `bootout` load/unload | Requires owner Mac + gui session |
| Real `gh auth status` + live GitHub API (no mock) | Needs owner credentials / network policy; fixture mock used on Linux |
| End-to-end launchd KeepAlive restart behavior | Depends on launchctl |

---

## Verdict rationale

Core Linux path works: shellcheck clean, plist XML valid, bind `127.0.0.1:8787`, `/healthz` + UI + `/activity.json` with a proper venv, pytest **195**/vitest **81**, CI python green. **FAIL** because of three medium issues: CI omits `ops/**`, README still documents the old launchd Python invocation, and `start-mac.sh` will start against an incomplete `.venv` without reinstalling deps (broken activity build).

---

## Notes

- Verify-only: no product edits; no PR comments; no merge; evidence only on `qa/MM-022`.
- Harness: `scripts/qa_mm022_behavioral.sh`
- Log dir: `logs/3119867f461fcba59819544faec7d635a8c11d17/`
