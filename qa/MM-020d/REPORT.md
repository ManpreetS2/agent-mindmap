# QA Report — MM-020d (PR #21) live SSE + Host/Origin + flock + stream cap

**Verdict: FAIL** (1 high, 2 medium, 1 low)  
**Head:** `dd4a3431214580a1fae1e4e72d78d84c7c7ae809` (`dd4a343`)  
**Prior partial:** `b046529` (held)  
**PR:** https://github.com/ManpreetS2/agent-mindmap/pull/21  
**Base:** `feat/MM-020-unified-network`  
**QA branch:** `qa/MM-020d`  
**Fresh checkout:** `/tmp/qa-mm020d-full/checkout`  
**Environment:** Linux 6.12.94+, Python 3.12.3, Node v22.23.3, Playwright 1.49.1

---

## Automated counts @ `dd4a343`

| Check | Result |
|-------|--------|
| **pytest** (clean, no generated `public/activity.json`) | **154 passed**, 1 skipped, **1 failed** (`test_sec_mm020d_1_sse_connection_cap`) — see finding |
| **pytest** (earlier same SHA) | 155 passed, 1 skipped (**flaky** on SSE cap release) |
| **vitest** | **81 passed** (18 files) |
| **typecheck** root + web | clean |
| **build** | success |
| **CI pytest** | **success** run [39398884101](https://github.com/ManpreetS2/agent-mindmap/actions/runs/39398884101) @ `dd4a343` |
| **CI web** | **not triggered** (path filter: PR touches `ingest/`, `tests/`, `README`, `ops/` only) |

---

## Behavioral checks

### (1) Host/Origin matrix (all endpoints incl. `/events`) — mostly PASS

| Case | `/healthz` | `/activity.json` | static | `/events` |
|------|------------|------------------|--------|-----------|
| Allowed localhost Host+Origin | 200 | 200 | 200 | 200 |
| `Host: evil.com` | 403 | 403 | 403 | 403 |
| DNS-rebind-style Host | 403 | 403 | 403 | 403 |
| IP variants (`127.1`, `0.0.0.0`, `[::1]`) | 403 | 403 | 403 | 403 |
| Missing Host | 403 | 403 | 403 | 403 |
| Mismatched Origin (`https://evil.com`) | 403 | 403 | 403 | 403 |
| `Origin: null` | **200** | **200** | **200** | **200** |

Evidence: `logs/dd4a343…/host_origin_matrix.json`

### (2) SSE — PASS (backend)

| Check | Result |
|-------|--------|
| Order + dedupe | PASS (`e1,e2,e3`) |
| Last-Event-ID replay | PASS (`e3,e4` after `e2`) |
| Heartbeat `: heartbeat` | PASS |
| 6 concurrent clients | PASS |
| Disconnect fd/thread bounded (40 cycles) | PASS (no permanent fd growth) |
| Live UI via SSE without position reset | **N/A / low finding** — no SSE client in web (poll only); drag positions stable on daemon-hosted UI without updates |

### (3)/(a) QA-MM011-2 flock singleton — PASS

| Check | Result |
|-------|--------|
| Second instance refused + clear message | PASS |
| `kill -9` then restart acquires | PASS |
| Lock mode `0o600` | PASS |
| Symlink lock path refused (`O_NOFOLLOW`) | PASS |
| Port conflict → `Address already in use` | PASS |

### (4) Bind / XSS / outbound — PASS

| Check | Result |
|-------|--------|
| Listen `127.0.0.1` only | PASS |
| XSS markup in SSE JSON `summary` as data | PASS |
| UI XSS (`__xss`) | PASS false |
| Outbound beyond localhost (UI) | PASS none |

### (5)/(b) SEC-MM020d-1 stream cap — FAIL (release timing)

| Check | Result |
|-------|--------|
| Streams 1–8 → 200; 9th → **503 + Retry-After: 5** | PASS |
| Slot frees after graceful disconnect (wait > heartbeat) | PASS |
| Slot frees after abrupt disconnect (wait > heartbeat) | PASS |
| Permanent leak after 100 cycles (`active_end==0`) | PASS |
| Threads bounded | PASS |
| Rapid connect/close without waiting | **FAIL** — many 503s until heartbeat write detects peer close |
| Product unit test `test_sec_mm020d_1_sse_connection_cap` | **FAIL / flaky** (`sleep(0.2)` after close → often still 503) |

Evidence: `stream_cap_focused.json`, `pytest.txt`, `behavioral_run.txt`

**Production impact:** default `sse_heartbeat_sec=15`, so a disconnected client can hold a slot for up to ~15s before release.

### (6) Regressions MM-020a / 020c / 020f

| Area | Result |
|------|--------|
| MM-020a membership / schema tests | PASS in clean suite (generated `public/activity.json` only env-artifact) |
| MM-020c events fetch/mirror tests | PASS (in full suite) |
| MM-020f web vitest (cluster/merge/edges) | PASS 81 |
| Live daemon serves multi-group UI | PASS (graph+filter load) |

---

## Findings

### F1 — SEC-MM020d-1 delayed slot release (HIGH)

| Field | Value |
|-------|-------|
| **component** | `MindmapHandler._handle_sse` + `SseConnectionLimiter` |
| **expected** | After client disconnect (incl. abrupt), slot frees promptly; 100 connect/disconnect cycles stay under cap without spurious 503; product test stable |
| **actual** | Slot released only when a subsequent `wfile.write` fails (heartbeat path). Until then, count stays high → 9th/rapid reconnect get **503**. Focused: release ~one heartbeat (~0.2s in test; **up to 15s default**). `test_sec_mm020d_1_sse_connection_cap` failed locally (503 after `sleep(0.2)`). `rapid30` → 22×503. No permanent leak (`active_end=0`). Event-write `BrokenPipeError` not caught (stderr traceback) though `finally` still releases. |
| **repro** | Open 8 `/events`; close one; immediately open → 503 until heartbeat. Or re-run `pytest tests/test_live.py::test_sec_mm020d_1_sse_connection_cap` repeatedly. |
| **evidence** | `stream_cap_focused.json`, `pytest.txt`, `behavioral_run.txt` |
| **environment** | Linux, Python 3.12, head `dd4a343` |
| **severity** | high |
| **confidence** | high |

### F2 — Origin: null allowed (MEDIUM — checklist vs PR AC)

| Field | Value |
|-------|-------|
| **component** | `origin_header_allowed` |
| **expected** (this verify checklist) | `Origin: null` → 403 on all endpoints |
| **actual** | **200** — matches PR body / audit “absent, null, or localhost” policy |
| **repro** | `GET /healthz` with `Host: 127.0.0.1:PORT` and `Origin: null` |
| **evidence** | `host_origin_matrix.json` |
| **severity** | medium |
| **confidence** | high |

### F3 — SSE UI transport not wired (LOW)

| Field | Value |
|-------|-------|
| **component** | `web/src/data/activityTransport.ts` |
| **expected** (checklist) | UI live-updates via SSE without resetting positions |
| **actual** | Poll transport only; backend SSE verified. Daemon-hosted UI loads; dragged positions stable without updates. |
| **evidence** | `ui_positions_retry.json`, `ui_report.json` |
| **severity** | low |
| **confidence** | high |

---

## Verdict rationale

Host/Origin allowlist (except null-vs-checklist), flock singleton, bind, XSS, ordering/Last-Event-ID/heartbeat, and vitest/CI pytest are in good shape. **FAIL** because SEC-MM020d-1 does not free SSE slots until the next heartbeat write, which flakes the product’s own cap test, causes rapid-reconnect 503s, and with the default 15s heartbeat can pin slots long after clients disconnect.

---

## Notes

- Verify-only: no product edits; no PR comments; no merge; evidence only on `qa/MM-020d`.
- Harness: `scripts/qa_mm020d_behavioral.py`
