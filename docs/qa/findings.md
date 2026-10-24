# QA findings (Mission 003)

## Current verification

Product integration tested: `07e5b4d`; quota source `c4b95d4`; runtime branch `1449153`;
UI scratch worktree `/tmp/qa-ui-m003` at `98eec80`.

- Required Python QA command: **191 passed, 27 strict xfailed** (218 cases).
- Added after baseline checkpoint: **72 Python cases + 21 frontend cases**.
- Frontend QA: **10 passing invariants + 11 strict expected failures** (`it.fails`, which fails on an unexpected pass).
  A diagnostic run with the expected-failure markers removed verified all 11 fail on the intended assertions.
- UI branch complete suite with QA included: **321 passed** in 36 files, including the 11 expected failures.
  TypeScript check and production build both pass. Existing jsdom canvas warnings do not fail the suite.
- Engineer suites in detached scratch worktrees: quota **55 passed**; runtime **109 passed**.
- `QA-004` is FIXED by runtime integration `a0217a9` (source `1449153`); `QA-006` is FIXED by `07e5b4d`.
  Their six strict xfails were converted to ordinary passing regressions after confirming the fixes.
- All test commands use synthetic inputs/temp state/local git remotes. Frontend fetches are injected Responses;
  no real provider commands, `gh` writes, persistent jobs, or collector ports are used.

| ID | Severity | Current status | Verified behavior |
|---|---|---|---|
| QA-003 | High | OPEN @ 07e5b4d | Email display metadata survives private export |
| QA-009 | High | OPEN @ 07e5b4d | Private manual-source labels reach operational JSON |
| QA-015 | High | OPEN @ 98eec80 | Private metadata passes transport and reaches DOM |
| QA-002 | Medium | OPEN @ 07e5b4d | VERIFIED accepts null observation/expiry |
| QA-005 | Medium | OPEN @ 07e5b4d | Remote feed is read without a size bound |
| QA-007 | Medium | OPEN @ 07e5b4d | Encoded credentials in supplied node IDs survive export |
| QA-008 | Medium | OPEN @ 07e5b4d | Invalid provider resets become VERIFIED windows |
| QA-010 | Medium | OPEN @ 07e5b4d | Five IDs bypass optional quota response validation |
| QA-011 | Medium | OPEN @ 07e5b4d | Stale local epoch adopts a reclaimed same-machine epoch |
| QA-012 | Medium | OPEN @ 07e5b4d | Doctor prints unsupported credential forms |
| QA-013 | Medium | OPEN @ 98eec80 | Forged VERIFIED demo pool renders green VERIFIED state |
| QA-014 | Medium | OPEN @ 98eec80 | Recommendations accept missing/future/stale evidence |
| QA-016 | Medium | OPEN @ 98eec80 | Transport accepts null windows that rendering cannot handle |
| QA-001 | Low | OPEN @ 07e5b4d | Schema accepts duplicate quota IDs |
| QA-004 | Medium | FIXED @ a0217a9 | All five malformed remote-shape regressions pass |
| QA-006 | Medium | FIXED @ 07e5b4d | Future remote timestamp no longer suppresses heartbeat |

The sections below retain original discovery commits and reproduction details. Their historical OPEN labels describe the discovery snapshot; the current table above takes precedence.

Confirmed defects are encoded as **strict xfail** tests in `tests/qa/`; each flips red when fixed. Baseline `d145a98` has 17 expected-failure cases across 7 findings. Phase 2 integration `4502020` has 29 expected-failure cases across 10 findings; all remain OPEN unless stated otherwise.

| ID | Sev | Location | Status |
|----|-----|----------|--------|
| QA-004 | Medium | tools/publish_observability.py:306 | OPEN |
| QA-003 | High | ingest/t3.py:207 (safe_text) | OPEN |
| QA-007 | Medium | ingest/t3.py:254 (safe_ident) | OPEN |
| QA-006 | Medium | tools/publish_observability.py:110-113 | OPEN |
| QA-005 | Medium | tools/publish_observability.py:306 | OPEN |
| QA-002 | Medium | schema/observability.schema.json:82,100-101 | OPEN |
| QA-001 | Low | schema/observability.schema.json:59-61 | OPEN |

