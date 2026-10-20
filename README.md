# agent-mindmap (MINDMAP)

Read-only agent-activity dashboard for the Fencepost bot team.

**Pipeline:** `task-ledger.md` + GitHub (`gh api`) → `ingest/build.py` → `web/public/activity.json` → Vite/React UI on **127.0.0.1**.

MINDMAP never posts, merges, or writes to the ledger. It never stores GitHub credentials.

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
```

- Ledger: `--ledger PATH` / `MINDMAP_LEDGER`, or `--ledger-source gh` for the allowlisted `data/ledger` mirror (same fetcher as `make refresh-gh-ledger`).
- Poll intervals: `--ledger-poll-sec` / `--gh-poll-sec`, or `MINDMAP_LEDGER_POLL_SEC` / `MINDMAP_GH_POLL_SEC` (defaults 30s / 60s).
- Endpoints: `/` (static `web/dist`), `/activity.json` (ETag + `If-None-Match` → 304), `/healthz` (poll timestamps + errors).
- GitHub: same read-only `gh api` allowlist as ingest; no tokens stored or logged.
- macOS autostart: copy `ops/com.manpreet.mindmap.plist` into `~/Library/LaunchAgents/`, set `WorkingDirectory`, `MINDMAP_LEDGER`, and log paths under `~/Library/Logs/mindmap/`, then `launchctl load` it. Validate with `plutil -lint ops/com.manpreet.mindmap.plist` (macOS only; CI skips on Linux).

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

**SEC-MM010-1:** before any flush, the payload is scanned with the same
`_looks_like_secret` helper used by the GitHub poller. A match refuses the flush
(`reason: secret_detected`, **line numbers only** — never the matched text),
leaves the state file untouched, and **`--force` cannot bypass** it.

### Ingest side

- `--ledger PATH` / `MINDMAP_LEDGER` — local file (default)
- `--ledger-source gh` — mirrored `ledger.md` @ `data/ledger` via `gh api`
- `activity.json` `meta.ledger`: `ok` | `error` | `skipped`
- `meta.ledger_last_entry_at` — latest dated ledger entry (UI stale banner)

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

## Hard constraints

1. No live Grok / room chat API — only ledger + GitHub + agent links (links only).
2. Localhost only (`127.0.0.1`).
3. No secrets in the repo; no tokens in ingest — `gh` CLI login only.
