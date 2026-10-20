# QA Report — MM-011 / PR #15

| Field | Value |
|-------|-------|
| **Verdict** | **PASS** |
| **Target SHA** | `0fa142f1a1ccbfa7f861a9bf0ecbdb0539baaa11` |
| **Baseline (superseded)** | `aaeef2bfd42b7ef0409e41c1e78b8245d239f6a5` |
| **PR** | https://github.com/ManpreetS2/agent-mindmap/pull/15 |
| **Environment** | Linux 6.12 (Cloud Agent VM); Python 3.12.3; Node via nvm; `gh` mocked for daemon loop |
| **Evidence branch** | `qa/MM-011` |
| **Date** | 2026-10-20 |

Head moved from `aaeef2b` → `0fa142f` during verification. All checks below were re-run on **`0fa142f`**. `aaeef2b` results are baseline only (see `baseline-aaeef2b/`).

---

## Verdict summary

Platform-neutral acceptance for MM-011 is met on `0fa142f`. DevOps blocking item **DEVOPS-MM011-1** and the two LOWs in comment [6286253644](https://github.com/ManpreetS2/agent-mindmap/pull/15#issuecomment-6286253644) are addressed. **SEC-MM011-1** (Host allowlist / DNS rebinding) is **observed** and deferred to **MM-020** (does not block this PR).

---

## Checks

| Check | Result | Notes |
|-------|--------|-------|
| `python3 -m pytest -q` | PASS | **97 passed, 1 skipped** (`plutil` macOS-only) |
| `cd web && npm test` (vitest) | PASS | 40 passed |
| `npm run typecheck` (root + web) | PASS | |
| `cd web && npm run build` | PASS | |
| Daemon unit tests (`tests/test_live.py`) | PASS | includes version gate + plist venv assertions |
| Daemon loop: schedule refresh | PASS | ledger edit → rebuild within poll interval (2s) |
| Daemon loop: idempotent | PASS | unchanged inputs → no rewrite |
| SIGTERM / SIGINT clean shutdown | PASS | exit 0, no orphans, port released |
| Orphan processes | PASS | none |
| Same-port second instance | PASS | `OSError: Address already in use` |
| Singleton lock (diff ports) | FINDING (LOW) | two instances can run on different ports; no pidfile/flock |
| `gh` down / network fail | PASS | keeps serving last-good; errors in `/healthz`; no tight loop |
| Rate-limit backoff | PASS | `RATE_LIMIT=1` → skip polls; 1 gh call then backoff messages |
| Logs contain no tokens | PASS | fail path with `Authorization: Bearer …` in gh stderr → not in daemon log |
| Writes only intended paths | PASS | `activity-out` + `--cache-dir` only |
| File permissions | PASS | activity `0600`; cache files not world-writable |
| Listener `127.0.0.1` only | PASS | `/proc/net/tcp` shows `127.0.0.1`; non-loopback connect refused |
| Methods other than GET/HEAD | PASS | POST/PUT/DELETE → **405**; PATCH → **501** (stdlib unimplemented); HEAD → 200 empty body |
| Path traversal | PASS | `../`, `%2e%2e`, `..%2f` → 400/404; no `/etc/passwd` leak |
| SEC-MM011-1 Host allowlist | OBSERVED (non-blocking) | `Host: evil.example` → **200** with body; scoped to MM-020 |
| DEVOPS-MM011-1 venv python | PASS | plist uses `…/.venv/bin/python`; not `/usr/bin/python3` |
| Python &lt;3.12 fail-fast | PASS | real **3.11.17** interpreter: exit 1 + clear stderr |
| Installer / README venv ≥3.12 | PASS | README: `python3.12 -m venv .venv`; simulated venv is 3.12.3 |
| DEVOPS-MM011-2 (LOW) | PASS | log path placeholders + README `mkdir -p` |
| DEVOPS-MM011-3 (LOW) | PASS | `KeepAlive`/`SuccessfulExit=false`; `bootstrap`/`bootout` |
| Ledger mirror secret-block on daemon flush | N/A / note | daemon has **no** flush path; `tools/ledger_mirror.py` still blocks secrets |

---

## DEVOPS-MM011-1 (fix verification)

**Expected:** plist runs repo `.venv/bin/python` (absolute after placeholder replace), not `/usr/bin/python3`; startup fails fast below 3.12.

**Actual:**

- `ops/com.manpreet.mindmap.plist` ProgramArguments: `REPLACE_WITH_AGENT_MINDMAP_REPO_ROOT/.venv/bin/python` (no `/usr/bin/python3`).
- README install step: `python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"` (creates the interpreter the plist points at once placeholders are filled with an absolute repo root).
- There is **no** separate install script binary — the documented README steps are the installer.
- Real Python **3.11.17** (`uv`-installed):

```
$ python3.11 -m ingest.live …
exit 1
stderr: mindmap live requires Python 3.12+ (interpreter reports 3.11); use REPLACE_WITH_AGENT_MINDMAP_REPO_ROOT/.venv/bin/python (pip install -e '.[dev]' in the repo venv)
```

Evidence: `python311_failfast.txt`, `venv_create.txt`, `devops_lows.txt`, `ops` copy via sha checkout.

---

## Comment 6286253644 — two LOWs

| ID | Expected (from DevOps) | Actual on `0fa142f` | Status |
|----|------------------------|---------------------|--------|
| **DEVOPS-MM011-2** | Log paths as placeholders; README `mkdir -p` for log dir | `REPLACE_WITH_ABSOLUTE_LOG_DIR/...`; no `/Users/manpreet/`; README step 2 `mkdir -p ~/Library/Logs/mindmap` | **Confirmed fixed** |
| **DEVOPS-MM011-3** | Prefer `launchctl bootstrap`; gentler KeepAlive | README `bootstrap` + `bootout`; plist `KeepAlive` → `{SuccessfulExit: false}` | **Confirmed fixed** |

---

## SEC-MM011-1 (observation only — MM-020)

| Field | Value |
|-------|-------|
| Component | `ingest/live.py` `MindmapHandler` |
| Expected (secure) | Reject foreign `Host` (e.g. 400/403/421) or otherwise not serve app content |
| Actual | `GET /healthz` and `/activity.json` with `Host: evil.example` → **HTTP 200** + JSON body |
| Repro | Start daemon on 127.0.0.1:PORT; `printf 'GET /healthz HTTP/1.1\r\nHost: evil.example\r\nConnection: close\r\n\r\n' \| nc 127.0.0.1 PORT` |
| Evidence | `bind_evidence.txt`, `host_evil_response.txt` |
| Environment | Linux VM, loopback only |
| Severity | LOW (Security triage); **does not block MM-011** |
| Confidence | High |

DNS rebinding requires the victim browser to resolve `evil.example` to 127.0.0.1 while the daemon is listening; bind is still loopback-only.

---

## Findings

### F1 — SEC-MM011-1 no Host allowlist (non-blocking)

- **Component:** HTTP handler  
- **Expected:** Host allowlist / reject foreign Host  
- **Actual:** Serves 200 for `Host: evil.example`  
- **Repro / evidence / env / severity / confidence:** see SEC-MM011-1 table above  
- **Disposition:** MM-020; not a MM-011 merge blocker

### F2 — No process singleton lock beyond port bind (LOW)

- **Component:** `ingest.live` process model  
- **Expected (QA ops checklist):** locking stops two instances  
- **Actual:** Same port → bind fails. Different ports → **both run**. No pidfile/flock.  
- **Repro:** Start two `python -m ingest.live --port 18787` and `--port 18788`  
- **Evidence:** `harness_stdout.txt` `locking_prevents_two_instances`  
- **Environment:** Linux VM  
- **Severity:** LOW (not in PR AC1–AC7; launchd KeepAlive usually one agent)  
- **Confidence:** High  

### F3 — Secret-block vs daemon write path (INFO)

- **Component:** `ingest.live` rebuild vs `tools/ledger_mirror.py`  
- **Expected:** “secret-block still applies on the daemon’s flush path”  
- **Actual:** Daemon **does not flush** to `data/ledger`. Mirror helper still returns `secret_detected` under `--force`. If a local ledger contains a token-like string, the daemon **will** write it into `activity.json` (no `_looks_like_secret` gate on that write).  
- **Evidence:** `secret_block_review.txt`  
- **Severity:** INFO (scope clarification; SEC-MM010-1 intact on mirror tool)  
- **Confidence:** High  

---

## NOT RUN (macOS owner required)

| Item | Why | Owner action on Mac |
|------|-----|---------------------|
| `plutil -lint ops/com.manpreet.mindmap.plist` | Linux CI skips; no `plutil` | Run lint after placeholder replace |
| `launchctl bootstrap` / `bootout` | Linux has no launchd | Install LaunchAgent; verify RunAtLoad, logs, bootout uninstall |
| Placeholder → absolute path substitution | Manual Mac install | Replace `REPLACE_WITH_*` including absolute `.venv/bin/python` |
| KeepAlive crash-loop behaviour under bad venv | launchd-specific throttling (~10s) | Mis-point ProgramArguments; confirm stderr gets 3.12 message and throttled restarts |
| Keychain | Not used by MM-011 | N/A |
| FSEvents | MM-011 uses interval polling, not FSEvents | N/A |

---

## Suite transcripts (SHA `0fa142f`)

```
pytest:  97 passed, 1 skipped
vitest:  40 passed
typecheck root+web: exit 0
vite build: exit 0
```

Files under `qa-evidence/MM-011/`: `pytest.txt`, `vitest.txt`, `typecheck.txt`, `build.txt`, `harness_*.json/txt`, `python311_failfast.txt`, `devops_lows.txt`, `bind_evidence.txt`, etc.
