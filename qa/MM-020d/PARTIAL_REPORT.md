# QA MM-020d — PARTIAL (held)

**Status:** PARTIAL — verification held on request; **no verdict**.  
**Target head at hold:** `b046529bc149a37cfdb94ddc8f9294cee4f26ea5` (`b046529`)  
**PR:** https://github.com/ManpreetS2/agent-mindmap/pull/21  
**Base:** `feat/MM-020-unified-network`  
**QA branch:** `qa/MM-020d`  
**Stopped:** 2026-10-20 (UTC) — awaiting new SHA with singleton lock (flock)

---

## Completed before hold

| Item | Result |
|------|--------|
| Fresh worktree @ `b046529` | yes (`/tmp/qa-mm020d/checkout`) |
| PR meta / body / implementation comment | captured |
| CI pytest on head | **success** (run 39398290981) |
| CI web on head | not listed in `gh pr checks` at hold |
| Locate SEC/SSE code (`host_header_allowed`, `origin_header_allowed`, `/events`, heartbeat) | identified in `ingest/live.py` + `tests/test_live.py` |
| Prior MM-011 note on singleton | prior QA: no pidfile/flock (LOW); flock SHA pending |

## Not run (deferred)

- Host/Origin matrix on all endpoints incl. SSE
- SSE stream / Last-Event-ID / heartbeat / disconnect cleanup / concurrency / UI positions
- QA-MM011-2 singleton lock + stale lock + port conflict
- Bind / XSS-via-SSE / outbound
- Local pytest / vitest / typecheck / build exact counts
- Regressions vs MM-020a / 020c / 020f
- Verdict

---

## Notes

- Verify-only; no product edits; no PR comments; no merge.
- Resume on the flock SHA against this branch’s partial baseline.
