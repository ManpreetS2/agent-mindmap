# agent-mindmap

Agent activity mind map dashboard for Manpreet's bot team (MINDMAP). Read-only: ledger + GitHub (`gh` CLI) → `activity.json` → static UI (later tasks).

## MM-001 — data schema and bot roster

| Path | Purpose |
|------|---------|
| `schema/activity.schema.json` | JSON Schema 2020-12 for `activity.json` (nodes, tasks, events, derived edges, `meta.github`) |
| `shared/types.ts` | TypeScript types mirroring the schema |
| `config/bots.json` | 13 bots + owner Manpreet: ids, display names, `~Name` signature aliases, groups (`owner` / `build` / `qr` / `radar`), fixed graph layout |
| `fixtures/sample-activity.json` | Hand-written Fencepost-shaped sample (e.g. PR #5 squash-merged as `693ebc7`) |

Event facts carry `source_url`, `source_time` (ISO 8601 with offset), and `attribution.method` (`signature` \| `ledger_owner` \| `unknown`). Edge types: `handoff`, `verdict`, `pr`, `merge`.

### Verify locally (no network)

```bash
# Python: schema + fixture + bots roster
python -m pip install -e ".[dev]"
pytest -q

# TypeScript: shared types
npm install
npm run typecheck
```
