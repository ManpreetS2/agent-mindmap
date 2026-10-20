# QA Report — MM-020a / PR #16

> **Delta re-verify @ `82f2066`:** **PASS** — see [`DELTA_REPORT.md`](DELTA_REPORT.md) and [`logs/82f20667ea2a2336701ed549a7caaa77fc0c2249/DELTA_REPORT.md`](logs/82f20667ea2a2336701ed549a7caaa77fc0c2249/DELTA_REPORT.md).  
> Prior FAIL at `b1fe594` remains below as historical baseline.

---

# QA Report — MM-020a / PR #16 (baseline FAIL @ b1fe594)

| Field | Value |
|-------|-------|
| **Verdict** | **FAIL** |
| **Target SHA** | `b1fe594ec72086a1b025a7b137213b9632f35920` (`b1fe594`) |
| **Base (main)** | `1a3a0cc684f518705abd4148d42f1a46666cbd25` (`1a3a0cc`) |
| **PR** | https://github.com/ManpreetS2/agent-mindmap/pull/16 (draft) |
| **Head moved?** | No — still `b1fe594` as requested |
| **Environment** | Linux 6.12.94+ (Cloud Agent VM); Python 3.12.3; Node v22.23.3; Playwright Chromium 131 |
| **Fresh checkout** | `/tmp/qa-mm020a/checkout` (detached worktree @ `b1fe594`) |
| **Evidence branch** | `qa/MM-020a` |
| **Date** | 2026-10-20 |

Independent QA: no product code edits; no push to `feat/MM-020-unified-network`; no GitHub PR comments; no merge; no QA PR opened.

---

## Verdict summary

Suites and CI are green, multi-membership / message edges / migration / XSS mostly hold, but **duplicate `groups.json` members are not handled** (AC miss). That blocks **PASS**. Secondary gaps: unknown member ids are silently indexed; `derive_edges` alone is not event-id idempotent (build merge path is).

---

## Acceptance sources

- PR #16 body (MM-020a claims: groups.json, schema 1.1.0, message edges, provenance optional, migration of 1.0.0 fixtures, 113 pytest / 56 vitest)
- `docs/MM-020-audit.md` §6–§7 (MM-020a row + NetworkEvent / migration)
- Prior invariants: QA-MM004 merge self-loops / `(repo, number)` / merger attribution; QA-MM011 secret posture (no tokens in committed activity; write-path scan still mirror-only — class of F3)
- Verifier scope: membership edge cases, message edges, provenance, migration, XSS with message payloads

Note: `build/mindmap/architecture.md` is not in this repo (same as prior QA); README still cites “architecture §7”.

---

## Checks @ `b1fe594`

| Check | Result | Evidence |
|-------|--------|----------|
| `python3 -m pytest -q` | **112 passed, 1 skipped** (113 collected) | `logs/pytest.txt`, `logs/pytest-collect.txt` |
| PR claim “113 passed” | **Claim nit** — CI also prints `112 passed, 1 skipped` | `logs/ci_checks.txt`, GH run 39393249586 |
| `cd web && npm test` (vitest) | **56 passed** (14 files) | `logs/vitest.txt` |
| `npm run typecheck` (root + web) | clean | `logs/typecheck-root.txt`, `logs/typecheck-web.txt` |
| `cd web && npm run build` | success | `logs/build.txt` |
| CI pytest @ head | **success** | run 39393249586 |
| CI web @ head | **success** | run 39393249493 |
| Schema validates all 1.0.0 fixtures + built 1.1.0 | PASS | `logs/schema_fixtures.txt` |
| `groups.json` happy path (Build / Q&R / Research; Bug fixer out) | PASS | `logs/harness.txt`, `logs/pytest-mm020a.txt` |
| Director/Architect multi-membership; one id each in bots.json | PASS | harness + unit tests |
| Unknown member id | OBSERVED — silent index, no raise | harness `membership.unknown_member` |
| Duplicate member id in one group | **FAIL** | harness; `extra_probes.txt` → `director.groups=['build','build',…]` |
| Missing member (bot not listed) | PASS → `[]` | harness |
| Malformed `groups.json` (bad JSON) | PASS → `JSONDecodeError` | harness |
| Message edge untargeted → `sender→group:{id}` | PASS | harness / unit |
| Message edge explicit recipients only; never invent | PASS | harness / unit |
| Message self-loop suppressed | PASS | harness |
| Message cross-event dedup `(source,target,type)` | PASS (count↑) | harness |
| Message same `event_id` twice via `derive_edges` | FAIL alone; **PASS via `merge_events`** | `logs/build_idempotency.txt` |
| Legacy: no merge self-loop; `(repo,number)` join; merger not from unknown | PASS | harness + `tests/test_build.py` |
| Provenance enum on NetworkEvent; optional on activity events | PASS (by design) | schema + harness |
| Ledger text cannot spoof provenance / invent message recipients | PASS | harness |
| Secrets in fixtures / built activity (`_looks_like_secret`) | PASS | harness |
| Activity write path does not strip Bearer in `raw` | INFO (same class as QA-MM011 F3) | harness |
| Migrate `1a3a0cc` sample lossless + idempotent | PASS | harness |
| Unknown / future `schema_version` → clear `ValueError` | PASS | harness |
| UI loads 1.0.0 and 1.1.0 (message) without crash | PASS | `logs/ui_load_compat.txt`, `screenshots/ui-*.png` |
| XSS with message / label payloads (legacy + 1.1.0) | PASS (no execution) | `logs/xss_message_results.json`, `screenshots/xss-*.png` |

