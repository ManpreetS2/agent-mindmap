# Engineering Workflow

Seven steps, plain Markdown, existing GitHub features only. No scheduler, no daemon. Standards come from the [charter](charter.md); this file is the order of operations.

Size the process to the task. A typo fix needs steps 4 and 6 only. Anything that touches behavior, state, integrations or security needs all seven.

## 1. Repository reconnaissance (read-only)

Establish facts before opinions. Collect, and record the command or file each fact came from:

- `git status`, current branch, `git log --oneline -10`, and `git worktree list` (other agents may own other worktrees).
- Branch heads versus the remote after `git fetch`. Local state can be stale.
- `project.md` status and approval gates, and the newest file in `docs/handoffs/`.
- Open PRs (`gh pr list`), their base branches (stacked PRs depend on each other) and CI results at the real head commit; open issues.
- The tests and scripts that cover the area (`Makefile`, `package.json`, `.github/workflows/`).

Bounded recon may be delegated to a cheap model with a read-only brief. The delegate returns facts and paths, not opinions.

## 2. Identify the three highest-impact problems

List exactly three, ranked, each with: symptom, evidence label (VERIFIED / LIKELY / UNKNOWN), blast radius, rough cost. Rank by correctness impact first (charter section 3), then by how much it blocks other work. If fewer than three real problems exist, list fewer. Do not invent filler.

## 3. Choose one recommended task

Pick one. State why it beats the other two, what it costs to build and maintain, and what you are deliberately **not** doing. Check it against the approval gates: if the project is paused or the task needs an owner decision, the recommendation is to ask, and the report says exactly what is needed.

## 4. Focused implementation

- Work on a new branch in an isolated worktree, named for the purpose. Never commit to a branch that another agent or PR owns without saying so.
- Reproduce first. Fix the root cause. Add the narrowest regression test that would have caught it.
- Keep the diff to the task. Record unrelated findings for the report instead of fixing them.
- Commit in coherent steps. Do not rewrite shared history.

## 5. Independent verification

The author does not grade their own work.

1. Run the project's real checks (for this repo: `python -m pytest -q`, `npm run typecheck`, `npm --prefix web test`, `npm --prefix web run build`; see `Makefile`). Report counts and the commit they ran on.
2. Run the change for real where it is user-visible or integration-dependent; unit tests alone are not enough. If the real thing cannot be reached (no login, no hardware, no approval), mark that part UNVERIFIED.
3. A **different** agent or session reviews the diff for regressions, correctness, privacy and security, and checks the author's claims against the code. One bounded review round; fix verified findings; rerun the affected checks.

## 6. PR preparation

- Open a **draft** PR against the correct base. Leave it draft and unmerged; marking it ready or merging is the owner's call.
- PR body: purpose, what changed, evidence table (check, result, commit, VERIFIED/LIKELY/UNKNOWN), what was not verified, approval needed, and the recommended next action.
- Confirm CI on the pushed head commit before saying CI is green. Provider API results can lag a push; compare the head SHA.
- Scan the diff for credentials, personal data and machine-specific absolute paths before pushing.

## 7. Session handoff

End every substantial session by updating the handoff so the next agent (or ChatGPT) starts from facts. Use [handoff-template.md](handoff-template.md). Commit it to the branch you worked on, or put it in the PR description. Chat transcripts and local agent memory are not shared between agents and are not a handoff.

## Roles (defaults, not mandates)

| Role | Used for |
|---|---|
| ChatGPT | Technical lead: architecture, prioritization, critical review from GitHub evidence. Cannot see other agents' local sessions. |
| Claude Code, account 1 | Implementation. |
| Claude Code, account 2 | Independent engineering and review. Separate credentials, sessions and quota from account 1. |
| Cursor / Grok | Focused implementation and UI work. |
| OpenAI Codex | Independent engineering, testing and adversarial review. |

Use the cheapest model and lowest reasoning effort that does the job; escalate for a stated reason. The owner's choice of models and effort levels, and what is actually available in a given session, take precedence over any default here. Current owner preference (2026-10-24, may change): low effort by default, higher effort or top-tier models only with a stated reason and owner approval; see section 5 of the [Mission 003 handoff](../handoffs/2026-10-24-mission003.md).
