# Taskbot activity in Agent Mindmap (read-only)

Shows Agent Control's `taskbot` jobs (GitHub issue → coding agent → verification → draft PR) next to the T3 view.
Authorized as a focused integration only; the project is otherwise paused (`project.md`).

**What it is not.** A taskbot task is a job record. It is not a T3 session, and an issue → PR link is taskbot's own
bookkeeping, not proof that one model delegated to another. The document has no edges, no prompts and no raw logs.

## Enable (opt-in, local, read-only)

```sh
AGENT_MINDMAP_TASKBOT_STATE=<agent-control>/state python -m ingest.live --source t3 --port <free port>
```

`GET /automation.json` then reads `<state>/taskbot.sqlite` and `<state>/events.sqlite` read-only (`mode=ro`, never created
or written). Unset means 404 and the panel says taskbot activity is not connected. Demo snapshots (`meta.t3.mode ==
"demo"`) serve the synthetic fixture and never read real state, even if the variable is set. Nothing is published:
`/automation.json` is not part of the private feed or the Pages build.

CLI check: `python -m tools.taskbot_activity --state-dir <agent-control>/state`. Schema: `schema/automation.schema.json`.

## States (each carries the reason it was derived)

| State | Evidence required |
|---|---|
| running | ticket `running`/`fixing`, a `run_start` with no `run_end`, and an event in the last 30 min |
| unknown | ticket says running but that evidence is missing (crash, sleep, pruned events); unrecognised status |
| blocked | queued with a future `wait_until` (quota/infra retry) |
| queued | ticket `queued` |
| completed | `pr_open` (draft PR, not merged), `merged`, `done`, or a dry run (nothing pushed) |
| failed | ticket `failed`, with a one-line redacted error summary from the event |
| skipped | `skipped`, `ignored`, `gone`, `superseded`, `pr_closed` |

Model and effort come from the `runs` row with the same `run_id`, else the `run_start` text, else they are shown as not
reported. The browser re-checks "running" against its own clock, so a cached document cannot keep a job running.

## Demonstrate without a model

In the Agent Control repo: `python3.12 tests/demo_pilot_lifecycle.py <new dir>` writes staged state directories from a
real taskbot run with only GitHub and the model faked. Point `AGENT_MINDMAP_TASKBOT_STATE` at a stage (a symlink you
swap works, the path is re-read on every request).

## Not verified

Real runs: no real taskbot job has executed, so only fixture and mock-driven databases have been read. The WSL machine's
state directory was not accessible. Real T3 sessions: this Mac has no T3 login.
