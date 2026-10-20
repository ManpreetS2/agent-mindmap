# QA delta re-verify — MM-012 @ `034655a`

**Verdict: PASS**  
**Target head:** `034655aeee8f30bdfd883fbc3a319f437ec86ae3`  
**Prior verified head:** `ceebb76030cf7b0ada835edd7df1069190b6afb5`  
**Rebase base:** `73457a13dacac38b6985df625e04fb39f1210e6f` (main / MM-011)  
**QA branch:** `qa/MM-012`  
**Note:** Interim merge `c091f4b` was force-replaced by this rebase + nits; verify target is the current tip.

---

## Delta vs `ceebb76` (allowed differences only)

### Rebased MM-012 stack = `ceebb76` (patch-id)

| Original | Rebased | `patch-id --stable` |
|----------|---------|---------------------|
| `2c44759` | `ea4f5be` | equal |
| `acd4dd6` | `14343c4` | equal |
| `ed22901` | `96c392d` | equal |
| `0220f7c` | `5264ef1` | equal |
| `ceebb76` | `5dae42b` | equal |

Faithful rebase tip before nits: `5dae42b`.

### Tree delta `ceebb76` → `034655a`

| Class | Count | Result |
|-------|-------|--------|
| Blob == `73457a1` (main content) | 22 | PASS |
| Nit tip only (`5dae42b`→`034655a`) | 2 files | PASS — in scope |
| Both-touched rebase 3-way (`README.md`, `MindmapView.tsx`) | 2 | Expected from replaying identical patches onto main; **unchanged by nits** |
| Unexpected alien blobs | 0 | PASS |

`only_mm012` / `only_main` path sets at polish tip: **0 mismatches**.

### Nit commit(s)

History shows **one** commit after polish with **two** nit fixes (not two separate commits):

- **`034655a`** — `fix(web): timeline unsourced offset + neon zoom controls after MM-011 rebase`
  - `web/src/components/TimelineSwimlanes.tsx` — shift `UnsourcedTag` when a task chip is present (layout only)
  - `web/src/styles/graph.css` — neon styling + `:focus-visible` on timeline zoom buttons

Scope: CSS/layout polish only. No data loading, no HTML sinks, no bind/host changes, no verdict mapping changes.

Evidence: `nit_delta_polish_to_tip.diff`

---

## Checks @ `034655a`

| Check | Result | Evidence |
|-------|--------|----------|
| `pytest -q` | **97 passed, 1 skipped** | `pytest.txt` |
| `vitest` | **56 passed** | `vitest.txt` |
| tsc root + web | clean | `typecheck-*.txt` |
| `npm run build` | success | `build.txt` |
| CI `web` @ `034655a` | **success** (run 39391439626) | `ci_checks.txt` |
| `127.0.0.1` bind (config + runtime) | PASS | `bind_static.txt`, `dev_bind.txt` |
| Verdict fallback + XSS smoke | PASS | `playwright_smoke.txt`, `smoke-verdict-xss.png` |
| A11y suite (axe + keyboard) | PASS | `vitest_invariants.txt` |

---

## Earlier invariants (nits did not break)

| Invariant | Status |
|-----------|--------|
| XSS (no `dangerouslySetInnerHTML`; script/onerror fixture text inert) | PASS |
| Verdict fallback COND + unknown→VER | PASS |
| Localhost-only Vite bind | PASS |
| A11y (axe serious/critical none; skip-link) | PASS |

---

## Findings @ `034655a`

**None new.** Prior `QA-MM012-1` (Vite SPA fallback for missing `activity.json`) remains a pre-existing host note; nits do not affect it.

---

## Verdict rationale

Rebase is patch-identical to `ceebb76`; non-main deltas are the documented layout/CSS nits (plus expected both-touched replay blobs). Suites and CI green; security/a11y/bind/verdict smokes still pass. **PASS**.
