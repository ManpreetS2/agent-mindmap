# QA Report — MM-020b (PR #17) NetworkEvent JSONL emitter

| Field | Value |
|-------|-------|
| **Verdict** | **FAIL** |
| **PR** | https://github.com/ManpreetS2/agent-mindmap/pull/17 |
| **Verified head SHA** | `692216de5f944a870887bc7bf37779f618797cc2` |
| **Originally requested SHA** | `48a13d947517692ce17b5163d19347bdb7f70bdf` (**head moved**; both evaluated) |
| **Base** | `feat/MM-020-unified-network` @ `b1fe594ec72086a1b025a7b137213b9632f35920` |
| **Evidence branch** | `qa/MM-020b` |
| **Environment** | Linux 6.12.94+, Python 3.12.3, Node v22.23.3, fresh clone under `/tmp/qa-mm020b/checkout` |
| **Verifier** | Independent QA (no product code changes; no PR comments) |
| **Date (UTC)** | 2026-10-20 |

## Verdict summary

Core emitter contract from MM-020 audit §7 (020b) and PR claims holds at `692216d`: concurrent appends are exact and uncorrupted, lines stay ≤ PIPE_BUF, deterministic ids, `networkEvent` / `agent-reported` provenance validate, suite/typecheck/build/CI green.

**FAIL** against the broader acceptance matrix (QA request + audit fact b + Security notes context): summary content is a **denylist** scan (not content allowlist); `sk-`, `AKIA`, JWT-shaped strings, private-key blocks, emails, and raw-ish message bodies are **written into JSONL**; unknown recipients are accepted with **no reject/flag**.

Security notes:

- **SEC-MM020b-1** — **Confirmed open at `48a13d9`**; **addressed at `692216d`** (`O_NOFOLLOW` + symlink refuse + create mode `0o600`).
- **SEC-MM020b-2** — Cap was **2000** at `48a13d9`, **240** at `692216d`. Raw message text that is not secret-like **can pass through** (then truncated). Refuse-not-redact for matched secrets: **confirmed** (clear `SecretRefusedError` / CLI stderr; no file written).

## Checks

| Check | Result | Evidence |
|-------|--------|----------|
| Head identity | Head moved `48a13d9` → `692216d` | `logs/*/`, `ci_runs.json` |
| Full pytest | **123 passed**, 1 skipped @ `692216d` (was 120 @ `48a13d9`) | `logs/692216d…/pytest.txt` |
| Typecheck | PASS | `logs/692216d…/typecheck.txt` |
| Web build | PASS | `logs/692216d…/build.txt` |
| CI on head | pytest **success** run `39394298787` @ `692216d` | `logs/692216d…/ci_checks.txt` |
| Opt-in (no write without emit) | PASS (call-gated only; no env flag) | harness `opt_in_no_file_without_write` |
| Concurrent 8 proc × 500 | PASS (4000/4000, all JSON, unique ids) | harness |
| Concurrent 8 thread × 200 | PASS (1600/1600) | harness |
| PIPE_BUF / large events | PASS | harness |
| Crash / partial trailing line | PASS (harness reader skip/flag; emitter has no reader) | harness |
| Secret refuse (ghp_/Bearer/pat) | PASS — clear refusal, nothing written | harness + `sec_mm020b_1_2.txt` |
| Secret coverage (sk-/AKIA/JWT/key/email) | **FAIL** — accepted into summary | harness `raw_text_and_unscanned_secrets` |
| Allowlist fields only | PASS (event keys) | harness |
| Content allowlist (not denylist) | **FAIL** — `_looks_like_secret` denylist | `looks_like_secret` + harness |
| Recipients not inferred from @mentions | PASS | harness |
| Unknown recipients rejected/flagged | **FAIL** — accepted as-is | harness |
| SEC-MM020b-1 @ `48a13d9` | **OPEN** — no `O_NOFOLLOW`, mode `0o644`, symlink write-through | `logs/48a13d9…/sec_mm020b_1_2.txt` |
| SEC-MM020b-1 @ `692216d` | **ADDRESSED** — `O_NOFOLLOW`, `0o600`, `SymlinkRefusedError` | `logs/692216d…/sec_mm020b_1_2.txt` |
| SEC-MM020b-2 cap / raw text | Cap 2000→240; raw text can pass | both `sec_mm020b_1_2.txt` |
| FS permission errors | PASS — `PermissionError` to caller | harness |
| Rotation / size limits | N/A (not in 020b spec beyond PIPE_BUF) | harness |
| MM-020a schema / provenance | PASS — `type=message`, `provenance=agent-reported`, validates `$defs/networkEvent` | harness + `tests/test_mm020a_membership.py` |

