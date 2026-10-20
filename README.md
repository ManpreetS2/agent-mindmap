# agent-mindmap (MINDMAP)

Read-only agent-activity dashboard for the Fencepost bot team.

**Pipeline:** `task-ledger.md` + GitHub (`gh api`) → `ingest/build.py` → `web/public/activity.json` → Vite/React UI on **127.0.0.1**.

MINDMAP never posts, merges, or writes to the ledger. It never stores GitHub credentials.

---

## Run on a Mac (MM-020-OPS)

**Prerequisites:** Python 3.12+ (`brew install python@3.12`), Node 20+, and [`gh`](https://cli.github.com/) logged in (`gh auth status` — the startup script never runs `gh auth login`).

```bash
# From the repo root (creates .venv, builds web/dist if needed, starts live daemon)
./scripts/start-mac.sh
# → http://127.0.0.1:8787  (override port with MINDMAP_PORT)

# Local ledger file (optional; otherwise ledger is read from gh:data/ledger)
export MINDMAP_LEDGER=/absolute/path/to/task-ledger.md
./scripts/start-mac.sh

# Force a fresh web build
./scripts/start-mac.sh --rebuild
```

**Stop:** `Ctrl+C` in the terminal where the script is running.

**launchd autostart (optional):**

The template `ops/com.manpreet.mindmap.plist` runs **`/bin/bash` → `scripts/start-mac.sh`** (not `.venv/bin/python` directly). `install-launchagent.sh` renders it with `plistlib` into `~/Library/LaunchAgents/`.

```bash
export MINDMAP_LEDGER=/absolute/path/to/task-ledger.md
./scripts/install-launchagent.sh
# Creates ~/Library/Logs/mindmap, writes the plist, validates it, then prints:
#   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.manpreet.mindmap.plist
#   launchctl bootout gui/$(id -u)/com.manpreet.mindmap
# (It does not run bootstrap/bootout for you.)

# Optional: MINDMAP_EVENTS_SOURCE=gh|off (default gh) is passed through to ingest.live.
```

**Stop (launchd):** `launchctl bootout gui/$(id -u)/com.manpreet.mindmap`

See also **Running live (MM-011)** below for poll intervals and endpoints.

---

## Setup

Python 3.12+ and Node 20+ recommended.

```bash
# Python (schema validation + ingest tests)
python3 -m pip install -e ".[dev]"

# Shared TypeScript types
npm install

# Web app
cd web && npm install && cd ..
```

### GitHub access (read-only `gh` login — no tokens)

Director ruling: **no PAT / no `GITHUB_TOKEN`**. Ingest shells out to:

```bash
gh api --include …
```

using whatever account is already logged in on the machine (`gh auth status`).

- Allowed repos only: `ManpreetS2/fencepost`, `ManpreetS2/agent-mindmap`
- Credentials must never appear in `activity.json`, logs, or the repo (covered by tests)
- See `.env.example` — it documents `MINDMAP_LEDGER` only; do not add tokens

---

## Build `activity.json` (ingest)

`build.py` requires an explicit ledger path (QA-MM004-3): `--ledger PATH` or `MINDMAP_LEDGER`.

### Live refresh (local ledger path)

```bash
export MINDMAP_LEDGER=/absolute/path/to/build/task-ledger.md
make refresh
# → writes web/public/activity.json (gitignored)
```

### Live refresh (mirrored ledger on `data/ledger`)

```bash
python3 -m ingest --ledger-source gh --out web/public/activity.json
```

Reads allowlisted  
`repos/ManpreetS2/agent-mindmap/contents/ledger.md?ref=data/ledger`  
via `gh api` (ETag / 304, base64 decode). No tokens.

If GitHub/`gh` fails for PRs, ingest still writes a **ledger-only** snapshot with `meta.github: "error"`.  
If the ledger mirror fetch fails, `meta.ledger` is `"error"` (and `ledger_last_entry_at` may be null).

### Offline demo (fixtures, no network)

```bash
make refresh-demo
# ledger: tests/fixtures/ledger-sample.md
# GitHub: skipped → meta.github: "skipped"
```

Equivalent one-liner:

```bash
python3 -m ingest \
  --ledger tests/fixtures/ledger-sample.md \
  --out web/public/activity.json \
  --skip-github
```

---

## Run the web app (127.0.0.1 only)

```bash
make refresh          # or: make refresh-demo
cd web && npm run dev
# Vite listens on http://127.0.0.1:5173
```

Acceptance path (architecture §7 MM-008):

```bash
export MINDMAP_LEDGER=/absolute/path/to/build/task-ledger.md
make refresh && cd web && npm run dev
```

The UI fetches `/activity.json` via `web/src/data/loadActivity.ts`. For day-to-day use on a Mac, prefer the **live daemon** (below) instead of Vite dev + manual `make refresh`.

---

## Running live (MM-011)

One stdlib Python process polls the ledger and GitHub, keeps `web/dist/activity.json` fresh, and serves the built UI on **127.0.0.1 only** (default port **8787**).

```bash
cd web && npm run build && cd ..
export MINDMAP_LEDGER=/absolute/path/to/build/task-ledger.md
make live
# or: python3 -m ingest.live --ledger "$MINDMAP_LEDGER"
# gh mirror (MM-010): python3 -m ingest.live --ledger-source gh
#   (or `make live` with MINDMAP_LEDGER unset)
# MM-020d: also polls gh:data/events; SSE at GET /events (Last-Event-ID replay).
# SEC-MM011-1: Host must be 127.0.0.1/localhost; Origin localhost-only (403 otherwise).
```

- Ledger: `--ledger PATH` / `MINDMAP_LEDGER`, or `--ledger-source gh` for the allowlisted `data/ledger` mirror (same fetcher as `make refresh-gh-ledger`).
- Poll intervals: `--ledger-poll-sec` / `--gh-poll-sec`, or `MINDMAP_LEDGER_POLL_SEC` / `MINDMAP_GH_POLL_SEC` (defaults 30s / 60s).
- Endpoints: `/` (static `web/dist`), `/activity.json` (ETag + `If-None-Match` → 304), `/healthz` (poll timestamps + errors).
- GitHub: same read-only `gh api` allowlist as ingest; no tokens stored or logged.
- macOS autostart: use **Run on a Mac (MM-020-OPS)** above (`./scripts/start-mac.sh` for manual runs; `./scripts/install-launchagent.sh` for launchd). The plist invokes `scripts/start-mac.sh`, which creates a hash-locked `.venv`, builds `web/dist` when needed, and enforces Python **3.12+** before `ingest.live` starts.

---

## NetworkEvent emitter (MM-020b)

Bots may append opt-in live messages with `tools/event_emit.py` (JSONL, one `O_APPEND` write per line, ≤ `PIPE_BUF` bytes).

- **Summary:** short sanitized summary only — never raw chat transcripts. Whitespace collapsed, secret patterns refused via `tools.secret_scan.looks_like_secret` (shared denylist from MM-020c), **max 240 characters** (truncated with `…` if longer).
- **Recipients:** only when explicit; ids not in `config/bots.json` are listed under `unknown_recipients` (event still emitted; warning logged).
- **File:** opens with `O_NOFOLLOW` (symlinks refused); new files created **0o600**; existing files tightened to **0o600** on open.

```bash
python3 -m tools.event_emit --out /path/to/events.jsonl \
  --sender dev-1 --group build --summary "Handoff to QA for MM-020"
```

---

## Attribution rules (edges)

Derived in `ingest/edges.py` — never stored independently.

| Edge | Rule |
|------|------|
| **merge** | Merger → PR author. Merger comes from a **ledger** `merged` note’s actor, or a **~Bot signature** on a ledger-style `merged as <sha>` comment. **`merged_by` is ignored** (every GitHub action is the owner account). If no bot can be attributed: keep the merge **event**, emit **no** merge edge. Never self-loops; never `manpreet→author` from owner login. |
| **verdict** | Signature-attributed review/comment with PASS / FAIL / CHANGES / CONDITIONAL / BLOCKED / INCONCLUSIVE → reviewer → PR author. Unknown attribution → no edge. |
| **pr** | Each signature-attributed review/comment → PR author → reviewer, deduped per pair per `(repo, number)`. |
| **handoff** | Ledger assigned/handoff notes with actor + target. |

### PR identity

All PR joins use **`(repo, number)`**, never number alone (QA-MM004-8). GitHub events set `repo` (e.g. `ManpreetS2/fencepost`). Ledger notes resolve repo from GitHub URLs or `agent-mindmap PR #N` / bare `PR #N` (defaults to fencepost).

Body signatures (`~Architect 🛠️`, `~QA / Verifier 🧪`, …) are configured in `config/bots.json`.

---

## Ledger mirror contract (MM-010)

The canonical task ledger lives off the Mac. Bots push **one overwritten** file
`ledger.md` to branch **`data/ledger`** of this repo (**never `main`**, no history
kept), only when a **state-change** line appears
(`assigned` / `done` / `blocked` / `verdict` / `merge` / `handoff`), batched at
most every **3 minutes**.

### Flush helper (`tools/ledger_mirror.py`, stdlib only)

```bash
# Decide (does not update state):
python3 tools/ledger_mirror.py \
  --ledger /path/to/task-ledger.md \
  --state /path/to/mirror-state.json \
  --payload /tmp/ledger.md

# → JSON: {"flush": bool, "sha256": "...", "reason": "...", "payload": "...?"}
#
# flush is true only if content hash changed AND a new state-change line was
# added since the last flush AND ≥180s elapsed — or --force.
# Identical sha256 never flushes twice (idempotent), even with --force.

# After a successful push to data/ledger:
python3 tools/ledger_mirror.py \
  --mark-flushed <sha256> \
  --state /path/to/mirror-state.json \
  --ledger /path/to/task-ledger.md
```

Reasons: `unchanged` | `no_state_change` | `under_180s` | `state_change` | `force` | `marked` | `secret_detected`.

**SEC-MM010-1 / SEC-MM020c-2:** before any flush, the payload is scanned with
`tools.secret_scan.looks_like_secret` (shared denylist). A match refuses the
flush (`reason: secret_detected`, **line numbers only** — never the matched
text), leaves the state file untouched, and **`--force` cannot bypass** it.

### Ingest side

- `--ledger PATH` / `MINDMAP_LEDGER` — local file (default)
- `--ledger-source gh` — mirrored `ledger.md` @ `data/ledger` via `gh api`
- `activity.json` `meta.ledger`: `ok` | `error` | `skipped`
- `meta.ledger_last_entry_at` — latest dated ledger entry (UI stale banner)

---

## Events mirror contract (MM-020c)

Shared box JSONL of sanitized `NetworkEvent` lines (see `docs/MM-020-audit.md` §6.1)
is mirrored as one overwritten `events.jsonl` on branch **`data/events`**
(**never `main`**), with **7-day retention**, dedupe by `id`, and the same
flush / SEC-MM010-1 secret rules as MM-010.

### Flush helper (`tools/events_mirror.py`, stdlib only)

```bash
python3 tools/events_mirror.py \
  --events /workspace/events.jsonl \
  --state /path/to/events-mirror-state.json \
  --payload /tmp/events.jsonl

# → JSON: {"flush": bool, "sha256": "...", "reason": "...", "payload": "...?"}
#
# Invalid lines are dropped with a warning. Path default: MINDMAP_EVENTS or
# /workspace/events.jsonl.

# After a successful push to data/events:
python3 tools/events_mirror.py \
  --mark-flushed <sha256> \
  --state /path/to/events-mirror-state.json \
  --events /workspace/events.jsonl
```

### Mac fetch (`ingest/events_fetch.py`)

Allowlisted read-only `gh api` contents fetch of `events.jsonl` @ `data/events`
(ETag / sha cache). Missing branch → empty list. Entry point for the live
daemon: `fetch_events_from_gh(repo, branch="data/events") -> list[dict]`.

---

## Tests

```bash
make test
# or separately:
python3 -m pytest -q
cd web && npm test
npm run typecheck && cd web && npm run typecheck
```

MM-008 integration: `tests/test_integration.py`.  
MM-010: `tests/test_ledger_mirror.py`, `tests/test_ledger_fetch.py`.  
MM-020c: `tests/test_events_mirror.py`, `tests/test_events_fetch.py`.

---

## Layout (high level)

| Path | Role |
|------|------|
| `schema/activity.schema.json` | JSON Schema for `activity.json` |
| `shared/types.ts` | TS mirror of the schema |
| `config/bots.json` | 13 bots + owner, aliases, layout |
| `ingest/` | ledger parser, `gh` poller, edges, `build.py` |
| `web/` | Vite + React dashboard |
| `tests/fixtures/` | Ledger + mocked GitHub JSON (no network) |
| `fixtures/sample-activity.json` | Hand-written sample for UI unit tests |

---

## Credits (web UI)

Third-party libraries and adapted UI patterns (shadcn/ui, Magic UI, Tailwind, React Flow, etc.) are listed in **[CREDITS.md](CREDITS.md)** with licenses. The web app does not load fonts or scripts from CDNs at runtime.

---

## Hard constraints

1. No live Grok / room chat API — only ledger + GitHub + agent links (links only).
2. Localhost only (`127.0.0.1`).
3. No secrets in the repo; no tokens in ingest — `gh` CLI login only.