## QA-004 Medium (FIXED @ a0217a9) — non-feed remote `latest.json` is overwritten / escapes failure accounting
- Repro: seed remote `latest.json` with `null`, `[]`, `42`, `"text"`, or `{}`; run publish. (`test_non_feed_json_remote_is_rejected`)
- Actual: previous feed is parsed unvalidated (`previous.get(...)` on non-dict raises TypeError/AttributeError, or `{}` is treated as valid) — remote is replaced, or crash bypasses `consecutive_failures`.
- Expected: refuse (PublishError), leave remote head untouched, `consecutive_failures == 1`.
- Fix: validate `isinstance(previous, dict)` and required keys after load; raise PublishError.

## QA-003 High — email addresses published verbatim
- Repro: task/provider/model/project/branch = `qa.person@example.invalid` → appears in latest.json and summary.md. (`test_email_never_leaves_in_either_artifact`)
- Expected: absent from both artifacts.
- Fix: add email regex to `_sensitive_any` / safe_text and safe_ident.

## QA-007 Medium — encoded credentials in node IDs pass `safe_ident`
- Repro: node id `password%3Dsyntheticsecret`, `token%253Dsyntheticsecret`. (`test_encoded_credentials_in_ids_are_not_exported`)
- Expected: dropped. Fix: `safe_ident` must apply `_sensitive_any` over iterated percent-decoding (or forbid `%` in `_IDENT`).

## QA-006 Medium (FIXED @ 07e5b4d) — future remote `exported_at` suspends heartbeat indefinitely
- Repro: previous.exported_at = now+365d; `should_publish(previous, feed, now)` returns False. (`test_future_remote_timestamp_cannot_suspend_heartbeat`)
- Expected: True (clock skew must not silence the feed → viewer sees STALE falsely-fresh gap).
- Fix: treat `exported_at > now + skew_tolerance` as invalid → publish.

## QA-005 Medium — remote `latest.json` has no size bound
- Repro: remote feed with > `MAX_SOURCE_BYTES` padding is fully parsed and replaced. (`test_oversized_remote_feed_rejected`)
- Expected: PublishError, failure counted, remote untouched. Fix: stat/limit-read the remote file before `json.loads`.

## QA-002 Medium — schema accepts VERIFIED pool with null `observed_at`/`expires_at`
- Repro: set either to null on a VERIFIED pool; schema validates. (`test_verified_null_evidence_rejected`)
- Expected: invalid (contract says VERIFIED requires expiry). Fix: `if status==VERIFIED then required non-null` (`allOf`/`if-then`) on pool.

## QA-001 Low — duplicate pool ids accepted
- Repro: pools[1].id = pools[0].id (still 5 items). (`test_duplicate_ids_rejected`)
- Expected: invalid. Fix: `uniqueItems` can't key on id; use `contains` ×5 (one per enum id) or validate in code.

## Phase 2 quota / observability — integration `4502020`, quota `c4b95d4`

Added 45 adversarial cases. The original 17 expected failures remain OPEN on the integrated tree.
Validation: **162 passed, 29 strict xfailed** using the required QA command. The quota engineer's own suites passed **55 tests** separately in detached scratch worktree `/tmp/qa-quota` at `c4b95d4`.

| ID | Severity | Location | Verified status | Cases |
|---|---|---|---|---|
| QA-009 | High | tools/quota/normalize.py:158 | OPEN @ 4502020 / c4b95d4 | 3 |
| QA-008 | Medium | tools/quota/collectors/codex_app_server.py:43; tools/quota/collectors/claude_statusline.py:35 | OPEN @ 4502020 / c4b95d4 | 8 |
| QA-010 | Medium | tools/observability_doc.py:121 | OPEN @ 4502020 | 1 |

