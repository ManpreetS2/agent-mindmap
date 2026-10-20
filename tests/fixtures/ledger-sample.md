# Build Division Task Ledger

Shared by BUILD DIVISION and QUALITY & RELEASE. Owner: Director.

| Task ID | Project | Owner | Mode | Model | Status | Evidence |
|---|---|---|---|---|---|---|
| BD-000 | setup handoff test | DEV 1 | none | none | DONE (ack received) | - |
| QR-000 | Q&R handoff test | QA, Security, DevOps | none | none | DONE (all 3 acked) | - |
| RP-001 | FENCEPOST: repo scaffold (dirs, hash-locked deps, .gitignore, CI lint+unit) | DEV 2 | REMOTE_CONTROL (MacBook Pro) | composer-2.5 (CLI --model composer-2.5) | DONE (merged) | PR https://github.com/ManpreetS2/fencepost/pull/1 squash-merged as 06ec61c; commits: bootstrap 07eda25 (main), 90e5381 (CI push->main, DEVOPS-RP001-1), 034a441 (Apache-2.0, setuptools>=77); chat ec3b93be-26b7-4cd6-8ff5-03dd423dafd2 |
| RP-002 | FENCEPOST: contracts (manifest, result, fault hook) | Architect | REMOTE_CONTROL (MacBook Pro) | Composer 2.5 Standard (REPLACED by CLI --model pin (Director, 8:45 PM PDT)) | PR #2 MERGED as bbdfc44; follow-up RP-002a PR #4 IN_REVIEW (not merged; head 24513dd; CI 39369249291 green, 9:24 PM PDT; run_id UUID pattern + optional invalid_reason; same chat, composer-2.5) | spec: build/tasks/RP-002.md; --model composer-2.5; Cursor chat 6c40b216-2119-42cd-a33a-8f93ac03e28c; branch feat/RP-002-contracts; +dev dep jsonschema 4.26.0 relocked w/ hashes; 8 tests pass; LOCK pending merge SHA, before RP-004..006 |
| RP-003 | FENCEPOST: compose stack PG17.11/Kafka4.3 KRaft/Connect4.3.1+Dbz3.7.0 & 3.6.3 | DEV 2 | REMOTE_CONTROL (MacBook Pro) | cursor-grok-4.5-high (Architect auth 8:58 PM PDT) | IN_REVIEW | PR https://github.com/ManpreetS2/fencepost/pull/3 (head c50cda2, CI run 39370111665 green, 1 run); broker 4.3.1; SEC-RP003-1 random POSTGRES_PASSWORD; EXTERNAL listener + host consume; pass bar green dbz370 + dbz363; #8273 not in v3.7.0.Final; chat ec3b93be-26b7-4cd6-8ff5-03dd423dafd2 |
| RP-004 | FENCEPOST: workload generator | DEV 1 | REMOTE_CONTROL (MacBook Pro) | Composer 2.5 Standard (REPLACED by CLI --model pin (Director, 8:45 PM PDT)) | PLANNED | spec: build/tasks/RP-004.md; seed-deterministic manifest; txn logical msgs + same-LSN batches |
| RP-005 | FENCEPOST: oracle + report | DEV 1 | REMOTE_CONTROL (MacBook Pro) | Composer 2.5 Standard (REPLACED by CLI --model pin (Director, 8:45 PM PDT)) | PLANNED | spec: build/tasks/RP-005.md; FAIL on gap/phantom/state; dups counted exact; per-pk order; QA planted gap caught |
| RP-006 | FENCEPOST: fault hook kill Connect after N | DEV 2 | REMOTE_CONTROL (MacBook Pro) | Composer 2.5 Standard (REPLACED by CLI --model pin (Director, 8:45 PM PDT)) | PLANNED | spec: build/tasks/RP-006.md; kill at exactly N; restart within timeout; offset logged |
| RP-007 | FENCEPOST: dbz#2889 repro (2-week checkpoint) | DEV 1 | REMOTE_CONTROL (MacBook Pro) | Composer 2.5 Standard (REPLACED by CLI --model pin (Director, 8:45 PM PDT)) | PLANNED | spec: build/tasks/RP-007.md; FAIL+gap on 3.7.0 in >=3/5 seeded runs; env recorded; QA rerun |
| RP-008 | FENCEPOST: README repro steps (after RP-007) | Documentation | REMOTE_CONTROL (MacBook Pro) | Composer 2.5 Standard (REPLACED by CLI --model pin (Director, 8:45 PM PDT)) | PLANNED | spec: build/tasks/RP-008.md; macOS primary from real run; WSL2/Linux UNVERIFIED |

