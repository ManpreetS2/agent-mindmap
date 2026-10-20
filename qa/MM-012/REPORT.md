# QA Report — MM-012 (PR #14) redesign UI

**Verdict: PASS** (1 medium finding)  
**Target head:** `ceebb76030cf7b0ada835edd7df1069190b6afb5` (`ceebb76`)  
**PR head at verify time:** `ceebb76` (unchanged from requested)  
**PR:** https://github.com/ManpreetS2/agent-mindmap/pull/14  
**QA branch:** `qa/MM-012`  
**Environment:** Linux 6.12.94+, Python 3.12.3, Node v22.23.3, Playwright Chromium 131, Vite 5.4.21  
**Fresh checkout:** `/tmp/qa-mm012-checkout` @ `ceebb76`

---

## Acceptance sources

- PR #14 body + phase comments (futuristic UI, motion, poll, brush, polish)
- README hard constraints (127.0.0.1, no secrets, no CDN runtime)
- Repo invariants exercised by prior QA (verdict fallback, self-loops, `(repo, number)` joins, XSS, empty/missing/malformed)
- Note: `build/mindmap/architecture.md` is **not** in this repo (same as prior QA)

---

## Checks @ `ceebb76`

| Check | Result | Evidence |
|-------|--------|----------|
| `python3 -m pytest -q` | **69 passed** | `logs/ceebb76/pytest.txt` |
| Self-loop + `(repo, number)` + verdict edge tests | **4 passed** | `logs/ceebb76/pytest_edges.txt` |
| `cd web && npm test` (vitest) | **56 passed** (14 files) | `logs/ceebb76/vitest.txt` |
| MM-012 feature unit tests (diff/poll/brush/layout) | **11 passed** | `logs/ceebb76/vitest_mm012_features.txt` |
| `tsc` root + web | clean | `logs/ceebb76/typecheck-*.txt` |
| `cd web && npm run build` | success | `logs/ceebb76/build.txt` |
| CI web workflow @ head | **success** (run 39389743872) | `logs/ceebb76/ci_checks.txt` |
| Dev server bind `127.0.0.1` only | **PASS** (netstat; external IP connection failed) | `logs/ceebb76/dev_bind.txt`, `dev-server.txt` |
| Demo UI: graph + timeline + legend | **PASS** | `screenshots/01-demo-graph.png` |
| MiniMap / drag handle / brush / zoom | **PASS** | Playwright + screenshots |
| Now-line | **PASS** when domain includes now | `screenshots/12-now-line.png` |
| List view toggle | **PASS** (“List view”) | `screenshots/11-list-view.png` |
| Legend top-right polish | **PASS** | Playwright bbox |
| Debug drawer (unparsed) | **PASS** | `screenshots/08-unparsed-debug-open.png` |
| Verdict fallback COND/BLK/INC + unknown→VER | **PASS** | `screenshots/04-verdict-fallbacks.png` |
| Empty activity.json | **PASS** | `screenshots/05-empty-state.png` |
| Malformed activity.json | **PASS** (alert + Retry) | `screenshots/07-malformed-activity.png` |
| Missing activity.json | **FAIL→finding** (alert, but not LedgerErrorView) | `screenshots/06-*.png`, `13-*.png` |
| No self-loop edges (demo+sample) | **PASS** | Playwright + pytest |
| PR events carry repo identity | **PASS** | fixture + `test_cross_repo_pr_number_not_joined` |
| No console errors (demo) | **PASS** | Playwright |
| Keyboard skip-link focus | **PASS** | Playwright |
| A11y labels + contrast spot-check | **PASS** | Playwright |
| XSS via ledger/task/event text | **PASS** (no execution) | `screenshots/09-xss-payload.png` |
| No automatic outbound beyond localhost | **PASS** | Playwright request listener |
| No secrets in repo / activity.json | **PASS** | `logs/ceebb76/repo_secret_scan.txt` |

Machine-readable: `logs/ceebb76/playwright_report.json`  
Harness: `scripts/qa_mm012_playwright.mjs`

---

## PR claims vs observed

| Claim (PR body / comments) | Observed |
|----------------------------|----------|
| Timeline fixes + Debug drawer | PASS (unit + UI Debug toggle) |
| Tailwind / shadcn / Magic UI + glass/neon shell | PASS (build + UI screenshots) |
| Graph drag handle (hover, top-right), MiniMap, tooltips/glow, particles | PASS (handle+MiniMap present; motion deps present) |
| `prefers-reduced-motion` | PASS (CSS + `useReducedMotion` present; axe suite green) |
| 10s poll + id diff-patch | PASS (`POLL_MS` default 10_000; transport/diff tests) |
| Timeline zoom/brush + now line | PASS (brush/zoom UI; now-line when in domain) |
| Group-band ≥24px + dagre fallback | PASS (`graphLayout.test.ts`) |
| Legend top-right; unsourced beside markers | PASS (bbox + prior unsourced tests) |
| A11y suite preserved; new tests green | PASS (56 vitest incl. A11y) |

---

## Findings @ `ceebb76`

### QA-MM012-1 — Missing `activity.json` under Vite does not hit `LedgerErrorView`

| Field | Value |
|-------|-------|
| **component** | `loadActivity` + Vite SPA host (`npm run dev` / `vite preview`) |
| **expected** | Missing file → HTTP 404/422 → `LedgerLoadError` → `LedgerErrorView` (“Can't read …”) + Retry |
| **actual** | Vite SPA-fallback serves `index.html` with **HTTP 200** for `/activity.json`; UI shows JSON parse error: `Unexpected token '<', "<!doctype "... is not valid JSON` + Retry (no crash) |
| **repro** | `rm web/public/activity.json`; `curl -i http://127.0.0.1:5173/activity.json`; reload UI |
| **evidence** | `logs/ceebb76/screenshots/06-missing-activity.png`, `13-missing-activity-detail.png`, `playwright_followup.txt` |
| **environment** | Linux, Vite 5.4.21, Playwright, head `ceebb76` |
| **severity** | medium |
| **confidence** | high |

Notes: Empty + malformed paths behave acceptably. This host fallback predates MM-012 (LedgerErrorView path requires a true 404/422). Does not block redesign AC; documented for Architect/DevOps if a static 404 for `/activity.json` is required.

**No other findings.** XSS, localhost bind, secrets, self-loops, verdict fallback, and outbound network checks passed.

---

## Verdict rationale

Automated suites and CI are green; redesign claims verified in UI; security/localhost/XSS invariants hold. The single medium finding is host-level missing-file handling, not a redesign regression. **PASS**.

---

## Notes

- Independent QA: no product edits; no push to `feat/MM-012-redesign`; no GitHub comments on PR #14; no merge; no QA PR opened.
- Artifacts only on `qa/MM-012`.


---

## Delta re-verify @ `034655a` (rebase onto `73457a1` + nits)

**Verdict: PASS** — see [`logs/034655aeee8f30bdfd883fbc3a319f437ec86ae3/DELTA_REPORT.md`](logs/034655aeee8f30bdfd883fbc3a319f437ec86ae3/DELTA_REPORT.md).

- Rebased stack `patch-id --stable` == `ceebb76` (5/5)
- Nit commit `034655a`: unsourced offset + neon zoom (2 files, CSS/layout only)
- pytest **97** / vitest **56** / tsc+build clean / CI web **success** (39391439626)
