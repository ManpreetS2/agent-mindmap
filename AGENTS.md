# Agent instructions — agent-mindmap

Read by Codex, Cursor and Claude Code (Claude via `CLAUDE.md`). Keep this file short and self-contained: Codex cannot follow imports. The full standard is [docs/agents/charter.md](docs/agents/charter.md); read it before any non-trivial change.

## Project state comes first

- Agent Mindmap development is **PAUSED by the owner** (see "PROJECT STATUS" at the top of [project.md](project.md)). An instruction like "write docs" or "fix X" is a narrow authorization, not a resumption. Do not infer permission to build features, delegate, merge or activate anything.
- Draft PRs #36 and #38 stay open, draft and unmerged. Do not merge, tag, release or mark anything ready for review.
- Read, in order: `project.md` (pause note, then "CURRENT STATE"), the newest file in `docs/handoffs/`, then the code and tests you will touch. Check actual state with `git`/`gh` instead of trusting a handoff.

## Rules that apply to every task

1. **Judge independently.** Challenge a flawed assumption with evidence. Recommend one best next action and its maintenance cost, not a menu.
2. **Understand before editing.** Inspect code, PRs, issues and tests. Preserve existing branches and behavior. Never rebuild a subsystem because it is easier to explain.
3. **Correctness before polish.** Accurate agent states, real delegation relationships, reliable transitions, honest blocked / failed / stale / unknown states.
4. **Label evidence.** VERIFIED (you observed it, say how), LIKELY, UNKNOWN. A unit test does not prove a live integration. Never fabricate tests or results. Demo or simulated data is never presented as live.
5. **Stay in scope.** No unrelated changes; report other findings instead of fixing them.
6. **Done means:** reproduced, root cause fixed, regression test added, integrated behavior verified, limitations and next action reported.
7. **Delegation:** only independent work, bounded brief, non-overlapping files, and independently review what comes back. Cheapest model and lowest effort that does the job.

## Hard limits (need explicit, current owner approval)

- Merging, tagging, publishing; deleting branches, worktrees or history; force-push.
- Starting or changing collectors, T3 services, private publishers, OAuth sessions, Claude quota taps, LaunchAgents or any background job. Never touch ports 8787, 8799 or 8882.
- Changing authentication, account settings or global model preferences. The two Claude accounts keep separate credentials, sessions and quota; never copy credentials between them or between machines.
- Credentials, tokens, personal data, prompts or private messages in the repo, logs, PRs or chat. No absolute machine-specific paths in committed docs.
- The public Pages demo stays synthetic-only. The private feed repo stays private.

## Commands (see `Makefile`, `.github/workflows/`)

- Python: `python -m pytest -q` (Python 3.12+; `pip install -e ".[dev,t3]"`)
- Web: `npm ci --prefix web`, then `npm --prefix web test`, `npm --prefix web run build`; types: `npm run typecheck`
- Instruction-system check: `python -m tools.check_agent_docs`

## Workflow and handoff

Seven steps in [docs/agents/workflow.md](docs/agents/workflow.md): recon, three highest-impact problems, one recommended task, focused implementation, independent verification, draft PR, session handoff. Handoffs follow [docs/agents/handoff-template.md](docs/agents/handoff-template.md). Maintenance of these instructions: [docs/agents/README.md](docs/agents/README.md).
