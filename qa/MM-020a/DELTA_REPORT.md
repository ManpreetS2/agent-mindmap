# QA Delta Report — MM-020a / PR #16 @ `82f2066`

| Field | Value |
|-------|-------|
| **Verdict** | **PASS** |
| **Target SHA** | `82f20667ea2a2336701ed549a7caaa77fc0c2249` (`82f2066`) |
| **Prior FAIL SHA** | `b1fe594ec72086a1b025a7b137213b9632f35920` (`b1fe594`) |
| **Base (main)** | `1a3a0cc684f518705abd4148d42f1a46666cbd25` |
| **PR** | https://github.com/ManpreetS2/agent-mindmap/pull/16 (draft) |
| **Head moved?** | Yes — `b1fe594` → `82f2066` (`fix(MM-020a): dedupe membership, park unknowns, require provenance`) |
| **Environment** | Linux 6.12.94+; Python 3.12.3; Node v22.23.3; Playwright Chromium 131 |
| **Fresh checkout** | `/tmp/qa-mm020a-delta/checkout` (detached @ `82f2066`) |
| **Evidence branch** | `qa/MM-020a` |
| **Date** | 2026-10-20 |

Verify-only: no product edits; no push to `feat/MM-020-unified-network`; no PR comments; no merge; no new PR.

---

## Verdict summary

Prior blockers **QA-MM020a-1** (duplicate membership) and **QA-MM020a-2** (unknown members) are fixed and confirmed by behavioral tests. Provenance is required on schema **1.1.0** events; migration fills legacy sources correctly and is idempotent. Suites and CI are green; XSS/UI regressions hold. One **INFO** claim-count nit remains (117 passed ≠ “118 passed”).

---

## Requested checks

### (1) QA-MM020a-1 — duplicate members deduped — **PASS**

| Field | Value |
|-------|-------|
| **component** | `ingest/membership.py` `membership_index` / `resolve_membership` |
| **expected** | Repeated id within one group → one group entry; same bot in several groups → unique group list in first-seen order |
| **actual** | `members: [director×3, architect]` in build + duplicates in qr → `director==['build','qr','radar']`, each group once |
| **repro** | `harness/delta_verify.py` `check_dedupe`; unit `test_qa_mm020a_1_membership_dedupes_repeated_members` |
| **evidence** | `logs/delta_harness.txt`, `logs/delta_harness_results.json`, `logs/pytest-mm020a.txt` |
| **environment** | Linux VM @ `82f2066` |
| **severity** | n/a (fixed) |
| **confidence** | high |

### (2) QA-MM020a-2 — unknown members parked + warning — **PASS**

| Field | Value |
|-------|-------|
| **component** | `resolve_membership` |
| **expected** | Unknown ids not indexed; parked in `unknown_members`; warning on stderr; no raise |
| **actual** | `ghost-bot` parked for build+qr; warn contains `parking (QA-MM020a-2)`; index only known bots |
| **repro** | harness `check_unknown_parked`; unit `test_qa_mm020a_2_unknown_members_parked_not_indexed` |
| **evidence** | `logs/delta_harness.txt` |
| **severity** | n/a (fixed) |
| **confidence** | high |

### (3) Provenance required on new 1.1.0 events — **PASS**

| Field | Value |
|-------|-------|
| **component** | `schema/activity.schema.json` `allOf` if `schema_version==1.1.0` then events/unparsed require `provenance` |
| **expected** | Missing or invalid provenance rejected; valid enum accepted; 1.0.0 still optional |
| **actual** | Missing → ValidationError `'provenance' is a required property`; `ledger-claimed` rejected; `observed` ok; 1.0.0 without provenance validates |
| **repro** | harness `check_provenance_required`; unit `test_schema_1_1_rejects_event_without_provenance` |
| **evidence** | `logs/delta_harness_results.json` |
| **confidence** | high |

### (4) Legacy migration fill + idempotent — **PASS**

