# Agent instruction system — map and maintenance

One canonical charter, three tiny adapters, no framework. Status: ready for owner review (draft PR). Loading verification recorded below.

## Files

| File | Read by | Role |
|---|---|---|
| [charter.md](charter.md) | any agent, on demand | **Canonical** vendor-neutral standard. Edit policy here. |
| [workflow.md](workflow.md) | any agent, on demand | Seven-step process, roles. |
| [handoff-template.md](handoff-template.md) | any agent, ChatGPT | Handoff format. |
| `AGENTS.md` | Codex, Cursor, Claude (via import) | Short self-contained digest + hard limits + pointers. |
| `CLAUDE.md` | Claude Code | `@AGENTS.md` import + Claude-specific notes. |
| `.cursor/rules/engineering-charter.mdc` | Cursor | `alwaysApply` pointer + Cursor notes. |
| `.claude/skills/{recon,handoff}/SKILL.md` | Claude Code | Thin entry points into workflow steps 1-3 and 7. |
| `tools/check_agent_docs.py`, `tests/test_check_agent_docs.py` | CI / humans | Drift and hygiene check. |

## Why these formats (from each client's documentation and tests below)

- **Codex** concatenates `AGENTS.md` files from the repository root down, one per directory, capped at 32 KiB combined. It documents no import mechanism, so `AGENTS.md` must be self-contained and short; it links to the charter, which an agent reads on demand.
- **Claude Code** loads `CLAUDE.md` and expands `@path` imports (relative to the importing file, up to four hops). It reads `AGENTS.md` itself only when **no** `CLAUDE.md` exists in or above the working directory, so a `CLAUDE.md` that imports `AGENTS.md` is required to get both. `.claude/rules/` was not used: nothing here is path-specific.
- **Cursor** reads `AGENTS.md` and `.cursor/rules/*.mdc`. A rule with `alwaysApply: true` is always included; `@file` references inside rules attach those files.

## Loading verification (2026-10-24)

Method: each client was run non-interactively from this repository with a read-only prompt that asks for facts found **only** in the instruction files (the three off-limits ports, the exact name of the check command, the project status). Tools were disabled (Claude) or the event stream contained no tool calls (Codex, Cursor), so a correct answer shows the content was already in context. Negative controls ran from an empty directory. Probes used the cheapest practical model and effort.

| Client | Result | Evidence |
|---|---|---|
| Claude Code 2.1.310, default login ("account 1" by the handoff's convention) | **VERIFIED** loads `CLAUDE.md` and the `@AGENTS.md` import | Haiku, 1 turn, tools off, all three answers correct |
| Claude Code, second config dir ("account 2") | **VERIFIED**, same result; the two logins were confirmed to be distinct identities | same probe |
| Claude negative control (empty directory) | all three items answered NOT IN CONTEXT | confirms the probe cannot be answered without the files |
| Claude skills `recon`, `handoff` | **VERIFIED** discovered, with their descriptions | listing visible with only the Skill tool enabled; not invoked |
| Codex CLI 0.164.0 | **VERIFIED** loads `AGENTS.md` | `codex exec`, read-only, event stream had no command executions; control from an empty directory answered NOT IN CONTEXT |
| Cursor Agent CLI 2026.10.16 | **VERIFIED** loads both `AGENTS.md` and the `.cursor/rules/*.mdc` rule | two probes, one answerable only from each file; no tool-call events |
| Cursor editor (IDE) | **UNVERIFIED** | not tested; only the CLI agent was. Rules are documented to load there, but nothing here proves it |
| ChatGPT | **NOT APPLICABLE / UNVERIFIED** | repository files cannot set its instructions or reach other agents' sessions; use [handoff-template.md](handoff-template.md) and give it the GitHub link |
| Claude subagents, skills' *behavior* when invoked | **UNVERIFIED** | only discovery was tested |

Loading is not compliance: a model that has the rules can still ignore them. This test shows presence in context, nothing more. The charter is deliberately not auto-loaded (too long); the digest tells agents to read it, and whether they do is UNVERIFIED.

To repeat: from the repository root run the same prompt through `claude -p --tools "" --no-session-persistence`, `codex exec -s read-only --ephemeral` (redirect stdin from `/dev/null`, or Codex waits for input) and `cursor-agent -p --mode ask --trust --output-format stream-json`, and compare the answers with `AGENTS.md`.

## Maintaining it

1. Change policy in `charter.md` or `workflow.md` first. They are the single source of truth.
2. Update the `AGENTS.md` digest only if a rule that must always be in context changed. Keep it under ~12 KB and self-contained.
3. Do not copy charter text into `CLAUDE.md`, the Cursor rule, or skills. They point; they do not restate.
4. Run `python -m tools.check_agent_docs` (also part of `python -m pytest`). It checks required files, the `@AGENTS.md` import, size, links, frontmatter, and (heuristically) that no credential-shaped strings or common absolute machine-path shapes appear in the instruction files and `docs/handoffs/`. It **cannot** prove a client loads the files.
5. Re-verify loading after upgrading a client or changing a file's name or location (procedure above). Record result and client version.
6. Project state (pause, PR list, approval gates) belongs in `project.md` and `docs/handoffs/`, never in the charter.

## Not included, on purpose

No scheduler, spend monitor, orchestration daemon, generated files, or per-model prompt variants. Do not change global (`~/.claude*`, `~/.codex`, Cursor user) settings from this repository; they are per-account and per-machine.
