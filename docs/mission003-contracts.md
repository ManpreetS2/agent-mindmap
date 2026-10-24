# Mission 003 — shared contracts and file ownership

Base: PR #38 branch `feat/pages-observability-preview`. Workers branch from the contract commit and push **only their own branch**.
Only the commander updates PR #38. Never merge PR #36/#38 into `main`. No LaunchAgent may be enabled. Public Pages stays DEMO-only.

## The document the UI consumes: `GET /observability.json`
Schema `schema/observability.schema.json`, types `shared/observability.ts`, fixtures `fixtures/observability/*.json`
(demo, live-mixed, live-all-unknown, live-collector-down, reader-other-owner). The collector daemon serves it next to
`/activity.json` (commander wires it; until then use the fixtures). Contains no hostnames/usernames/paths/credentials.
`session.account` (optional `{id,label}` = T3 provider instance, e.g. `claudeAgent_2` / "Claude2") may appear on sessions in
`/activity.json` once the commander adds it to the adapter; the UI must tolerate its absence.

## Python interfaces (so workers integrate without waiting on each other)
Runtime engineer provides:
- `tools/machine_identity.py`: `MachineIdentity(id, label, role, platform)`; `load_identity(config_dir=None) -> MachineIdentity | None`
  (None until initialised), `init_identity(label, role="reader", config_dir=None)`. File `<config_dir>/machine.json`
  (default `~/.config/agent-mindmap/`, override env `AGENT_MINDMAP_CONFIG_DIR`), dir 0700 file 0600. `id` = `mac-` + 8 random hex
  (never from hostname/username/MAC). Default role is `reader`.
- `tools/publisher_ownership.py`: lease/epoch fencing recorded inside `latest.json` as an additive `publisher` object
  `{machine_id,label,epoch,lease_expires_at,state:"active"|"released"}` (the two-file feed contract is unchanged);
  `decide(remote_feed|None, identity, now) -> Decision(action in publish|refuse|claim_required, reason)`;
  `feed_health(state_dir=None, now=None) -> dict` shaped exactly like `FeedHealth` in `shared/observability.ts`.
  CLI: `python -m tools.publisher_ownership status|claim|release|handover`. A takeover of an unexpired lease needs an explicit flag.
Quota engineer provides:
- `tools/quota/` package; `tools.quota.api.pools(now=None, state_dir=None) -> list[dict]`: exactly the five `QuotaPool` objects
  (order `claude-1, claude-2, cursor-premium, devin-free, codex`), staleness computed at call time. CLI `python -m tools.quota collect|show|manual|claude-statusline`.
  Default state dir `~/.local/state/agent-mindmap-quota/` (env `AGENT_MINDMAP_QUOTA_DIR` overrides), files 0600, dir 0700.

## Ownership (edit ONLY your files; everything else is read-only for you)
| Thread | Owns | Branch |
| --- | --- | --- |
| Commander | `schema/**`, `shared/**`, `fixtures/**`, `ingest/**`, `tools/observability_doc.py`, `tools/export_observability.py`, `.github/**`, `docs/mission003-contracts.md`, `docs/runbook-this-mac.md`, integration on PR #38 | `feat/pages-observability-preview` |
| Runtime engineer | `tools/machine_doctor.py`, `tools/bootstrap_mac.py`, `tools/machine_identity.py`, `tools/publisher_ownership.py`, `tools/publish_observability.py`, `tools/runtime_install.py`, `tools/publisher_launchd.py`, `tools/run_collector.py`, `tests/test_machine_*.py`, `tests/test_bootstrap_*.py`, `tests/test_publisher_*.py`, `tests/test_runtime_*.py`, `docs/multi-machine.md` | `m003/runtime` |
| Quota engineer | `tools/quota/**`, `tests/test_quota_*.py`, `docs/quota-sources.md` | `m003/quota` |
| UI engineer | `web/**` (except `web/e2e/**`), `docs/command-center-ui.md` | `m003/ui` |
| QA | `tests/qa/**`, `docs/qa/**` (new files only; never edit product code, report defects) | `m003/qa` |
| Integration/E2E | `web/e2e/**`, `docs/e2e.md` | `m003/e2e` |

## Hard rules for every worker
No tokens, OAuth material, Keychain, or other machines' credentials; no scraping private stores or internal endpoints;
zero LLM calls from collectors/tests; no `launchctl bootstrap/load`, no LaunchAgents writes outside temp dirs in tests; never touch port 8787, 8799 (the persistent collector's port) or Agent Control;
use your own port range; do not delete worktrees/runtime installs; paths with spaces must work; no hardcoded `/Users/<name>`; tests use temp dirs and a real local git remote, never the real private repo.
Python tests: `cd <your worktree> && /Users/manpreet/Desktop/agent-mindmap/.venv/bin/python -m pytest -q` (baseline at the contract commit: 351 passed).
Frontend: `cd web && npm ci && npx vitest run && npx tsc --noEmit -p tsconfig.json && npm run build`.