### QA-009 — manual source labels leak private strings into `/observability.json`

Repro: `test_manual_source_never_reaches_public_observability`, using a temporary quota directory:
write a manual Devin weekly reading with source `/Users/qa/private`, `qa@example.invalid`, or
`Bearer syntheticcredential123`; call `build_observability(..., quota_dir=tempdir)`.
Each input is copied verbatim into `quota.pools[].source.method` in the returned document.
`clean_text` removes controls/limits length but does not sanitize secrets or paths. This violates the
operational document's explicit no-paths/no-credentials contract. No real credentials are used in the test.
Expected: private strings absent from the composed document. Suggested fix: apply the shared
credential/path sanitizer to all free-text quota metadata before storing/composing; also redact email.
The private publisher's later scan does not protect the independently served observability document.

### QA-008 — malformed non-null reset becomes a current VERIFIED reading

Repro: `test_malformed_provider_reset_cannot_become_verified`: pass a valid percentage with reset
`"not-an-epoch"`, `-1`, `NaN`, or `true` to either Codex's `resetsAt` or Claude's `resets_at` mapper.
Both convert the malformed reset to `None`, retain the window, and `evaluate` reports VERIFIED for 15 minutes.
Expected: reject that malformed window or return UNKNOWN/ERROR; a malformed supplied reset must not be
silently treated as an intentionally absent reset. Suggested fix: distinguish explicit null/absent reset
(supported for Codex) from invalid non-null data before appending a window. Existing null-reset behavior
is not reported as a defect.

### QA-010 — a quota response with only the five IDs bypasses fail-soft validation

Repro: `test_five_ids_without_evidence_degrade_to_valid_unknown`: stub `api.pools` to return
`[{"id": id} for id in POOL_IDS]`, then compose a live document. The result fails the operational schema
because every pool lacks required evidence/status/source fields. Expected: valid UNKNOWN placeholders,
as for other malformed optional sources. Suggested fix: validate returned pools against the contract,
including required fields, before trusting them; otherwise use `unknown_pools` and a fixed diagnostic note.

## Phase 2 runtime — `1449153`

Runtime is reviewed in detached scratch worktree `/tmp/qa-runtime-m003`; it is not merged into the QA branch.
`test_runtime_adversarial.py` uses `pytest.importorskip` and skips until the runtime modules are integrated.
The engineer's five runtime suites passed **109 tests**. Independent runtime attacks: **23 passed, 4 strict xfailed**.

| ID | Severity | Location | Verified status | Cases |
|---|---|---|---|---|
| QA-011 | Medium | tools/publisher_ownership.py:147 | OPEN @ 1449153 (now :156 @ 07e5b4d) | 1 |
| QA-012 | Medium | tools/machine_doctor.py:36 | OPEN @ 1449153 | 3 |

### QA-011 — old generation adopts a higher epoch for the same machine identity

Repro: `test_resurrected_generation_of_same_machine_is_fenced`, using a real local bare git remote.
Mac A publishes at epoch 1; seed a valid epoch-3 owner record for the same stable machine ID (the state
following intervening handovers). Keep the old process's local epoch 1 and publish a changed task.
Actual: `decide` accepts any higher remote epoch when the machine ID matches; the process overwrites
the feed and adopts epoch 3. Expected: epoch 1 cannot write under epoch 3 without an explicit reclaim.
Suggested fix: fence both directions of local/remote epoch mismatch for an ordinary publish; reserve
adopting a newer epoch for the explicit claim path. This is distinct from a foreign-machine takeover,
which the rejected-push/re-clone attack correctly refuses.

### QA-012 — doctor prints credential forms embedded in remote owner labels

Repro: `test_doctor_does_not_print_other_credential_forms`: inject a synthetic remote owner label
containing `password=syntheticsecret`, a Slack `xoxb-...` token, or `Authorization: Basic ...` into the
fake `gh api` response; run `check_feed` and render text/JSON. All three strings survive verbatim.
Expected: credentials absent from both formats even when external metadata contains them.
Suggested fix: use the shared normalization/credential sanitizer for diagnostic text and hints,
including encoded credentials; the current doctor regex covers only GitHub/OpenAI/Bearer examples.
No real `gh` command or remote is accessed by these tests.

