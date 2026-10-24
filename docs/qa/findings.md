# QA findings (Mission 003)

All findings below are encoded as **strict xfail** tests in `tests/qa/` (17 xfail cases = 7 findings); each flips red when fixed. Status as of baseline `d145a98`: all OPEN.

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
