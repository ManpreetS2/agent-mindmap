# Technical Handoff Template

Purpose: let ChatGPT (or any agent starting cold) act as engineering lead from **GitHub evidence alone**. Repository files do not change ChatGPT's instructions and do not give it access to other agents' local sessions. It only knows what it can fetch, so the handoff must be self-contained, committed or in a PR description, and checkable.

Keep it to one screen of facts. Prefer links and SHAs to prose. Every state claim carries an evidence label from the [charter](charter.md): **VERIFIED** (observed this session, with command or run), **LIKELY**, **UNKNOWN**.

Save as `docs/handoffs/YYYY-MM-DD-<topic>.md`. Do not paste credentials, tokens, private messages, prompts or absolute local paths.

---

```markdown
# Handoff: <topic> (<YYYY-MM-DD>)

**Repository / branch / head:** <owner/repo> · `<branch>` · `<full or 8-char SHA>` · fetched <time>
**Written by:** <agent + role>  **Status of project:** <ACTIVE | PAUSED per project.md>

## 1. Integrated functionality (what works on the head commit)
- <capability> — <VERIFIED/LIKELY/UNKNOWN> — <evidence>

## 2. Active PRs and dependencies
| PR | Branch → base | Draft | Head SHA | CI at that SHA | Depends on |
|---|---|---|---|---|---|

## 3. Verified test state
| Check | Result | Commit | Evidence label |
|---|---|---|---|
Say what the tests do **not** prove (live integrations, deployments, other machines).

## 4. Biggest known correctness issue
<one issue, its evidence, its blast radius, where to reproduce>

## 5. Work in progress
<branches/worktrees with owner and state; anything uncommitted; anything that must not be touched>

## 6. Owner approval gates
- [ ] <action> — needs <what> — blocked until <who decides>

## 7. Recommended next action
<ONE action, why it beats the alternative, cost, and what it deliberately leaves out>
```

---

## How ChatGPT should use a handoff

1. Fetch the handoff and `project.md` from the branch named in it. Confirm the head SHA still matches; if not, say what changed.
2. Check one or two claims against GitHub (CI runs, PR state) before relying on any of them.
3. Respond with: agreement or challenge of the recommended action, the single next step, and a bounded brief for whichever agent should execute it (goal, files it may write, evidence to return, stop condition).
4. When the executing agent reports back, review that report against the PR diff and CI, not against the report's own summary.
