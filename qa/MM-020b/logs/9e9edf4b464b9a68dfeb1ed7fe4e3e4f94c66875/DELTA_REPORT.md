# QA Delta Report — MM-020b / PR #17 @ `9e9edf4`

| Field | Value |
|-------|-------|
| **Verdict** | **PASS** |
| **Target SHA** | `9e9edf4b464b9a68dfeb1ed7fe4e3e4f94c66875` (`9e9edf4`) |
| **Prior FAIL SHA** | `692216de5f944a870887bc7bf37779f618797cc2` (`692216d`) |
| **Base** | `feat/MM-020-unified-network` (includes MM-020a fix, MM-020c `#18`, MM-020f `#19`) |
| **PR** | https://github.com/ManpreetS2/agent-mindmap/pull/17 (draft) |
| **Head moved?** | Yes — prior FAIL `692216d` → `9e9edf4` (rebased onto shared `tools/secret_scan.py`) |
| **Environment** | Linux 6.12.94+; Python 3.12.3; Node v22.23.3 |
| **Fresh checkout** | `/tmp/qa-mm020b-delta/checkout` @ `9e9edf4` |
| **Evidence branch** | `qa/MM-020b` |
| **Date** | 2026-10-20 |

Verify-only: no product edits; no push to `feat/MM-020b`; no PR comments; no merge; no new PR.

Prior FAIL report read: `qa/MM-020b/REPORT.md` @ `849f359` (FAIL @ `692216d` — preexisting modes, secret denylist gaps, unknown recipients).

---

## Verdict summary

Prior FAIL findings **QA-MM020b-1/2/3** are closed by behavioral tests. Earlier SEC fixes (symlink / `O_NOFOLLOW` / new-file `0o600` / 240-char cap / docstring) still hold. Suites and CI are green on `9e9edf4`. MM-020a / 020c / 020f smoke on this feature branch shows no regressions.

---

## Requested checks

### (1) QA-MM020b-2 — shared `tools/secret_scan.py` refusal — **PASS**

| Field | Value |
|-------|-------|
| **component** | `tools/event_emit.py` → `tools.secret_scan.looks_like_secret` |
| **expected** | Summaries with `sk-`, `AKIA`, JWT, PEM, email, `ghp_`, Bearer refused via **shared** scanner; no local pattern copy; benign `task-runner` / `risk-based` / `Mask-RCNN` pass |
| **actual** | All listed secret payloads → `SecretRefusedError`, nothing written. `event_emit.py` imports shared scanner only (no `re.compile` / `_RULES`). Benign words emit successfully. |
| **repro** | `harness/delta_verify_mm020b.py` `check_secrets_shared_and_refuse` |
| **evidence** | `logs/delta_harness.txt`, `logs/delta_harness_results.json` |
| **severity** | n/a (fixed) |
| **confidence** | high |

Note: `sk-` match requires the shared rule `\bsk-[A-Za-z0-9_-]{20,}` (case-sensitive). Short `sk-` alone is not in the denylist; QA exercised a ≥20-char `sk-…` token as in SEC-MM020c-1.

### (2) QA-MM020b-1 — preexisting JSONL mode — **PASS (tightened to 0o600)**

| Field | Value |
|-------|-------|
| **component** | `tools/event_emit._open_jsonl_append` (`fchmod` on existing files) |
| **expected** | Preexisting `0o644` / `0o666` tightened to `0o600` **or** refused |
| **actual** | **Tightened to `0o600`** for both `0o644` and `0o666` after successful append (not refused) |
| **repro** | delta harness + prior `test_sec_mm020b_behavioral.py` preexisting tests |
| **evidence** | `logs/delta_harness.txt` (`outcomes={'0o644': 'tightened_to_0o600', '0o666': 'tightened_to_0o600'}`), `logs/sec_behavioral_run.txt` |
| **confidence** | high |

### (3) QA-MM020b-3 — unknown recipients — **PASS (flagged, not hard-refused)**

| Field | Value |
|-------|-------|
| **component** | `build_network_event` / `_partition_recipients` |
| **expected** | Unknown recipients flagged or refused |
| **actual** | **Flagged**: known stay in `recipients`; unknowns go to `unknown_recipients`; WARNING logged (`unknown recipient id(s)…`). Emit still succeeds. `@mentions` still not inferred. |
| **repro** | delta harness `check_unknown_recipients`; unit `test_unknown_recipients_partitioned_and_logged` |
| **evidence** | `logs/delta_harness.txt` |
| **confidence** | high |

