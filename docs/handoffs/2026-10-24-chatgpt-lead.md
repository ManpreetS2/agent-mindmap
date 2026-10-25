# Handoff: agent-mindmap state for the ChatGPT engineering lead (2026-10-24)

First real use of [docs/agents/handoff-template.md](../agents/handoff-template.md). Facts below were checked with `git`, `gh` and a local test run on 2026-10-24 unless labelled otherwise. Older detail: [Mission 003 handoff](2026-10-24-mission003.md).

**Repository / branch / head:** `ManpreetS2/agent-mindmap` · `feat/pages-observability-preview` (PR #38) · `5581322` · fetched 2026-10-24
**Written by:** Claude Code (lead engineer, instruction-system assignment) **Status of project:** **PAUSED** by the owner (`project.md`, "PROJECT STATUS")

## 1. Integrated functionality (on `5581322`)
- Read-only T3 Code agent/session monitoring with deterministic synthetic replay, quota cards, observability health, evidence-gated recommendations, multi-Mac publisher lease/epoch code — **LIKELY** (code present, PR CI green; built by workers, not re-audited here).
- Public Pages demo is synthetic-only; workflow builds synthetic `activity.json` and `observability.json` — **LIKELY** (workflow success at this SHA; the hosted artifact was **not** inspected, so UNKNOWN).
- Real T3 data, per-account Claude quota taps, and a single real private publisher — **UNKNOWN**. Per the pause note and Mission 003 handoff, the newer Mac has no T3 login, quota tap or LaunchAgent enabled; what the older Mac's manual collector and legacy publisher are doing now was **not checked** and may still be running (approval gates, section 6).

## 2. Active PRs and dependencies
| PR | Branch → base | Draft | Head | CI at that head |
|---|---|---|---|---|
| #36 | `feat/t3-readonly-activity` → `main` | yes | `d0f08ba` | not re-checked |
| #38 | `feat/pages-observability-preview` → `feat/t3-readonly-activity` | yes | `5581322` | python, web, Pages, full-history secret audit: all **success** (VERIFIED, `gh run list`) |
| this PR | `docs/agent-engineering-charter` → `feat/pages-observability-preview` | yes | see PR | docs/tests only |
| #16 | `feat/MM-020-unified-network` → `main` | yes | `8dd6c29` | not re-checked |
| #29, #30 | → `feat/MM-020-unified-network` | yes | — | not re-checked |
| #35 | `integ/mm020-p0-recovery` → `feat/MM-020-unified-network` | **no (ready)** | `3061aa8` | pytest, web **success** |
| #12, #13 | QA reports → `main` | yes | — | stale, from early milestones |

Stack: #38 depends on #36; this PR depends on #38 (it needs the handoff docs there). #16 / #29 / #30 / #35 are the older legacy-ledger line, separate from the T3 line.

## 3. Verified test state
| Check | Result | Commit | Label |
|---|---|---|---|
| `python -m pytest -q` (local, Python 3.12) | 762 passed | `5581322` | VERIFIED |
| GitHub Actions python / web / Pages / secret audit | success | `5581322` | VERIFIED |
| Frontend suite, typecheck, build | 321 passed, clean (worker-reported); web CI green | `fe7a770` / `5581322` | LIKELY — not rerun here |
| Browser views at 1440 / 768 / 390 px | worker-reported only | `fe7a770` | LIKELY |

Not proven by any of this: live T3 sessions, OAuth, the two Claude quota taps, a two-Mac publish to the real private repo, the hosted Pages artifact, launchd behavior.

## 4. Biggest known correctness issue
Issue #34 (labelled bug, High): on the legacy ledger dashboard line (PR #16 lineage), SSE mode never refetches `activity.json` after ledger or manual-refresh rebuilds, so the dashboard silently goes stale while "connected". Its own report says CONFIRMED by code tracing, no browser test. Issue #33 (daemon reports GitHub "ok" during outages) is related. PR #35 (open, CI green, mergeable) describes fixes for both, but this review did **not** verify that the fix works — **LIKELY**. Neither affects the T3 line in #36/#38. Open issue #37 is an unrelated small `format.ts` timestamp bug.

## 5. Work in progress
- Nothing uncommitted on the instruction-system branch. Local worktrees from Mission 003 and earlier exist on the owner's machine (`git worktree list`); do not delete them (the older Mac may still run services from them).
- The owner's local checkout of #38 may lag the remote; always `git fetch` before reading it.

## 6. Owner approval gates
- [ ] Review and merge this instruction-system PR (and #36/#38) — the owner only.
- [ ] Resume Agent Mindmap development — owner decision; the pause forbids new features, delegation, service activation.
- [ ] T3 MCP login on the new Mac (`docs/handoffs/2026-10-24-mission003.md`, Gate C).
- [ ] Install the two Claude status-line taps — separate approval per account.
- [ ] Choose the single publisher Mac, after the older Mac's legacy publisher is stopped (Gate D).
- [ ] Public Pages workflow edits need the `workflow` GitHub scope; the owner grants it.

## 7. Recommended next action
**Keep Agent Mindmap paused and take no development action.** If it is resumed, the single best step is the owner's T3 MCP login: until real sessions flow, every T3 claim is validated only against synthetic fixtures, so nothing else (quota taps, publisher handover) can be judged. Deliberately not recommended: more UI polish, a new quota feature, or merging anything before real data has been observed once.
