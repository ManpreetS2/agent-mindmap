# Claude Code instructions — agent-mindmap

Claude Code reads `AGENTS.md` only when no `CLAUDE.md` exists, so this file imports it to keep one source of truth:

@AGENTS.md

## Claude Code specifics

- Two Claude accounts use this repository from separate config directories. Instructions here are project-level and shared; never copy credentials, sessions or memory between accounts, and never record which account holds which quota in the repo.
- Before non-trivial work, read `docs/agents/charter.md` (it is not auto-loaded; it is long).
- Project skills in `.claude/skills/`: `recon` (workflow steps 1-3) and `handoff` (step 7). They only point at `docs/agents/`; do not copy policy into them.
- Instructions are context, not enforcement. The hard limits above are only as strong as your compliance; for anything irreversible, ask first.