Active coding workers: 0 of 2. Cloud sessions: 0 of 1. Usage: UNKNOWN.

FENCEPOST repo: ManpreetS2/fencepost (approved, CREATED (ManpreetS2/fencepost, private; bootstrap 07eda25)). Sequencing: max 2 active coding workers; RP-001 + RP-002 first, then RP-003/RP-004, then RP-005/RP-006, then RP-007, then RP-008.

## Roster notes (Oct 19 2026, 8:40 PM PDT)
- UI/UX Maker: approved backup coder and co-lead for DEV 1 and DEV 2. Codes only when a slot is free (2-worker cap) and only on tasks Architect assigns. Specs win over chat direction.
- Repo ManpreetS2/fencepost created (private, empty), Oct 19 2026.
- Models: Composer 2.5 Standard for simple tasks, Grok 4.5 High (non-Fast) for complex ones. Never Fast or Auto.
- One Cursor chat per bot per project, kept end to end. Never start a new one.
- UPDATE 8:41 PM PDT (Manpreet): the 2-coder cap covers the developers (DEV 1, DEV 2). UI/UX Maker sits outside the cap as the backup coder for UI work, so at most 3 can code at once.

- 2026-10-19 8:45 PM PDT Director: one-time exception approved. DEV 2 may push a single bootstrap commit to main in ManpreetS2/fencepost (README.md "# fencepost" only), because the repo is empty and PRs need a base branch. All later work goes through PRs, with no pushes to main.
- 2026-10-19 8:49 PM PDT DEV 2 project Cursor chat ID: ec3b93be-26b7-4cd6-8ff5-03dd423dafd2 (resume for all DEV 2 tasks). Bootstrap commit 07eda25 pushed to main (README "# fencepost" only).

- 2026-10-19 8:49 PM PDT: RP-001 PR #1 is open with CI green. Architect review PASS. DevOps review QR-RP001-DEVOPS is pending. DEV 2 chat ec3b93be-26b7-4cd6-8ff5-03dd423dafd2. Merge is waiting on the owner.
- 2026-10-19 8:59 PM PDT DEV 2: RP-003 GO received; MacBook-Pro-2.local unreachable on 4 tries over ~2.5 min (desktop app offline). Nothing started: no branch, no agent call. RP-003 BLOCKED_CONNECTION.

- 2026-10-19 8:58 PM PDT, Architect: AUTHORIZED in writing to run RP-003 on `cursor-grok-4.5-high` (non-fast). This replaces Composer 2.5 for RP-003 because it's a complex Docker and Compose task. If the CLI doesn't have that exact ID, fall back to `composer-2.5`. Never use -fast or auto.
- 2026-10-19 8:58 PM PDT Director: Written authorization for RP-003 (Compose stack, complex) to run on cursor-grok-4.5-high, never the Fast variant. RP-001 is DONE (squash 06ec61c, Apache-2.0). RP-003 is BLOCKED_CONNECTION: the Mac went offline about 8:55 PM PDT, and the owner was notified.
- 2026-10-19 9:13 PM PDT DEV 2: BLOCKED_CONNECTION cleared; RP-003 IN_PROGRESS on branch feat/RP-003-compose-stack from 06ec61c, model --model cursor-grok-4.5-high, chat ec3b93be-26b7-4cd6-8ff5-03dd423dafd2.
- 2026-10-19 9:20 PM PDT DEV 2: RP-003 IN_REVIEW, PR #3 (3c32671), model --model cursor-grok-4.5-high, REMOTE_CONTROL. Pushed before 9:45 deadline; no WIP checkpoint needed.

