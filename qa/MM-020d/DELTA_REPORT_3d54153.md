# QA Delta Report — MM-020d (PR #21) @ `3d54153` vs FAIL @ `b67ac50`

**Verdict: PASS** (0 findings)  
**Head under test:** `3d5415347d7f378b1bcbf135011941d3e472d107` (`3d54153`)  
**Prior delta FAIL:** `b67ac506dbf8edbbe8e6f796b6c99deed530049a` (`b67ac50`) — see `DELTA_REPORT.md`  
**PR:** https://github.com/ManpreetS2/agent-mindmap/pull/21  
**QA branch:** `qa/MM-020d`  
**Fresh checkout:** `/tmp/qa-mm020d-delta3/checkout`  
**Diff vs `b67ac50`:** `ingest/live.py` (+drain / end-on-client-data), `tests/test_live.py` (+garbage regression)  
**Environment:** Linux 6.12.94+, Python 3.12.3, Node v22.23.3, Chromium 131 (ms-playwright 1148)

---

## Prior finding disposition

| ID | Topic | @ `b67ac50` | @ `3d54153` |
|----|-------|-------------|-------------|
| SEC-MM020d-2 | select+MSG_PEEK busy-spin + permanent slot leak on post-request garbage | FAIL (high) — ~90% CPU / 10s; slot held 20s+ after close | **CLEARED** — ~0% util / 10s; slot freed in ~0s; peer close observed |

Earlier FAIL drivers (slot release ≤1s, `Origin: null` → 403) remain cleared.

---

## Automated counts @ `3d54153`

| Check | Result |
|-------|--------|
| **`test_sec_mm020d_2_sse_garbage_client_bytes_no_cpu_spin`** ×20 | **20/20 PASS** — `garbage_x20_failures=0` |
| **`test_sec_mm020d_1_sse_connection_cap`** ×20 | **20/20 PASS** — `cap_x20_failures=0` |
| **pytest** ×3 (clean; no generated `web/public/activity.json`) | **158 passed**, 1 skipped ×3 — `pytest_x3_failures=0` |
| **vitest** | **81 passed** (18 files) |
| **typecheck** root + web | clean (`EXIT:0`) |
| **build** | success |
| **CI pytest** | **success** run [39406159481](https://github.com/ManpreetS2/agent-mindmap/actions/runs/39406159481) @ `3d54153` |
| **CI web** | **not triggered** (path filter: ingest/tests only) |

---

## (1) SEC-MM020d-2 behavioral — PASS

| Check | Result | Detail |
|-------|--------|--------|
| Garbage + keep socket open ~10s: CPU near idle | PASS | `approx_util_last_half≈0.0`, `cpu_delta_s≈0.01` over `wall_s=10.01` |
| Stream/slot freed ≤1s (socket still open) | PASS | `freed_within_1s=true`, `free_elapsed_s≈0.0`; peer EOF seen |
| 8 concurrent garbage clients | PASS | all free ≤1s; legit client **200**; `active_final=0` |
| Slow trickle (1 byte / 50ms) | PASS | freed after first byte (`elapsed_s≈0.05`) |
| `SHUT_WR` half-close | PASS | freed ≤1s |

Evidence: `cpu_spin.json`, `eight_garbage.json`, `trickle.json`, `shut_wr.json`

Product behavior: readable non-EOF client data → drain → end SSE → `SHUT_RDWR` → limiter release (no busy `continue`).

---

## (2) Legitimate clients not closed by mistake — PASS

| Check | Result | Detail |
|-------|--------|--------|
| curl-like raw SSE across ≥3 heartbeats (`hb=0.25`) | PASS | 3× `: heartbeat`, slot still held |
| Chromium `EventSource` across ≥3 heartbeat intervals | PASS | `readyState=1`, `opened=true` |
| Node W3C `EventSource` corroboration | PASS | `readyState=1`, `opened=true` |

Evidence: `legit_survive.json`

---

## (3) Regression / cap / full suite — PASS

See automated counts above (garbage ×20, cap ×20, pytest ×3 all green).

---

## (4) Earlier fixes still hold — PASS

| Check | Result |
|-------|--------|
| Graceful close → new stream ≤1s (`heartbeat=15`) | PASS (~0s) |
| Abrupt RST (raw socket `SO_LINGER`) → free ≤1s | PASS (also `disconnect_matrix.json`: RST/graceful/`SHUT_WR` 3/3) |
| 100 rapid cycles | PASS (`fail503=0`, `stuck=0`, `active_end=0`) |
| `Origin: null` → 403 all routes | PASS |
| Host/Origin matrix (evil/bad/missing Host) | PASS |
| flock `0o600` / second refused / after `kill -9` / symlink refused | PASS |
| Bind `127.0.0.1` only | PASS |
| SSE order+dedupe / Last-Event-ID | PASS |
| XSS payload as JSON text | PASS |
| MM-020a / 020c / 020f (pytest + vitest 81) | PASS in clean suite |

---

## Findings @ `3d54153`

None.

---

## Verdict rationale

`3d54153` ends SSE on unexpected client read data (drain + exit) instead of spinning on `MSG_PEEK`. Behavioral repro of SEC-MM020d-2 now shows **idle CPU** and **prompt slot release**, including 8-wide garbage, trickle, and `SHUT_WR`. Legitimate EventSource/curl streams survive ≥3 heartbeats. New garbage regression and cap tests are stable ×20; full pytest ×3 is green; CI pytest on the head is success. **PASS.**

---

## Notes

- Verify-only: no product edits; no PR comments; no merge; evidence only on `qa/MM-020d`.
- Harness: `scripts/qa_mm020d_delta_3d54153.py` (phased subprocesses; `MockGh` to avoid hung `gh` polls).
- Log dir: `logs/3d5415347d7f378b1bcbf135011941d3e472d107/`