Machine-readable harness: `logs/harness_results.json`.

---

## Findings

### QA-MM020a-1 — Duplicate `groups.json` members not deduped (MEDIUM) — **blocks PASS**

| Field | Value |
|-------|-------|
| **component** | `ingest/membership.py` `membership_index` / `build_nodes` |
| **expected** | Duplicate member ids in a group are handled (dedupe or clear validation error) |
| **actual** | `members: ["director", "ghost-bot", "director"]` → `index["director"] == ["build","build"]`; built node `groups` lists `build` twice |
| **repro** | Load a groups cfg with a repeated member; call `membership_index` / `build_nodes` (see `harness/verify_mm020a.py`) |
| **evidence** | `logs/harness.txt`, `logs/extra_probes.txt`, `logs/harness_results.json` |
| **environment** | Linux VM, Python 3.12.3, head `b1fe594` |
| **severity** | medium |
| **confidence** | high |

### QA-MM020a-2 — Unknown member ids accepted silently (LOW)

| Field | Value |
|-------|-------|
| **component** | `ingest/membership.py` |
| **expected** | Unknown members handled (skip/warn/fail clearly vs bots.json) |
| **actual** | Unknown id (e.g. `ghost-bot`) is indexed; no node is created for it; no error |
| **repro** | Append a non-bot id to `groups[].members`; call `membership_index` |
| **evidence** | `logs/harness_results.json` `membership.unknown_member` |
| **environment** | same |
| **severity** | low |
| **confidence** | high |

### QA-MM020a-3 — `derive_edges` event-id idempotency (INFO / mitigated)

| Field | Value |
|-------|-------|
| **component** | `ingest/edges.py` `add_edge` |
| **expected** (strict) | Same event `id` twice → one edge listing / animation (audit §8.2) |
| **actual** | `derive_edges([e,e])` → `count=2`, `event_ids=['m4','m4']`. Pre-existing for handoff too. **`merge_events` in build dedupes by id first**, so assemble path is idempotent. |
| **repro** | See `logs/build_idempotency.txt` |
| **evidence** | `logs/build_idempotency.txt`, harness `message.idempotent_same_event_id` |
| **severity** | info (live stream dedupe remains MM-020d) |
| **confidence** | high |

### QA-MM020a-4 — Provenance model vs “every node and edge carries its source” (INFO)

| Field | Value |
|-------|-------|
| **component** | `schema/activity.schema.json`, `ingest/build.py` |
| **expected** (literal verifier wording) | Every node and edge carries its source / provenance |
| **actual** | `provenance` is **required** on `$defs/networkEvent`, **optional** on activity events, **absent** on nodes/edges. Events always require `source_url`. Built 1.1.0 ledger/GitHub events have **no** `provenance` field set. Edges link via `event_ids`. Matches additive MM-020a design; full live provenance is later workstreams. |
| **evidence** | harness `provenance.*`, `logs/schema_fixtures.txt` |
| **severity** | info |
| **confidence** | high |

### QA-MM020a-5 — PR test-count wording (INFO)

| Field | Value |
|-------|-------|
| **component** | PR #16 body |
| **expected** | Accurate count |
| **actual** | Body: “113 passed, 1 skipped”. Observed/CI: **112 passed, 1 skipped** (113 collected). |
| **evidence** | `logs/pytest.txt`, CI run 39393249586 |
| **severity** | info |
| **confidence** | high |

---

## Scope notes (not blockers for 020a)

- UI legend still lists four edge types; `message` styled for compile-only (`edgeStyles.ts` comment → MM-020f).
- Group target nodes (`group:build`) are not first-class graph nodes yet (MM-020f).
- SEC-MM011-1 Host/Origin remains deferred to MM-020d (out of 020a product scope).

---

## Verdict rationale

Happy-path membership, schema 1.1.0 back-compat, message edge rules, migration, secrets scan of fixtures, XSS, and CI all pass. **FAIL** because AC requires duplicate members to be handled, and they are not (`QA-MM020a-1`).

---

## Artifacts on `qa/MM-020a`

```
qa/MM-020a/
  REPORT.md
  harness/verify_mm020a.py
  harness/xss_message_check.mjs
  logs/…
  screenshots/ui-legacy-clean.png
  screenshots/ui-v11-message-clean.png
  screenshots/xss-legacy-10.png
  screenshots/xss-message-11.png
```
