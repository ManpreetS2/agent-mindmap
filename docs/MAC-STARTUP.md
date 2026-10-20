# MINDMAP — Mac startup guide

Runs the read-only MINDMAP live daemon on **http://127.0.0.1:8787** (localhost only; the daemon refuses any other bind host).

## Prerequisites
- Python **3.12+** on PATH as `python3.13` or `python3.12` (`brew install python@3.12`)
- Node **20+** and npm (only needed when `web/dist` must be built)
- GitHub CLI `gh`, already logged in — check with `gh auth status`. The script never runs `gh auth login`; run it yourself.

## Start (foreground)
From the repo root:
```bash
./scripts/start-mac.sh            # creates .venv, builds web/dist if missing, starts ingest.live
./scripts/start-mac.sh --rebuild  # force npm ci + npm run build in web/
./scripts/start-mac.sh --help
```
Environment (optional):
- `MINDMAP_LEDGER=/absolute/path/to/task-ledger.md` — local ledger. If unset, the ledger is read from the `data/ledger` branch via `gh`.
- `MINDMAP_PORT` — listen port (default `8787`).
- `MINDMAP_EVENTS_SOURCE=gh|off` — events from the `data/events` branch (default `gh`).

**Stop:** `Ctrl+C`.

## Autostart with launchd (optional)
```bash
export MINDMAP_LEDGER=/absolute/path/to/task-ledger.md   # required by the installer
./scripts/install-launchagent.sh
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.manpreet.mindmap.plist
```
The installer only writes the plist (and lints it with `plutil` if `plutil` is available) to `~/Library/LaunchAgents/com.manpreet.mindmap.plist`; it does not load it. The agent runs `scripts/start-mac.sh` at login and restarts it on failure (30 s throttle).

**Stop / uninstall:** `launchctl bootout gui/$(id -u)/com.manpreet.mindmap` (then delete the plist file to remove it fully).

**Logs:** `~/Library/Logs/mindmap/live.stdout.log` and `live.stderr.log` (launchd only; foreground runs log to the terminal).

## Check it's running
Open http://127.0.0.1:8787, or `curl http://127.0.0.1:8787/healthz` (poll timestamps and errors).

## LIVE mode (default)
Read-only. The daemon polls:
- the task ledger (`MINDMAP_LEDGER` file, or `data/ledger` via `gh`; every 30 s by default),
- bot events from `data/events` via `gh` (unless `MINDMAP_EVENTS_SOURCE=off`),
- GitHub PRs for the allowlisted repos via `gh api` (every 60 s by default).

The UI updates live over SSE (`/events`). No tokens are stored; the existing `gh` login is used.

## DEMO mode
```bash
./scripts/start-mac.sh --demo
```
Shows sample events, not real activity. In this mode the script:
- forces the events source to `off`, ignoring `MINDMAP_EVENTS_SOURCE`,
- passes `--demo` to `ingest.live`,
- skips the `gh auth status` check.

The header banner shows the current mode: DEMO, LIVE, loading, or unknown. DEMO serves only the bundled fixtures and never calls `gh` or GitHub. The ledger is not used, but if `MINDMAP_LEDGER` is set it must still point to an existing file, or the script exits with `MINDMAP_LEDGER file not found`. Unset it to be safe.

To regenerate the offline sample `activity.json` from the committed fixture ledger (no network, no `gh`), run `make refresh-demo`. It writes to `web/public/activity.json` by default; override with `ACTIVITY_OUT=/path`.

## Troubleshooting
| Message | Fix |
|---|---|
| `Python 3.12+ is required but python3.13/python3.12 was not found on PATH.` | `brew install python@3.12` |
| `.venv failed health check ... recreating` | Informational; the script rebuilds `.venv` itself. |
| `Node.js and npm are required to build web/dist` | Install Node 20+. |
| `mindmap: port <PORT> is already in use; exiting` (the port you set, `8787` by default) | Another process (maybe the launchd copy) holds the port. Stop it, or set a different `MINDMAP_PORT`. |
| `GitHub CLI (gh) is required for live mode` | `brew install gh` |
| `gh is not authenticated. Run 'gh auth login' yourself` | Run `gh auth login`, then retry. |
| `MINDMAP_LEDGER file not found` | Use an absolute path to an existing file. |
| `set MINDMAP_LEDGER ... before installing` | The launchd installer needs a local ledger path. |
| `MINDMAP_EVENTS_SOURCE must be 'gh' or 'off'` | Fix the env value. |
