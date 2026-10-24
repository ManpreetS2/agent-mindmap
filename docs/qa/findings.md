# QA findings (Mission 003)

Confirmed defects are encoded as **strict xfail** tests in `tests/qa/`; each flips red when fixed. Baseline `d145a98` has 17 expected-failure cases across 7 findings. Phase 2 integration `4502020` has 29 expected-failure cases across 10 findings; all remain OPEN unless stated otherwise.

| ID | Sev | Location | Status |
|----|-----|----------|--------|
| QA-004 | High | tools/publish_observability.py:306 | OPEN |
| QA-003 | High | ingest/t3.py:207 (safe_text) | OPEN |
| QA-007 | High | ingest/t3.py:254 (safe_ident) | OPEN |
| QA-006 | Medium | tools/publish_observability.py:110-113 | OPEN |
| QA-005 | Medium | tools/publish_observability.py:306 | OPEN |
| QA-002 | Medium | schema/observability.schema.json:82,100-101 | OPEN |
| QA-001 | Low | schema/observability.schema.json:59-61 | OPEN |

## QA-004 High — non-feed remote `latest.json` is overwritten / escapes failure accounting
- Repro: seed remote `latest.json` with `null`, `[]`, `42`, `"text"`, or `{}`; run publish. (`test_non_feed_json_remote_is_rejected`)
- Actual: previous feed is parsed unvalidated (`previous.get(...)` on non-dict raises TypeError/AttributeError, or `{}` is treated as valid) — remote is replaced, or crash bypasses `consecutive_failures`.
- Expected: refuse (PublishError), leave remote head untouched, `consecutive_failures == 1`.
- Fix: validate `isinstance(previous, dict)` and required keys after load; raise PublishError.

## QA-003 High — email addresses published verbatim
- Repro: task/provider/model/project/branch = `qa.person@example.invalid` → appears in latest.json and summary.md. (`test_email_never_leaves_in_either_artifact`)
- Expected: absent from both artifacts.
- Fix: add email regex to `_sensitive_any` / safe_text and safe_ident.

## QA-007 High — encoded credentials in node IDs pass `safe_ident`
- Repro: node id `password%3Dsyntheticsecret`, `token%253Dsyntheticsecret`. (`test_encoded_credentials_in_ids_are_not_exported`)
- Expected: dropped. Fix: `safe_ident` must apply `_sensitive_any` over iterated percent-decoding (or forbid `%` in `_IDENT`).

## QA-006 Medium — future remote `exported_at` suspends heartbeat indefinitely
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
| QA-011 | High | tools/publisher_ownership.py:147 | OPEN @ 1449153 | 1 |
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
