# QA Delta Report — MM-020d (PR #21) @ `b67ac50` vs FAIL @ `dd4a343`

**Verdict: FAIL** (1 high — SEC-MM020d-2)  
**Head under test:** `b67ac506dbf8edbbe8e6f796b6c99deed530049a` (`b67ac50`)  
**Prior FAIL:** `dd4a3431214580a1fae1e4e72d78d84c7c7ae809` (`dd4a343`) — see `REPORT.md`  
**PR:** https://github.com/ManpreetS2/agent-mindmap/pull/21  
**QA branch:** `qa/MM-020d`  
**Fresh checkout:** `/tmp/qa-mm020d-delta2/checkout`  
**Environment:** Linux 6.12.94+, Python 3.12.3, Node v22.23.3  
**Out of scope this delta:** QA-MM020d-3 SSE UI transport

---

## Prior findings disposition

| Prior ID | Topic | @ `dd4a343` | @ `b67ac50` |
|----------|-------|-------------|-------------|
| F1 / SEC-MM020d-1 | Slot release only on heartbeat write; rapid 503s; flaky cap test | FAIL (high) | **CLEARED** — graceful/abrupt ≤1s; 100 cycles clean; cap test ×20 = 0 failures |
| F2 | `Origin: null` → 200 | FAIL (medium vs checklist) | **CLEARED** — `Origin: null` → **403** on `/healthz`, `/activity.json`, static, `/events` |
| F3 | SSE UI not wired | low / N/A | Still out of scope (QA-MM020d-3) |

---

## Automated counts @ `b67ac50`

| Check | Result |
|-------|--------|
| **pytest** ×3 (clean; no generated `web/public/activity.json`) | **157 passed**, 1 skipped ×3 — `pytest_x3_failures=0` |
| **`test_sec_mm020d_1_sse_connection_cap`** ×20 | **20/20 PASS** — `cap_x20_failures=0` |
| **vitest** | **81 passed** (18 files) |
| **typecheck** root + web | clean |
| **build** | success |
| **CI pytest** | **success** run [39402171223](https://github.com/ManpreetS2/agent-mindmap/actions/runs/39402171223) @ `b67ac50` |
| **CI web** | **not triggered** (path filter: ingest/tests only) |

---

## Behavioral checks (prompt + Security addition)

### QA-MM020d-1 prompt release — PASS

| Check | Result | Detail |
|-------|--------|--------|
| 8 streams → 200; 9th → **503 + Retry-After: 5** | PASS | |
| Graceful close → new stream ≤1s (`heartbeat=15`) | PASS | `elapsed_s≈0.001` |
| Abrupt close → new stream ≤1s | PASS | `elapsed_s≈0.0` |
| 100 rapid open/close (clean run) | PASS | `fail503=0`, `stuck_wait0=0`, `active_end=0`, threads bounded |

Evidence: `prompt_release.json`, `cycles100_clean.json`, `cycles_and_spin_followup.txt`  
Note: first harness pass reported `unexpected_503_or_stuck=100` due to leftover streams / `wait_until_active_at_most(0)` — clean re-run is authoritative.

### Origin / Host matrix — PASS

| Case | Result |
|------|--------|
| Missing Origin | 200 |
| Local Origin | 200 |
| **`Origin: null`** | **403** all routes |
| Evil Host / bad Origin / missing Host | 403 |

Evidence: `origin_host_matrix.json`

### SSE / flock / bind / XSS — PASS

| Check | Result |
|-------|--------|
| Order + dedupe | PASS |
| Last-Event-ID | PASS |
| flock `0o600`, second refused, after `kill -9`, symlink refused | PASS |
| Bind `127.0.0.1` only | PASS |
| XSS payload as JSON text in SSE | PASS |

### SEC-MM020d-2 garbage-after-request CPU spin — FAIL (HIGH)

**Repro:** open `GET /events`; read response headers; send non-empty garbage bytes (`GARBAGE_BYTES_NOT_HTTP…`); **keep TCP open**; sample `/proc/<pid>/task/*/stat` ~10s; then close and watch slot.

| Metric | Observed |
|--------|----------|
| Wall window | **10.01 s** |
| CPU delta (full window) | **10.01 s** |
| CPU last half (~5 s) | **4.52 s** → **≈90%** util |
| `active` during garbage | **1** (slot held) |
| Slot freed within 1s of client close | **false** |
| Slot freed within **20 s** of close | **false** (`freed_at_s: null`, `active_after_20s: 1`) |

**Mechanism (product, read-only):** `_handle_sse` does `select` → if readable and `_peer_closed()` is false → `continue` with **no drain, no backoff, no heartbeat write**. `_peer_closed` uses `MSG_PEEK`; non-EOF garbage keeps the socket readable forever, so the loop busy-spins and never reaches the heartbeat path that would surface a write error after the client leaves. After TCP close, unread peek data still prevents EOF → **permanent thread spin + permanent slot hold** until process death.

Evidence: `cpu_spin.json`, `spin_slot_leak.json`, `cycles_and_spin_followup.txt`, harness `scripts/qa_mm020d_delta_b67ac50.py`

**Severity (QA rating): high**  
Localhost-only bind limits remote attackers, but one misbehaving/local client pins **~1 core** and **one of eight** SSE slots indefinitely (and the spinning handler never emits heartbeats). That is sustained DoS of the live daemon’s stream budget and CPU — high confidence, high severity for this PR’s security surface.

---

## Findings @ `b67ac50`

### F1 — SEC-MM020d-2 select+MSG_PEEK busy-spin on post-request bytes (HIGH)

| Field | Value |
|-------|-------|
| **component** | `MindmapHandler._handle_sse` / `_peer_closed` |
| **expected** | Readable non-EOF client data must not busy-spin; drain, close, or backoff; slot must free when the client is gone |
| **actual** | ~**90%** CPU over ~5s with socket left open after garbage; slot still held **20s+** after close; stream stays counted in limiter |
| **repro** | SSE open → send garbage → keep socket open → measure CPU 10s → close → `active_count` stays ≥1 |
| **evidence** | `logs/b67ac50…/cpu_spin.json`, `spin_slot_leak.json` |
| **environment** | Linux, Python 3.12, head `b67ac50`, `sse_heartbeat_sec=15` |
| **severity** | **high** |
| **confidence** | **high** |

---

## Verdict rationale

Delta **clears** the prior FAIL drivers (prompt slot release under 1s, stable cap test, `Origin: null` → 403). Automated suites and CI pytest are green. **FAIL** solely on **SEC-MM020d-2**: confirmed behavioral CPU spin (~90%) plus lasting SSE slot leak when extra bytes arrive after the request and the connection is not drained/closed by the server.

---

## Notes

- Verify-only: no product edits; no PR comments; no merge; evidence only on `qa/MM-020d`.
- Harness: `scripts/qa_mm020d_delta_b67ac50.py`
- Log dir: `logs/b67ac506dbf8edbbe8e6f796b6c99deed530049a/`