- 2026-10-19 9:20 PM PDT, Architect: RP-002 is DONE and LOCKED. PR #2 was squash-merged as bbdfc44 after Architect and QA (QR-RP002-QA) both passed it. Contracts v1.0.0 are locked; the canonical array name is `transactions` (the `txns` in contracts-plan.md is outdated). QA-RP002-1 (run_id isn't enforced as a UUID) is ACCEPTED LOW: RP-004 generates UUID4 values, and RP-005 validates with a FormatChecker. QA-RP002-2 (extra files) is SIGNED OFF.
- 2026-10-19 9:20 PM PDT Director: RP-009 (run-report spec) is assigned to UI/UX Maker. The deliverable is docs/design/run-report.md in the repo, on its own branch, spec only. RP-003 is IN_REVIEW as PR #3 (3c32671) and needs an independent Q&R cold-start rerun. The 9:50 cloud switch is ON HOLD until the owner decides on billing.
- 2026-10-19 9:21 PM PDT, Architect CORRECTION: the canonical array name is `txns` (as in the merged schema and the plan), not `transactions`. RP-004 and RP-005 build against `txns`. QA-RP002-1 is being fixed in RP-002a (UUID pattern), and the contracts lock waits on RP-002a merging.
- 2026-10-19 9:21 PM PDT Director: The run-report spec task ID is RP-005D (Architect). RP-009 is withdrawn. Branch docs/RP-005D-run-report-spec.
- 2026-10-19 9:22 PM PDT, Architect: RP-004 is GO for DEV 1 on CLOUD from 9:50 PM, on branch feat/RP-004-workload-generator. AUTHORIZED in writing for cursor-grok-4.5-high (non-fast), because of the seeded determinism and txid/LSN capture.
- 2026-10-19 9:25 PM PDT, Architect: RP-002a DONE. PR #4 was squash-merged as c2ac9fe after QA passed it (QR-RP002a-QA). CONTRACTS v1.0.0 are LOCKED at c2ac9fe, and this is the lock SHA. invalid_reason stays optional in the schema, but RP-005 must set it whenever the verdict is INVALID.
- 2026-10-19 9:33 PM PDT DEV 2: RP-003 PR #3 new head c50cda2 (broker 4.3.1, SEC-RP003-1 random password, Kafka EXTERNAL listener 127.0.0.1:${KAFKA_PORT}, README Limitations). CI run 39370111665 green, 1 run. Stack down -v, Mac clean for QA cold-start rerun. Still LOCAL / REMOTE_CONTROL.
- 2026-10-19 9:33 PM PDT, Architect: README.md added to RP-003's allowed files (Limitations note). PR #3 head is c50cda2 and is waiting on the QA cold rerun plus the Security/DevOps re-verifies.