Harness: `qa/MM-020b/harness/qa_verify_mm020b.py` (independent; does not modify product code).

---

## Findings

### F1 — Summary secret coverage incomplete (denylist gaps)

| | |
|---|---|
| **Component** | `tools/event_emit.py` → `sanitize_summary` / `ingest.github_poller._looks_like_secret` |
| **Expected** | Tokens (`ghp_`, `github_pat_`, `sk-`, `AKIA`, Bearer, JWT, private key blocks), emails, raw message bodies, long free text must not appear in JSONL; content handling should be allowlist-oriented |
| **Actual** | Field set is allowlisted; **summary text** uses MM-010 denylist regex only. At `692216d`, **accepted into output**: `sk-proj-…`, `AKIA…`, JWT-shaped strings, `BEGIN PRIVATE KEY` blocks, `alice@example.com`, multi-sentence raw bodies (capped at 240). **Refused**: `ghp_`, `github_pat_`, `Bearer`/`Authorization` |
| **Repro** | Fresh checkout @ `692216d`; `python3 qa/MM-020b/harness/qa_verify_mm020b.py` → `raw_text_and_unscanned_secrets` / `secret_scanner_coverage` |
| **Evidence** | `logs/692216d…/harness_results.json`, `harness_stdout.txt` |
| **Environment** | Python 3.12.3, Linux x86_64 |
| **Severity** | **HIGH** |
| **Confidence** | **HIGH** |

### F2 — Unknown recipients neither rejected nor flagged

| | |
|---|---|
| **Component** | `tools/event_emit.emit_message` / `build_network_event` |
| **Expected** | Recipients only from explicit fields (met); unknown recipients rejected or flagged |
| **Actual** | `@mentions` in summary are not inferred (**good**). Explicit `recipients=["dev-1","not-a-real-bot"]` is written unchanged with no validation against `bots.json` and no flag field |
| **Repro** | `emit_message(..., recipients=["dev-1","not-a-real-bot"])` |
| **Evidence** | harness `recipients_explicit_unknown_accepted` |
| **Environment** | same |
| **Severity** | **MEDIUM** |
| **Confidence** | **HIGH** |

### F3 — SEC-MM020b-1 open at requested SHA `48a13d9` (fixed on moved head)

| | |
|---|---|
| **Component** | `append_event` / `os.open` |
| **Expected (Security)** | Confirm missing `O_NOFOLLOW`; create mode `0o644`; symlink target behavior |
| **Actual @ `48a13d9`** | `flags = O_WRONLY\|O_APPEND\|O_CREAT` (**no** `O_NOFOLLOW`); `os.open(..., 0o644)`; created file mode **`0o644`**; writing via symlink **followed** and appended to real file (`real_size` 187) |
| **Actual @ `692216d`** | `_open_jsonl_append`: pre-check `path.is_symlink()`, `O_NOFOLLOW`, mode **`0o600`**; `SymlinkRefusedError`; real file size remains 0 |
| **Repro** | See `logs/48a13d9…/sec_mm020b_1_2.txt` and `logs/692216d…/sec_mm020b_1_2.txt` |
| **Evidence** | those files + source snippets in same dirs |
| **Environment** | same; umask `0o022` |
| **Severity** | **MEDIUM** at `48a13d9`; **informational / addressed** at `692216d` |
| **Confidence** | **HIGH** |

### F4 — SEC-MM020b-2 summary is free text; raw message text can pass

