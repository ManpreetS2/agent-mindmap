# QA Report — MM-020e (PR #20) GitHub PR lanes

| Field | Value |
|-------|-------|
| **Verdict** | **FAIL** |
| **PR** | https://github.com/ManpreetS2/agent-mindmap/pull/20 |
| **Requested SHA** | `1b3f178d4c67d88196106b32693bfd4823175e83` |
| **Verified head** | `9a30965fd89c62f014a198c785a821e9e31db052` (**head moved**) |
| **Base** | `feat/MM-020-unified-network` @ `c2b8d66` |
| **Evidence branch** | `qa/MM-020e` |
| **Fresh checkout** | `/tmp/qa-mm020e/checkout` |
| **Environment** | Linux 6.12.94+, Python 3.12.3, Node v22.23.3 |
| **Date (UTC)** | 2026-10-20 |

## Verdict

**FAIL.** Commit-subject leak reported by Security is **fixed** at `9a30965` (SEC-MM020e-1). The same sink still accepts **unsanitized PR titles and review/comment bodies** into `event.raw` → `activity.json` (and the UI detail pane). That residual exposure keeps the PR from PASS.

Suite/CI on head: **157 passed, 1 skipped**; CI green.

## Head movement

| | SHA |
|--|-----|
| Requested | `1b3f178` — commit subject → `raw` unscanned/uncapped |
| Current | `9a30965` — `fix(MM-020e): SEC-MM020e-1 sanitize commit subject before raw` |

Verification below is against **`9a30965`**.

## Checks

| # | Check | Result | Evidence |
|---|-------|--------|----------|
| 1 | Allowlist (repos / fork / foreign Link) | **PASS** | behavioral allowlist tests |
| 2 | Secret refusal on commit messages + shared scanner | **PASS** for commits; benign `task-runner` OK | `secret_summary_results.json`, raw-field JSON |
| 2b | SEC: secret/long subject in `raw` → activity.json | **Closed** at `9a30965` | `raw_field_security.json` |
| 2c | Residual: PR title / review body → `raw` | **FAIL** | `residual_pr_title_raw.txt`, `residual_review_raw.txt` |
| 3 | 240-char cap (239/240/241, emoji, multiline) | **PASS** on `sanitize_pr_summary`; applied to commit `raw` | `summary_cap.json` |
| 4 | gh read-only / no token; pagination; rate-limit | **PASS** | `gh_calls.json`, `commit_pagination.json`, `rate_limit.json` |
| 5 | XSS in UI | **PASS** (React text child; no `dangerouslySetInnerHTML`); markup may still be stored in `raw` | `xss_ui_scan.txt` |
| 6 | Exact counts + CI | **157 passed, 1 skipped** (claim was 156 @ `1b3f178`); CI success on `9a30965` | `pytest_counts.json`, `ci_checks.txt` |
| 7 | Regressions 020a / 020c / 020f surface | **PASS** subset + AgentGraph `groups` present | `pytest_regression_subset.txt` |

Harness: `qa/MM-020e/harness/test_qa_mm020e_behavioral.py` (13/13 OK at `9a30965`).

### Security addition — commit subject → `raw`

**At `1b3f178` (pre-fix):** `_push_events` set `raw=msg.split("\n",1)[0]` with no scan/cap → secrets and 300-char subjects would land in poller events → `merge_events` → `activity.json` → DetailPanel `{event.raw}`.

**At `9a30965` (verified):**

| Probe | activity.json `raw` | NetworkEvent |
|-------|---------------------|--------------|
| Subject with `sk-proj-…` | **Absent** (event dropped) | Absent |
| Subject length 300 | **Capped** to 240 + `…` | ≤240 |
| `task-runner` benign | Present | Present |
| XSS markup subject | Stored as text (escaped in UI) | Sanitized whitespace / cap |

Severity of the **original** commit-subject bug: **HIGH** (secret material persisted on disk + shown in UI).  
Status now: **closed** for commit subjects.

---

## Findings

### F1 — Unsanitized PR title still written to `event.raw` / activity.json

| | |
|---|---|
| **Component** | `GitHubPoller._events_for_pr` (`raw=f"Opened pull request #{number}: {title}"`) |
| **Expected** | Same secret/cap policy as commit subjects before persistence |
| **Actual** | Title containing `sk-proj-…` appears in `pr_opened.raw` inside activity.json |
| **Repro** | Mock pulls fixture title with secret; `build_activity(...)`; search activity JSON |
| **Evidence** | `logs/9a30965…/residual_pr_title_raw.txt` |
| **Severity** | **HIGH** |
| **Confidence** | **HIGH** |

### F2 — Unsanitized review/comment body still written to `event.raw` / activity.json

| | |
|---|---|
| **Component** | `_review_events` / `_comment_events` (`raw=body or …`) |
| **Expected** | Refuse/exclude secret-bearing bodies before activity persistence |
| **Actual** | Review body with `sk-proj-…` → `verdict.raw` in activity.json (1 hit in probe) |
| **Repro** | `residual_review_raw.txt` harness |
| **Evidence** | same dir |
| **Severity** | **HIGH** |
| **Confidence** | **HIGH** |

### N1 — XSS markup stored in `raw` (informational)

| | |
|---|---|
| **Component** | DetailPanel + commit/`raw` pipeline |
| **Expected** | Safe rendering |
| **Actual** | No `dangerouslySetInnerHTML` in `web/src`; React text binding escapes. Markup strings can still be stored after commit sanitize (non-secret) |
| **Severity** | **LOW** |
| **Confidence** | **HIGH** |

### Closed / passing notes

- Allowlist ctor + call set ⊆ `ALLOWED_REPOS`; cross-repo Link next rejected.
- `sanitize_pr_summary` uses `tools.secret_scan` (no local denylist copy in poller).
- Commit pagination follows same-repo Link; rate-limit path returns without throw.
- MM-020a / 020c / secret_scan / pr_lanes tests green; 020f multigroup `groups` still referenced in AgentGraph.

## How to re-run

```bash
git fetch origin feat/MM-020e
git checkout 9a30965fd89c62f014a198c785a821e9e31db052
python3 -m pytest -q   # 157 passed, 1 skipped
# point ROOT in harness to checkout:
python3 qa/MM-020e/harness/test_qa_mm020e_behavioral.py
```
