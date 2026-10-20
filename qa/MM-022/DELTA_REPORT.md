# Delta QA — MM-022 / PR #22 (Mac startup) @ 752207d

| Field | Value |
|-------|-------|
| **Verdict** | **PASS** |
| **Head** | `752207d97486f019b7b01366e9f71ca31b48842a` |
| **Prior FAIL** | `3119867` |
| **Rebased on** | `be2f241` (MM-020e2) |
| **PR** | https://github.com/ManpreetS2/agent-mindmap/pull/22 |
| **Evidence** | `qa/MM-022/DELTA_REPORT.md` |
| **Mode** | verify-only |

## Isolation (rebase noise)

`git log 3119867..752207d` includes unrelated base merges (`be2f241`, `b2baf35`, …).

**DevOps fix commits only** (`1e8e56f..752207d`):

| SHA | Subject |
|-----|---------|
| `fc74ddc` | MM-020-OPS: address QA-MM-022 and SEC-MM020OPS review findings |
| `752207d` | MM-020-OPS: isolate `--demo` stub for MM-020i / PR #24 rebase |

Fix touch list (7 files): `python.yml`, `README.md`, `ops/…plist`, `start-mac.sh`, `install-launchagent.sh`, `render_launchagent_plist.py`, `tests/test_start_mac.py`.

## Verdict

**PASS.** Prior QA-MM022-1…5 and SEC-MM020OPS-1 (+ Security’s 2 LOWs) all reproduce as fixed. **Findings: 0.**  
`plutil` / `launchctl`: **OPEN/DEFERRED** (macOS-only).

## Fix confirmations

| ID | Result | Repro |
|----|--------|-------|
| **QA-MM022-1** | **PASS** | `.github/workflows/python.yml` has `"ops/**"` on push + pull_request (`count >= 2`). |
| **QA-MM022-2** | **PASS** | Plist `ProgramArguments` = `/bin/bash` + `…/scripts/start-mac.sh`. README “Run on a Mac” states the same; MM-011 section redirects (no stale `.venv/bin/python` ProgramArguments). Rendered plist confirms. |
| **QA-MM022-3** | **PASS** | Empty venv fails `venv_health_ok` → recreate + `--require-hashes` install + post-check; never reaches broken listen. `test_broken_venv_triggers_reinstall` **PASS** (imports `ingest, jsonschema` after start). |
| **QA-MM022-4** | **PASS** | `resolve_events_source` reads `MINDMAP_EVENTS_SOURCE` (`gh`\|`off`) → `--events-source` on `ingest.live`. |
| **QA-MM022-5** | **PASS** | Without `lsof`, Python bind probe still detects busy port → exit 1 + clear stderr. `test_busy_port_without_lsof` **PASS**. |
| **SEC-MM020OPS-1** | **PASS** | `install_venv_deps`: `pip install --require-hashes -r requirements-dev.txt` then `--no-deps -e .`. |
| **Security LOW: ThrottleInterval** | **PASS** | Plist `ThrottleInterval` = 30. |
| **Security LOW: pinned shellcheck** | **PASS** | CI downloads shellcheck 0.9.0 and `sha256sum -c` before run. |

## Deferred (unchanged)

| Item | Status |
|------|--------|
| `plutil -lint` | **OPEN/DEFERRED** (macOS-only; Linux: `xmllint` + `plistlib`) |
| `launchctl bootstrap` / `bootout` | **OPEN/DEFERRED** (owner Mac) |

## New issues in fix diff

None.

## Counts

| Check | Result |
|-------|--------|
| shellcheck (`start-mac.sh`, `install-launchagent.sh`) | **exit 0** |
| xmllint (template + rendered) | **exit 0** |
| pytest @ `752207d` | **222 passed, 2 skipped** |
| vitest | **92 passed** (19 files) |
| CI python on head | **success** — https://github.com/ManpreetS2/agent-mindmap/actions/runs/39498706444 (CI log: `222 passed, 2 skipped`) |
| CI web | not triggered (no `web/**` in PR paths) — expected |
| Focused start-mac / filter / hash / events / port tests | **5/5 PASS** |

## Closed vs FAIL @ 3119867

| Prior | Status |
|-------|--------|
| F1 `ops/**` missing | **CLOSED** (QA-MM022-1) |
| F2 README stale launchd | **CLOSED** (QA-MM022-2) |
| F3 incomplete venv starts broken | **CLOSED** (QA-MM022-3) |
| F4 `MINDMAP_EVENTS_SOURCE` ignored | **CLOSED** (QA-MM022-4) |
| F5 port check skips without lsof | **CLOSED** (QA-MM022-5) |