| | |
|---|---|
| **Component** | `sanitize_summary` |
| **Expected (Security)** | Confirm cap; whether raw message text can pass; refuse-not-redact |
| **Actual @ `48a13d9`** | Cap **2000** chars; raw transcript-like text accepted (whitespace-normalized); secrets → `SecretRefusedError("summary refused: secret-like content")`, **no file created** |
| **Actual @ `692216d`** | Cap **`SUMMARY_MAX_CHARS = 240`**; raw-ish text still accepted then truncated to 240 with `…`; same clear refusal + no write for scanned secrets; CLI: `stderr: error: summary refused: secret-like content`, exit 1, no file |
| **Repro** | `sanitize_summary("Raw message body…"*N)`; `emit_message(..., summary="Authorization: Bearer …")` |
| **Evidence** | both `sec_mm020b_1_2*.txt`; harness `SEC-MM020b-2_*` |
| **Environment** | same |
| **Severity** | **MEDIUM** vs audit “NEVER raw transcript” / QA sanitization bar; refuse path itself is **correct** |
| **Confidence** | **HIGH** |

### F5 — Opt-in is call-gated only (observation)

| | |
|---|---|
| **Component** | emitter API / CLI |
| **Expected** | With no explicit opt-in, nothing written / no file created |
| **Actual** | Import/`build_network_event` create no file (**pass**). There is no env/config gate; any caller that invokes `emit_message` / CLI `--out` writes. Matches “opt-in by adoption” in audit §5, not a separate runtime switch |
| **Severity** | **LOW** / informational |
| **Confidence** | **HIGH** |

### F6 — No built-in JSONL reader / rotation (observation)

| | |
|---|---|
| **Component** | `tools/event_emit.py` |
| **Expected** | Reader skips/flags partial trailing line; rotation if spec’d |
| **Actual** | Single `os.write` ≤ PIPE_BUF mitigates torn writes from the emitter; no reader helper; no file rotation (not required in 020b row). Harness demonstrated skip/flag of a synthetic partial trailer |
| **Severity** | **LOW** |
| **Confidence** | **HIGH** |

### F7 — Full-disk not exercised (gap)

| | |
|---|---|
| **Component** | `append_event` error path |
| **Expected** | Full disk fails gracefully without crashing caller |
| **Actual** | Permission errors raise `OSError`/`PermissionError` to caller (verified). ENOSPC not simulated in this environment |
| **Severity** | **LOW** (test gap → does not alone drive FAIL) |
| **Confidence** | **MEDIUM** |

---

## Security notes — confirmation table

| ID | Question | At `48a13d9` | At `692216d` (current head) |
|----|----------|--------------|------------------------------|
| SEC-MM020b-1 | `O_NOFOLLOW`? | **Absent** | **Present** (+ symlink pre-check) |
| SEC-MM020b-1 | Create mode | **`0o644`** (stat confirms) | **`0o600`** (stat confirms) |
| SEC-MM020b-1 | Symlinked target | **Write-through** to real file | **`SymlinkRefusedError`**; real size 0 |
| SEC-MM020b-2 | Summary cap | **2000** | **240** |
| SEC-MM020b-2 | Raw message text | **Can pass** | **Can pass** (then truncated) |
| Refuse vs redact | Caller signal + no write | **`SecretRefusedError` / CLI error; no file** | **Same** |

No product fixes applied by this verifier.

## Compatibility (MM-020a)

Emitted events validate against `schema/activity.schema.json` `$defs/networkEvent` with `type: "message"` and `provenance: "agent-reported"`. Existing MM-020a membership tests pass in the same suite (`tests/test_mm020a_membership.py`).

## How to re-run

```bash
git fetch origin feat/MM-020b
git checkout 692216de5f944a870887bc7bf37779f618797cc2
python3 -m pytest -q          # expect 123 passed, 1 skipped
make typecheck
cd web && npm run build
# from repo with harness copied, or:
python3 qa/MM-020b/harness/qa_verify_mm020b.py   # after pointing ROOT at checkout
```
