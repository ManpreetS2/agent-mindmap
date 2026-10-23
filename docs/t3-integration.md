# T3 Code read-only monitoring

This is an adapter for the existing mind map, not an orchestrator. Legacy ledger/GitHub ingestion remains the default. The T3 source is opt-in and never calls agent execution, messaging, cancellation, merge or configuration tools.

## Start here

Use Python 3.12+ and Node/npm from the existing setup. In this repository:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev,t3]'
npm ci --prefix web
npm run build --prefix web
```

For deterministic offline mode (no T3 installation, authentication or network required):

```sh
python -m ingest.live --source t3-demo
```

Open http://127.0.0.1:8787. The header explicitly says **DEMO — offline fixtures**. Five example threads demonstrate Codex, Claude Code, delegation, waiting, completion and failure. Model strings are deliberately labeled examples (`reported-codex-model`, `reported-claude-model`), not claims about a real model. The observation clock is frozen at 2026-10-22 20:00 UTC. Tests exercise transitions separately; the static demo does not invent a stream of activity. For an explicitly synthetic animated scenario, use `python -m ingest.live --source t3-demo --demo-replay --demo-step-sec 5`; see the README for stage/cadence details.

## Connect your installed T3

1. Start T3 Code. In **Settings → Connections**, copy the running environment's **MCP URL**. Do not assume the default port below matches your installation. You can inspect `t3 --version` and `t3 thread --help` if that CLI is installed.
2. Authorize the dashboard from a terminal on the same machine as its browser:

   ```sh
   python -m ingest.t3_mcp login --url http://127.0.0.1:3773/mcp
   ```

   Replace the URL with the copied value. A browser sign-in opens. Approve **Agent Mindmap (read only)** with **Read only** access. Use T3's normal sign-in/pairing flow; do not copy provider-session bearer tokens. The callback listens on `127.0.0.1:18789` for up to three minutes. This milestone requires a browser on that host for login.
3. Start monitoring with the same URL:

   ```sh
   python -m ingest.live --source t3 --t3-url http://127.0.0.1:3773/mcp
   ```

4. Open http://127.0.0.1:8787 and start a task normally in T3. A discovered thread becomes a graph node. Its actual latest-run model is displayed only if returned by T3. A child with `relationshipToParent: subagent` becomes a delegation edge when both threads are present.
5. If access expires or is revoked, the dashboard preserves the last snapshot as stale. Repeat the login command to renew access. Revoke the dashboard under T3 Settings → Connections when finished.

The adapter uses the official Python MCP SDK (optional `t3` extra), OAuth discovery/PKCE, refresh support and authenticated Streamable HTTP. Access/refresh tokens and client registration are stored with mode `0600` under `~/.config/agent-mindmap/`, keyed by a hash of the MCP URL. They are never sent to the browser or included in activity/error output. The static directory cannot contain that credential location. TLS is required except on loopback; credential-bearing URLs are rejected.

An unavailable or incompatible installation is **unavailable**, not an automatic switch to fictional live data. Explicit `--source t3-demo` is the offline fallback.

## Compatibility and official evidence

Investigated the official T3 repository at commit `23bd753806eb9db5a315fbf9ac6563d355f20b3a`:

- [Outside agents](https://github.com/pingdotgg/t3code/blob/23bd753806eb9db5a315fbf9ac6563d355f20b3a/docs/user/outside-agents.md): external OAuth clients, Read only approval and host-local CLI.
- [Orchestrator MCP server](https://github.com/pingdotgg/t3code/blob/23bd753806eb9db5a315fbf9ac6563d355f20b3a/docs/orchestration-v2/orchestrator-mcp-server.md): durable thread reads, lineage, provider capabilities.
- [Public contracts](https://github.com/pingdotgg/t3code/blob/23bd753806eb9db5a315fbf9ac6563d355f20b3a/packages/contracts/src/orchestratorMcp.ts): thread list/read, recent runs, nullable metadata, pagination.
- [CLI thread implementation](https://github.com/pingdotgg/t3code/blob/23bd753806eb9db5a315fbf9ac6563d355f20b3a/apps/server/src/cli/thread.ts): `t3 thread list --json` explicitly sets `includeSubagents: false`. It is insufficient for complete delegation discovery, so this adapter uses MCP instead.
- [Project tools](https://github.com/pingdotgg/t3code/blob/23bd753806eb9db5a315fbf9ac6563d355f20b3a/apps/server/src/mcp/toolkits/project/tools.ts) and [environment tools](https://github.com/pingdotgg/t3code/blob/23bd753806eb9db5a315fbf9ac6563d355f20b3a/apps/server/src/mcp/toolkits/environment/tools.ts).

No installed T3 exists in the implementation environment. Consequently, no particular locally installed version or successful live OAuth connection is claimed. At connection time, `tools/list` must advertise `t3_project_list`, `t3_thread_list` (with `includeSubagents`) and `t3_thread_read`. Missing required capabilities fail closed; optional provider/environment metadata stays unknown. T3's reported server version is retained in `meta.t3.server_version`. Older installations without the outside-agent interface need an appropriate T3 update; the adapter does not bypass their authentication.

## Data pipeline and audit

Existing flow: `ingest/build.py` / `ingest/live.py` → ledger parsing + GitHub polling → schema-validated `activity.json` → `activityTransport` → `useActivityFeed` → existing React Flow and detail views.

Original coupling found:

- `build_nodes` iterates the fixed `config/bots.json` roster and matches ledger owners/aliases.
- The schema and TypeScript contract fixed `project` to `fencepost`; task IDs encode ledger conventions.
- The graph's grouping/layout assumes owner/build/QR/radar; detail panels describe ledger facts and Cursor cloud links.
- The transport silently retained old data on failure and delivered identical snapshots repeatedly; graph updates could reset dragged positions.

T3 flow: authenticated MCP read tools → `ingest/t3.py` allowlisted metadata projection → `T3Daemon` (existing HTTP handler and atomic writer) → the same activity transport and React components. The legacy task model remains intact; T3 thread titles are session tasks, not fabricated ledger IDs. `session` metadata, `sessions` group, `FAILED`/`STALE` states and `delegation` edges extend the contract. Old fixtures remain valid.

Only five read tools are allowlisted: environment read, project list, capabilities, thread list and thread read. No arbitrary MCP proxy is exposed to the browser. Prompts, messages, tool output, worktree paths, environment preferences and credentials are excluded from the published snapshot. Free-form display metadata (titles, project names, branches, model labels) is untrusted: it is Unicode-normalized, stripped of control/zero-width characters and checked against credential shapes (Authorization/Bearer/Basic headers, Slack, GitHub, GitLab, npm, AWS, Google and `sk-` style keys, JWTs, PEM headers, URL userinfo, sensitive `key=value`/`key: value` assignments, long mixed-case or hex blobs). A suspicious value is replaced **entirely** with `[redacted]` rather than partially scrubbed. Status, driver and server-version fields use a strict allowlist, and threads whose IDs are not plain identifiers are dropped. This is defense in depth, not a guarantee; titles should still be treated as private metadata.

Startup binds the localhost port **before** the first poll or write, so a port conflict (for example with a legacy daemon on 8787) exits with status 2 without touching any activity file. T3 sources default to their own output and cache under `ingest/.cache/t3/<source>/` (`activity.json`, `cache/`), never the legacy `web/dist/activity.json`; explicit `--activity-out`/`--cache-dir` still win. The browser transport orders overlapping requests by start time and discards older 200/304 responses once a newer one is applied, and OAuth credential writes use a lock file, a unique private temp file and atomic replace.

Default T3 polling is 15 seconds, followed by the existing 10-second browser polling. Each source poll has a 60-second total timeout; MCP requests have a 20-second timeout. Unchanged thread details are cached using the complete list record; all discovery remains paginated. Limits: 50 projects, 500 threads, 10 pages of 100 records. Exceeding limits or failing partway through a read preserves the last complete snapshot instead of publishing a misleading partial one.

Snapshot fingerprints and HTTP ETags suppress duplicate writes/delivery. IDs derive from source URL identity plus thread ID. Graph slots are stable for the lifetime of the daemon; dragged positions survive feed refreshes. Positioning and animation are frontend-only (see *Network UI* below); the backend still publishes only its stable grid `layout`, which the T3 view ignores.

## Status semantics and limits

- `running`, `starting`, `preparing` → in progress; `queued`/`waiting` → blocked/waiting; `idle` → idle; `completed` → done; `failed` → failed. Interrupted/cancelled/rolled-back and unknown future states remain unknown, with the exact reported status available in details. Completion means the reported thread/run state, not independent verification that its code is correct.
- A thread's `updatedAt` is the last verified **T3 thread update**, not proof of a specific tool execution. Unchanged timestamps older than five minutes make active/waiting sessions stale even while T3 remains reachable. A legitimate quiet long-running task may therefore be marked stale; it is never presented as verified ongoing work without fresh evidence. Configure with `--t3-stale-sec` (at least twice the poll interval).
- Disconnection marks retained nodes stale immediately after detection. The browser also ages active nodes if the server continues returning an old snapshot. Recovery updates the same IDs. Retention is in memory during a daemon session; restarting offline starts empty rather than trusting a previous mode's disk snapshot.
- Provider names come from `providerInstanceId` joined to capabilities `driverKind`: `codex` → Codex, `claudeAgent` → Claude Code. Unknown drivers stay as reported; missing providers/models are explicitly unknown. Model is read from the matching latest run, not inferred from titles or the currently selected thread model.
- Only explicit T3 subagent lineage creates edges. Forks, similar titles, shared branches, timestamps and native provider subagents without T3 child threads do not create delegation edges.
- Branch and linked GitHub PR URL are shown when reported. Issue associations, arbitrary communication edges, token usage, billing and hidden/native subagent relationships are unsupported. No issue number is guessed from a branch/title. Thread IDs are shown for lookup in T3; no undocumented browser route is invented.
- Timeline entries summarize currently observed T3 status and lineage. This milestone is a snapshot monitor, not a durable event archive; intermediate transitions between polls may be missed.
- One T3 environment per daemon. Switching URL changes the source namespace. Remote HTTPS works with T3 OAuth; the dashboard itself still binds only to localhost. No terminal scraping or private database access.

## Verification

Implementation results: **124 Python tests passed, 1 skipped; 61 frontend tests passed; TypeScript and production build passed; new adapter/test lint passed.** Repository-wide Ruff has 35 pre-existing findings (including an executable-bit finding in this connector-fetched checkout).

Run `python -m pytest -q`, `npm test --prefix web`, `npm run typecheck --prefix web`, and `npm run build --prefix web`. New Python files can be linted with `python -m ruff check ingest/t3.py ingest/t3_live.py ingest/t3_mcp.py tests/test_t3.py` (install Ruff separately).

Automated tests cover both providers, simultaneous sessions, delegation vs fork, statuses, unavailable/stale/reconnected sessions, duplicate delivery, unknown metadata, pagination bounds, cache behavior, token permissions, unsafe URLs, read-only calls, source projection and legacy fixtures. Frontend tests cover dynamic nodes/details, DEMO labeling, conditional requests, reconnect after initial failure and stale data despite 304 responses. A local HTTP fixture smoke test verifies snapshot/schema, ETag 304, health and POST 405.

A real T3 connection and OAuth handshake remain unverified. Browser screenshot verification was attempted but could not run: Chromium was absent and its download failed. React/Vitest DOM and accessibility tests ran; the existing jsdom canvas warning limits color-contrast coverage. The build reports the existing >500 kB chunk warning. There is no configured frontend lint script; repository-wide Ruff reports pre-existing legacy violations, while new adapter/test files pass.

## Later direct CLI monitoring

Add separate source adapters behind the same normalized contract, using documented Claude Code hooks/events and Codex app-server/structured events after reviewing the installed versions. Keep provider-native IDs, provenance and genuine parent-child links. Do not infer work from terminal text. Multi-environment selection, durable event history and incremental MCP activity reads can follow without turning this dashboard into an agent executor.

## DEMO REPLAY verification

The optional `--demo-replay --demo-step-sec 5` uses a pure elapsed-time scenario in `ingest/t3.py` and the existing daemon/writer/HTTP transport. The synthetic clock advances only at stage boundaries. Repeated reads within a stage retain the same snapshot and ETag; later cycles change timestamps without accumulating entities. Two session IDs survive all stages, with a single delegation edge only in stages 4–9 (one-based display). Stage 10 clears the tasks/edge, then stage 1 begins the next cycle. No source discovery, static fixture read, provider/API execution or GitHub poll runs in replay mode.

The daemon checks replay every 0.5 seconds; the existing browser transport detects demo replay metadata and uses conditional polling every 0.5–1 seconds, including rescheduling its first timer when replay is discovered. Static demo and real T3 keep their normal polling cadence. Replay is rejected for real/legacy sources. The ten stages follow elapsed time rather than queued frame delivery, so suspended tabs or slow connections can miss stages.

Verification for this update: **147 Python tests passed, 1 skipped; 64 frontend tests passed; TypeScript and production build passed; replay adapter/test lint passed.** Injectable-clock tests cover every status transition, exact boundaries, multiple cycles, stable IDs/layouts, bounded events/edges, ETags, restart and source isolation. HTTP tests verify 304, updated snapshots and edge removal. React tests cover every stage through the real feed, cadence isolation, status pulses and graph reconciliation preserving dragged coordinates/selection. A spring-with-three-keyframes error exposed by the replay test was fixed by using a short tween for the existing status pulse; the reduced-motion branch remains unchanged.

Full visual/browser testing remains **unverified**: the local Playwright Chromium executable is absent, and the available cloud browser returned `ERR_CONNECTION_REFUSED` for the actual local replay server. No public bind or tunnel was added. Existing jsdom canvas and bundle-size warnings remain. The original live T3/OAuth verification boundary is unchanged.

## Network UI (living force-directed graph)

The T3 view is a canvas network rendered with `react-force-graph-2d` (MIT; d3-force physics inside). The legacy ledger graph still uses React Flow. History: a React Flow + hand-rolled `d3-force` prototype (tag `checkpoint/pre-force-graph-2d`) was replaced because DOM cards cannot give the organic, compact-node feel; accessibility is preserved by an equivalent DOM roster (below). An independent engineering evaluation (Codex GPT-6 Astra) rated this choice GO-WITH-CHANGES; its changes are applied (stable node objects, `graphData` replaced only on topology change, camera preservation, alpha-independent ambient motion).

- **Nodes:** circles for Claude, hexagons for Codex (shape *and* colour), a status ring with a glyph (play = working, pause = blocked, × = failed, ✓ = done, dashed = stale/unknown), the reported model under the node, the task on hover/selection/zoom. Unknown providers/models read "Unknown provider" / "Model not reported".
- **Motion:** deterministic seeding; agents repel, delegations act as springs, collisions keep nodes apart. Positions persist between polls — `graphData` identity changes only when agents or relationships are added/removed, so status polls never re-heat or move anything. Active agents (`IN_PROGRESS`/`IN_REVIEW`, not stale) get a few pixels of bounded, zero-mean ambient drift; idle/finished agents are still. **Pause motion** stops the ambient motion; `prefers-reduced-motion` computes the layout up front (warmup ticks) and animates nothing.
- **Events:** an *observed* status change flashes a ring and a caption (STARTED / BLOCKED / FAILED / COMPLETED / RESUMED) for ~2.4 s — never on the baseline load. A verified delegation (its evidence event is in the snapshot) first *observed* after the baseline emits one short particle pulse plus a "NEW DELEGATION" tag for ~6 s; baseline loads, source/mode switches and replay restarts animate nothing. Edges are otherwise static arrows (parent → child) described as lineage, never traffic.
- **Interaction:** drag pins a node ("Release N pinned" frees them), wheel/pinch zoom, pan, hover/selection dims everything except the neighbourhood, click opens the inspector. The camera fits once after the first layout and on "Fit view"; polls never move it.
- **Accessibility:** the canvas is not focusable, so an *Agents* roster lists every agent (provider, model, status text, task, delegation lineage) with the same selection behaviour and arrow-key navigation. Status and provider are never colour-only.
- **Privacy:** unchanged. Only fields already published by the read-only adapter are drawn; nothing new is fetched.
- **QA hook:** with `localStorage.mindmapDebug = "1"` the page exposes `window.__mindmap.nodes()` / `zoom()` (positions only) for browser tests.