### (4) Earlier SEC fixes still hold — **PASS**

| Check | Result | Evidence |
|-------|--------|----------|
| Symlink path refused; target untouched | PASS | delta + sec behavioral |
| `O_NOFOLLOW` on open (`sys.audit`, flags `0xa0441`) | PASS | delta + sec behavioral |
| New file mode `0o600` | PASS | delta + sec behavioral |
| 240-char cap (239/240/241) + multibyte/emoji | PASS | delta + sec behavioral |
| Module docstring states 240 contract | PASS | `SUMMARY_MAX_CHARS (240)` in `__doc__` |
| Refuse-not-redact (no file / no secret echo) | PASS | delta + sec behavioral |

Prior SEC unittest suite @ this head: **9/9 OK** (`logs/sec_behavioral_run.txt`).

### (5) Exact test counts + CI — **PASS**

| Suite | Exact local @ `9e9edf4` | Exact CI @ `9e9edf4` |
|-------|-------------------------|----------------------|
| pytest | **175 passed, 1 skipped** (176 collected) | **175 passed, 1 skipped** (176 collected) — run [39397625333](https://github.com/ManpreetS2/agent-mindmap/actions/runs/39397625333) |
| vitest | **81 passed** (18 files) | **81 passed** — run [39397625225](https://github.com/ManpreetS2/agent-mindmap/actions/runs/39397625225) |
| tsc root + web / build | clean / success | web job includes typecheck+build success |

CI checks: `logs/ci_checks.txt` — pytest **pass**, web **pass**, `headSha=9e9edf4…`.

(Prior FAIL claim was 123 passed; count rose after rebase onto 020a/c/f + emitter tests — report exacts above, not the old claim.)

### (6) No regressions vs MM-020a / 020c / 020f on feature branch — **PASS**

| Area | Result | Evidence |
|------|--------|----------|
| MM-020a membership dedupe + park unknowns | PASS | harness smoke; `tests/test_mm020a_membership.py` in scoped run |
| MM-020c `tools/events_mirror.py` + `events_fetch` + shared scanner | PASS | imports `tools.secret_scan`; `tests/test_events_mirror.py` + `test_events_fetch.py` + `test_secret_scan.py` green |
| MM-020f message/group UI | PASS | `MessageEdge.tsx`, `GroupAnchorNode.tsx`, `groupMembership.ts` present; `edgeTypes` vitest **6 passed**; full web **81 passed** |
| Scoped pytest (020a/b/c secret+emit+mirror+fetch) | **77 passed** | `logs/pytest_scoped_regressions.txt` |

Note: `createSseTransport` is **not** present (SSE remains MM-020d). Not treated as 020f regression on this branch.

---

## Findings @ `9e9edf4`

**No blocking findings.**

### Informational

| ID | Note |
|----|------|
| QA-MM020b-1 disposition | Preexisting modes are **tightened to 0o600** (not refused). |
| QA-MM020b-3 disposition | Unknowns are **flagged** (`unknown_recipients` + warning), not hard-refused. |
| Prior FAIL F1/F2/F3 | **Resolved** relative to `692216d` report. |

---

## Suite transcripts (exact)

```
pytest: 175 passed, 1 skipped in 4.55s   (176 collected)
vitest: 81 passed (18 files)
delta harness: 17/17 ok
prior SEC behavioral: 9/9 OK
scoped regressions: 77 passed
CI pytest: success @ 9e9edf4 (39397625333)
CI web:    success @ 9e9edf4 (39397625225)
```

---

## Verdict rationale

Behavioral re-verify closes the three prior FAIL items against the shared secret scanner rebase. Earlier SEC contract holds; CI/suites green; 020a/c/f smoke clean. **PASS**.

---

## Artifacts

```
qa/MM-020b/DELTA_REPORT.md
qa/MM-020b/logs/9e9edf4…/
  DELTA_REPORT.md
  harness/delta_verify_mm020b.py
  harness/test_sec_mm020b_behavioral.py
  logs/…
```