| Field | Value |
|-------|-------|
| **component** | `ingest/migrate.py` `infer_provenance` / `migrate_activity` |
| **expected** | GitHub → `github-verified`; ledger / signature → `agent-reported`; idempotent; disk fixtures unchanged |
| **actual** | Sample from `1a3a0cc` bumped with zero rule mismatches; explicit gh/ledger/sig cases match; `migrate(migrate(doc))` provenance map unchanged; no-bump leaves 1.0.0 events untouched |
| **repro** | harness `check_migration_fill`; units `test_migrate_fills_*`, parametrized fixture bump |
| **evidence** | `logs/delta_harness.txt` |
| **confidence** | high |

### (5) Claimed counts — **claim mismatch (INFO)**

| Suite | Claimed | Exact observed (local) | Exact observed (CI @ `82f2066`) |
|-------|---------|------------------------|----------------------------------|
| pytest | **118 passed**, 1 skipped | **117 passed, 1 skipped** (118 collected) | **117 passed, 1 skipped** (118 collected) |
| vitest | **56 passed** | **56 passed** (14 files) | **56 passed** |

| Field | Value |
|-------|-------|
| **component** | PR / verifier claim vs runners |
| **expected** | 118 pytest passed + 1 skipped; 56 vitest |
| **actual** | pytest **117 passed, 1 skipped**; vitest **56 passed** |
| **repro** | `python -m pytest -q`; CI run 39395385428 |
| **evidence** | `logs/pytest.txt`, `logs/ci_pytest_count.txt`, `logs/vitest.txt`, `logs/ci_vitest_count.txt` |
| **severity** | info |
| **confidence** | high |

### (6) CI on head — **PASS**

| Check | Result | Run |
|-------|--------|-----|
| pytest | **success** @ `82f2066` | https://github.com/ManpreetS2/agent-mindmap/actions/runs/39395385428 |
| web | **success** @ `82f2066` | https://github.com/ManpreetS2/agent-mindmap/actions/runs/39395385395 |

Evidence: `logs/ci_checks.txt`, `logs/ci_pytest_meta.json`, `logs/ci_web_meta.json`.

### (7) No regressions vs earlier checks — **PASS**

| Prior check | @ `82f2066` |
|-------------|-------------|
| Multi-membership Director/Architect; Bug fixer out | PASS |
| Message edges (untargeted / explicit / no self-loop / never invent) | PASS |
| Merge self-loop invariant | PASS |
| Build emits schema 1.1.0 with provenance on events | PASS |
| Fixtures secret-scan clean | PASS |
| Provenance not spoofable via ledger text | PASS |
| Malformed groups.json → JSONDecodeError | PASS |
| Unknown/future schema_version → ValueError | PASS |
| tsc root + web / `npm run build` | clean |
| XSS message payloads (1.0.0 + 1.1.0) | PASS (`logs/xss_message_results.json`) |

---

## Findings @ `82f2066`

### QA-MM020a-6 — Pytest count claim off-by-one (INFO)

| Field | Value |
|-------|-------|
| **component** | Claimed suite count |
| **expected** | 118 passed, 1 skipped |
| **actual** | **117 passed, 1 skipped** (118 collected) — local and CI agree |
| **repro** | `pytest -q` on `82f2066` |
| **evidence** | `logs/pytest.txt`, `logs/ci_pytest_count.txt` |
| **environment** | Linux VM + GH Actions |
| **severity** | info |
| **confidence** | high |

**Prior FAIL findings QA-MM020a-1 and QA-MM020a-2: resolved.**  
Prior INFO items (derive_edges-alone idempotency; write-path secret strip) unchanged and non-blocking.

---

## Suite transcripts (exact)

```
pytest: 117 passed, 1 skipped in 3.10s   (118 tests collected)
vitest: 56 passed (14 files)
typecheck: root + web clean
build: vite success
delta harness: 23/23 ok
XSS: legacy-10 PASS; message-11 PASS
```

---

## Verdict rationale

Functional fixes for the earlier FAIL are verified. Suites/CI green; migration and provenance contract hold. **PASS**, with INFO on the pytest “118 passed” wording (actual **117 passed + 1 skipped**).

---

## Artifacts (this delta)

```
qa/MM-020a/logs/82f2066/   (and DELTA_REPORT.md)
  DELTA_REPORT.md
  harness/delta_verify.py
  harness/xss_message_check.mjs
  logs/…
  screenshots/xss-legacy-10.png
  screenshots/xss-message-11.png
```
