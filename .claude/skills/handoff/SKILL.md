---
name: handoff
description: Write a session handoff for agent-mindmap that ChatGPT or the next agent can review from GitHub evidence. Use at the end of a substantial session or before switching agents.
---

Use the format in `docs/agents/handoff-template.md` and the evidence labels from `docs/agents/charter.md` section 4.

1. Fetch first and re-check the head SHA, PR states and CI at that SHA with `git` and `gh`; do not copy them from earlier notes.
2. Fill every section. Write "none" or "UNKNOWN" rather than omitting one.
3. No credentials, tokens, private messages, prompts or absolute local paths.
4. Save as `docs/handoffs/YYYY-MM-DD-<topic>.md` on the working branch. Commit only if the task authorizes commits; otherwise show the text.
