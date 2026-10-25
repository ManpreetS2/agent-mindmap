---
name: recon
description: Read-only repository reconnaissance for agent-mindmap. Use at the start of a task, or when asked what to work on next. Produces verified repo state, the three highest-impact problems, and one recommended task.
---

Follow steps 1-3 of `docs/agents/workflow.md` (read it first, plus `docs/agents/charter.md` sections 1-4).

Read-only: do not edit files, push, start services or run anything that writes outside temp files.

Output exactly:
1. **State** — branch, head SHA, remote comparison, open PRs with CI at their real head, relevant issues; each fact marked VERIFIED / LIKELY / UNKNOWN.
2. **Top three problems** — ranked, with evidence, blast radius, cost.
3. **Recommendation** — one task, why it beats the other two, what you are not doing, and any owner approval it needs. If `project.md` says the project is paused, the recommendation must respect that.
