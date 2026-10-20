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

### Live refresh (Fencepost data)

```bash
export MINDMAP_LEDGER=/absolute/path/to/build/task-ledger.md
make refresh
# → writes web/public/activity.json (gitignored)
```

If GitHub/`gh` fails, ingest still writes a **ledger-only** snapshot with `meta.github: "error"`.

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

The UI fetches `/activity.json` via `web/src/data/loadActivity.ts`. There is no backend server, socket, DB, or auth.

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

## Tests

```bash
make test
# or separately:
python3 -m pytest -q
cd web && npm test
npm run typecheck && cd web && npm run typecheck
```

MM-008 integration coverage: `tests/test_integration.py` (fixture ledger + mocked `gh` → schema-valid `activity.json`).

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