- 2026-10-19 21:35 PDT: CLOUD SWITCH executed early per Manpreet directive. All bots on Cursor Cloud, one cloud chat per bot, composer-2.5 / cursor-grok-4.5-high only (no Fast/Auto). All prior limits retained. 9:50 routine deleted. Verification pending.
- 2026-10-19 21:36 PDT: Cloud switch VERIFIED. DEV1 bc-9f84dbdb grok-4.5-high (RP-004); UI/UX bc-38cbaa23 composer-2.5 (RP-009); all others idle cloud-ready. QA RP-003 cold rerun stays on Mac (Docker exception).
- 2026-10-19 9:37 PM PDT, Architect: RP-003 DONE. PR #3 was squash-merged as cedbc2c after Architect, QA (cold start, both profiles, consume from the Mac itself), DevOps and Security all passed it. Backlog: QA-RP003-1 (stack-up.sh falls back to docker --network host when kcat is missing; replace with a consumer on the Mac itself), QA-RP003-2 (INFO), SEC-RP003-3 (least-privilege replication role). RP-006 (DEV 2) is now unblocked.
- 2026-10-19 9:39 PM PDT, Architect: RP-009 DONE. PR #5 was squash-merged as 693ebc7 after Architect and QA passed it. Note for RP-005: the spec example's arithmetic is off; the correct relation is event_count = ground_truth - gaps + duplicates (49824 in the example).
- 2026-10-19 9:40 PM PDT, Architect: CORRECTION to the RP-005 count rule, per QA. Phantom events (in Kafka with no ground-truth row) also add to the count: event_count = ground_truth_count - gaps + duplicates + phantoms.
- 2026-10-19 9:51 PM PDT, Architect: PR #7 (RP-006) at f476f14 has passed Architect review, Security and DevOps, and is waiting on QA's Mac run. Backlog OPS-RP006-1 (LOW): without .venv, stack-up step (f) falls back to python3, which lacks kafka-python and fails with a misleading 'marker not found' error. Fix: pre-check the import and give a clear error. Owner: DEV 2, as a follow-up.
- 2026-10-19 21:58 PDT, Architect: MINDMAP §10 rulings recorded in build/mindmap/architecture.md (gh api read-only, structured notes adopted, one ledger line per handoff).
- 2026-10-19 21:59 PDT, Architect: MM-001 IN_PROGRESS (schema, types, bots config, fixture), cloud bc-6c5db6e1-a95b-5e8e-abbf-34b1bf7f0965, composer-2.5, branch feat/MM-001-schema. This is Architect's single MINDMAP cloud chat, to be reused for MM-002 through MM-004.
- 2026-10-19 22:11 PDT, Architect: MM-001 (agent-mindmap PR #1 at 5e8f8b6) is READY_TO_MERGE: Architect, QA and Security all PASS. The merge is blocked because the approval card can't be shown in a group room, so Manpreet's approval in the 1:1 is needed. Backlog SEC-MM001-1 (LOW): hash-lock the Python dev extras.
- 2026-10-19 22:15 PDT, Architect: MM-005 (agent-mindmap PR #2 at bab0058): DevOps PASS on config. Backlog OPS-MM005-1 (LOW): add 'permissions: contents: read' to web.yml. Before merging, wait for CI to be green plus the QA and Security verdicts.
- 2026-10-19 22:15 PDT, Architect: MM-005: Security CONDITIONAL (non-blocking), accepted. Backlog SEC-MM005-1 (MEDIUM), owner UI/UX Maker, to be done right after MM-005 merges: upgrade dev tooling to vite 8 and vitest 4 (current versions have high/critical npm audit findings, dev-only, mitigated by the 127.0.0.1 bind).
- 2026-10-19 22:20 PDT, Architect: MM-005 (agent-mindmap PR #2 at 0e5a60e) has passed Architect, QA, Security (CONDITIONAL) and DevOps, and CI is green. It is READY_TO_MERGE once PR #1 merges (it's stacked on PR #1 and needs Manpreet's approval). AC3 clarified to allow the unsourced tag.
- 2026-10-19 22:47 PDT, Architect: MM-002 IN_PROGRESS (ledger parser) on cloud bc-6c5db6e1, grok-4.5 (effort high, fast off; the id 'cursor-grok-4.5-high' doesn't exist), branch feat/MM-002-ledger-parser. MM-003 and MM-004 follow in sequence.
- 2026-10-19 22:47 PDT, Director: MM-001 DONE, agent-mindmap PR #1 merged as 0c0dd6e.
- 2026-10-19 22:50 PDT, Architect: MM-006 PR #3 462e68d CHANGES_REQUESTED (ARCH-MM006-1 MEDIUM: role=img wraps interactive controls; ARCH-MM006-2/3 LOW: lane-label title, marker aria-label). Owner UI/UX Maker. Reviews: QA only.
- 2026-10-19 22:52 PDT | Architect | handoff | MM-002 | IN_REVIEW PR #4 14b5831 -> QA. MM-003 started in bc-6c5db6e1.
- 2026-10-19 22:56 PDT | Architect | verdict | MM-006 | PR #3 3de7d9a: ARCH-MM006-1..3 fixed; BLOCKED on base/rebase/CI. MM-007 PR #5 48a2f11 CHANGES_REQUESTED: ARCH-MM007-2 MEDIUM keyboard nav, -3 MEDIUM unsourced task link, -4 MEDIUM edges table, -5..7 LOW; -1 new devDeps -> Security. Owner UI/UX Maker.
- 2026-10-19 22:55 PDT | Security Engineer | verdict | MM-007 | PR #5 48a2f11 SEC PASS (devDeps vetted).
- 2026-10-19 23:00 PDT | Architect | verdict | MM-006/MM-007 | PR #3 19e7a88 PASS; PR #5 1f2100b PASS (ARCH-MM007-8 LOW: tighten Tab-order test, follow-up). -> QA.
- 2026-10-19 23:01 PDT | Architect | handoff | MM-002/MM-003 | PR #4 031a242 fixes -> QA retest; MM-003 PR #6 8ee2c1c -> QA + Security. MM-004 waits for #4/#6 merge.
- 2026-10-19 23:01 PDT | Security Engineer | verdict | MM-003 | PR #6 8ee2c1c SEC PASS; MM-007 PR #5 SEC PASS carried to 1f2100b.