Runtime note for QA-004: `load_previous` now rejects non-object JSON (null/list/number/string), and
ownership rejects `{}` as corrupt. The original non-feed-shape cases are **FIXED on runtime `1449153`**
by `test_runtime_rejects_all_original_qa004_remote_shapes` (all five original payloads, real local remote); they remain OPEN on the current integrated QA base.
QA-005's unbounded remote file read remains at runtime `tools/publish_observability.py:311`.

## Phase 2 UI — `98eec80`

New file: `web/src/test/qa-observability-adversarial.test.tsx`. Optional module discovery was verified to skip all 21
UI cases cleanly in a temporary copy of the QA tree before integration; the file compiles on the QA branch and runs in the UI scratch worktree.
No product files were edited. All four findings below are strict Vitest expected failures.

| ID | Severity | Location | Verified status | Cases |
|---|---|---|---|---|
| QA-015 | High | web/src/components/QuotaPanel.tsx:126; web/src/utils/observabilityEval.ts:139 | OPEN @ 98eec80 | 3 |
| QA-013 | Medium | web/src/components/QuotaPanel.tsx:188; web/src/utils/observabilityEval.ts:41 | OPEN @ 98eec80 | 1 |
| QA-014 | Medium | web/src/utils/recommendations.ts:91,209 | OPEN @ 98eec80 | 6 |
| QA-016 | Medium | web/src/utils/observabilityEval.ts:138 | OPEN @ 98eec80 | 1 |

### QA-015 — accepted operational metadata reaches the DOM with private strings intact

Repro: the transport-to-DOM tests return a synthetic operational document with source method
`/Users/qa/private`, `qa@example.invalid`, or `Bearer syntheticcredential123` via an injected fetch Response.
The production transport returns `kind: "ok"`; render its document through `QuotaPanel`.
Each value remains in the DOM. Expected: reject or redact private metadata before rendering.
Suggested fix: validate/sanitize externally supplied operational free-text fields at the transport boundary,
with the same privacy contract as the backend. React escaping prevents HTML execution but does not prevent
private text exposure. This confirms the UI propagation path independently of QA-009's manual collector input.

### QA-013 — demo mode does not override a forged VERIFIED status

Repro: clone live-mixed, change `mode` to `demo`, render at its current fixture time. The DEMO banner
appears alongside green VERIFIED badges and `data-status="VERIFIED"` cards.
Expected: demo data never claims verified readings, even for conflicting input fields.
Suggested fix: reject conflicting demo documents or downgrade their pools to illustrative/manual state
before rendering. Recommendations correctly refuse demo mode; the defect is the quota presentation.

### QA-014 — recommendations bypass essential evidence gates

Repro: leave only Codex eligible in a live-mixed document with fresh activity; independently set:
all percentages null; expiry null; observation null; observation one day in the future; collector poll
one day in the future; or document generation one day old. All six return `RECOMMENDATIONS`.
Expected: `INSUFFICIENT_DATA` with no candidates in each case.
Suggested fix: require finite numeric headroom plus valid current observation/expiry, reject future
evidence beyond a defined clock tolerance, and enforce `evaluateObservability().documentStale`.
The current eligibility function checks status/window count/reset/upper threshold but lacks these gates.

### QA-016 — malformed window contents pass the production transport

Repro: put `[null]` in Codex `windows`; the injected production transport returns `kind: "ok"`.
Expected: `kind: "rejected"`; null is not a schema-valid window. The panel subsequently accesses
`w.resets_at` in `evaluatePool`, so this accepted shape is unsafe to render.
Suggested fix: validate each window's object shape, values, timestamps and bounds before accepting the
payload; return the fixed rejection reason instead of passing malformed data to components.
