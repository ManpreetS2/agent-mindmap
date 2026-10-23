# Agent Mind Map — Project Plan & UI Research

> Research and planning document, updated 2026-10-23. See *Status update* and *Cross-machine handoff* below for current state.
>
> Repository: https://github.com/ManpreetS2/agent-mindmap  
> Active work: [draft PR #36](https://github.com/ManpreetS2/agent-mindmap/pull/36), branch `feat/t3-readonly-activity`.
>
> **Scope:** improve the **existing** read-only Agent Mind Map for real T3 Code activity. Do not create a replacement repository, rewrite the backend unnecessarily, merge PR #36 without explicit permission, or expand into a general-purpose workflow editor.

## Visual polish completion (2026-10-23 — current)

Continued from clean local branch `t3/d4fbf680` at `c281eac` (already pushed to draft PR #36), preserving the shell/canvas work committed after `157b3b5`. Work was done directly with Codex GPT-6.1 Sol; no Claude or other delegation was used.

- Canvas labels now share a bounded screen-space text/collision envelope, retain readable overview text at tablet zoom, prioritize focused/attention agents and omit crowded details before overlapping neighbouring bodies. Delegation arrows retain a seven-pixel screen length; ordinary edges are quieter. Physics, camera preservation, event/particle semantics and backend protections are unchanged.
- Sidebar task names use the full row; status/provider metadata sits below. The settled filter accurately includes done/idle/stale states. Tablet header wraps so source and state counts remain visible.
- T3 list removes the duplicate Task column (the agent name is the task title), shows provider/model beneath names on phones, exposes current sort direction visually and keeps legacy ledger task columns. Reduced-motion styling disables panel/row transitions.
- Verification: **214 frontend tests**, **285 Python tests**, TypeScript/production build and diff whitespace check pass. Vite retains its existing large-bundle warning; jsdom/axe retains the existing canvas-context warning.
- Browser evidence: `/tmp/mmqa/codex/` contains final 1/2/12/30-agent demo screenshots at 1440×900, 768×1024 and 390×844, list screenshots and `matrix.log`. All 15 fixture/live viewport checks have no horizontal overflow or page errors. Live T3 at `127.0.0.1:8799` reported a connected source and 22 real agents at inspection time; no new auth flow or T3 write was exercised. Demo screenshots remain explicitly synthetic. The collaborative preview twice returned `Preview automation snapshot timed out after 15000ms.` so browser verification used the repository's documented Playwright/Chrome-for-Testing workflow.
- Browser harness: final run **12/12**, including drag/pin, camera persistence, reduced motion, full replay cycle, real toolbar/legend/roster geometry, demo separation and the legacy ledger dashboard. Report/screenshots: `/tmp/mmqa/codex/harness/`. Updated its stale controls selector to `.network-toolbar`, require panel geometry before overlap checks, and bounded replay-cycle sampling.
- PR #36 must remain **draft and unmerged**. The legacy daemon on 8787 was not touched. Account usage remains unavailable from the read-only MCP; no private API or credential access was added.

Older handoffs below are retained as history and are superseded by this entry.

## Status update (2026-10-23, after the handoff below — read this first)

The three worker branches from the handoff **have been integrated** into PR #36 (`feat/t3-readonly-activity`, still **draft**, never merged) on the original MacBook, and the remaining defects are fixed:

- Integrated in order: `t3/browser-qa-harness`, `t3/polish-agent-roster-inspector`, `t3/tune-network-physics-renderer` work (via `t3/astra-physics-finish` and `t3/astra-living-network`, Codex GPT-6 Astra). Worker branches were left in place.
- Security/correctness findings from the handoff are fixed with tests: path-shaped private titles are redacted (`[redacted path]`); the static demo is labelled synthetic everywhere (`mode === "demo"`); a delegation first seen after an outage, a missed stretch of polls or a wholly stale snapshot is "Newly observed" (static glow) and never "NEW DELEGATION" (backend now publishes `meta.t3.poll_sec` for the continuity bound).
- Visual defects fixed: bounded fit-to-view, label placement/culling, screen-space captions, camera centre/zoom preserved across polling and inspector resize, drag never moves the camera, settled agents are exactly still, gentler ambient motion (2.4 px), pause/reduced-motion, legend no longer overlaps the roster at tablet width, no graph-view flash on phones.
- Verification: pytest 285, vitest 193, `tsc`, `npm run build`, and the real-Chrome QA harness (`web/e2e/run.mjs`, 12/12). The harness now measures idle drift only after the 3–10 s intro layout has settled and asserts camera *centre* (not node screen position) across inspector open/close.
- Still true: live T3 usage limits are **not** exposed by the read-only MCP (see "Usage feature" below); known cosmetic issue: two "unsourced" tags overlap in the pre-existing timeline strip.

The handoff text below is kept as history.

## Cross-machine handoff (written 2026-10-23 — read this first)

Development moves to the owner's original MacBook. **Feature work is paused; all progress is on GitHub.** PR #36 stays **draft and unmerged**; `main` and the legacy daemon on port 8787 were not touched.

### Where everything is (verified on origin via `git ls-remote`)

| Ref | SHA | Contents |
| --- | --- | --- |
| `feat/t3-readonly-activity` (PR #36) | `3421ff8` + this handoff commit | T3 view = canvas network on `react-force-graph-2d`; roster, legend, inspector; legacy ledger graph unchanged (React Flow); docs. |
| `t3/tune-network-physics-renderer` | `af29522` | Astra (Codex GPT-6 Astra) renderer/physics hardening: camera save/restore across topology updates (waits until the link force holds the new links), drag no longer moves camera, pointer hook + tests, label-aware collision, particle queue. **WIP checkpoint**. |
| `t3/polish-agent-roster-inspector` | `36a9f69` | UI-polish worker (Claude): roster filter/grouping/updated-time, inspector glyph/status/copy-session-id, collapsible legend, responsive+contrast CSS. **WIP checkpoint** (inspector/legend/CSS only partly done). |
| `t3/browser-qa-harness` | `634f8d7` | QA worker (Codex GPT-6 Luna): new files only, `web/e2e/run.mjs` + README (Playwright-core harness). **WIP**, never run end-to-end against an integrated build (syntax checked only). |
| tag `checkpoint/pre-force-graph-2d` | `fb47c87` | Earlier React Flow + hand-rolled d3-force prototype, kept for recovery. |

**Merge dry-run (done 2026-10-23, `git merge-tree` against PR head `4484049`): each worker branch merges cleanly on its own, and all three merge cleanly together — zero conflicts.** (Note: `git diff 3421ff8 origin/t3/tune-network-physics-renderer` looks like it deletes `NetworkA11y.test.tsx` and edits `graph.css`; that is only because Astra's branch point `60d340d` predates `3421ff8` — use `git diff 60d340d..origin/t3/tune-network-physics-renderer` to see its real changes.)

Worker branches were cut from `3421ff8` (Astra from `60d340d`, which only adds the roster-lineage commit) and have **not** been merged into PR #36. A fourth local worktree `t3/browser-qa-t3-view` was an empty duplicate (no commits, no changes) and was intentionally not pushed.

### Test evidence at checkpoint time (honest, not final)
- PR branch `3421ff8`: pytest 249 passed; vitest 113 passed (20+ files); `tsc --noEmit` clean; `npm run build` OK (existing >500 kB chunk warning).
- `t3/tune-network-physics-renderer` `af29522`: tsc clean; vitest 22 files / 128 tests passed.
- `t3/polish-agent-roster-inspector` `36a9f69`: tsc clean; vitest 22 files / 123 tests passed.
- `t3/browser-qa-harness`: `node --check web/e2e/run.mjs` OK; not executed against a build.
- Real-browser checks (Chromium via Playwright-core, done by the lead on `3421ff8` before the split): static demo 5 agents/1 delegation; drag→pin stays put ≥3 s; wheel zoom unchanged across polls; pause freezes drift; `reducedMotion` gives zero drift; replay one full cycle max per-sample step 6.7 px, min node distance ≈85 px, no console errors; legacy graph (React Flow) still renders 14 nodes / 5 edges. Live T3 OAuth/MCP was **never** exercised (no T3 in the dev environment).

### Remaining defects / TODO (priority order)
1. **Security review findings (Codex GPT-6 Luna, read-only):**
   - *High:* `ingest/t3.py` `safe_text` redacts credential shapes but not filesystem paths: a thread title like `/Users/name/worktrees/x` is published and rendered in roster/canvas. Redact path-shaped values in the adapter + add a Python test (small hardening; do not replace the adapter).
   - *Medium:* static demo (`meta.t3.mode === "demo"`, no `replay`) is labelled as real ("Verified delegation", "Last verified activity", "T3 subagent lineage") in `MindmapView` legend and `SessionInspector`. Derive the simulated labelling from `mode === "demo"`, not `Boolean(replay)`.
   - *Medium:* an old delegation edge first seen after an outage is shown as "NEW DELEGATION" with a directional particle (`useFreshEdges`/`AgentNetwork`). Relabel "Newly observed" and consider a non-directional highlight.
   - Clean: no XSS (`nodeLabel={() => ""}`, text via React/canvas `fillText`, http(s)-only links); `npm audit --omit=dev` 0 vulnerabilities; graph deps permissive-licensed, no postinstall/telemetry.
2. **Visual defects seen on the integrated build** (Astra was asked to fix; verify on its branch): fit-to-view zoom becomes huge with only 2 agents (cap ≈1.6–2); provider/model labels collide with neighbouring nodes/rings when centres ≈85 px apart; "NEW DELEGATION" tag oversized when zoomed and drawn over the arrowhead; opening the inspector resizes the canvas (camera centre must be preserved — Astra's camera work targets this).
3. **Integrate** (not done): merge the three worker branches into `feat/t3-readonly-activity` one at a time. File ownership was disjoint, so conflicts are not expected, but dry-run each with `git merge --no-commit --no-ff <branch>` and abort if anything conflicts.
4. Re-run everything after integrating (below), then an **independent review** of the final diff (first Codex GPT-6 *Sol* review failed with "model at capacity"; use `gpt-6-astra` or `gpt-6-luna`, High).
5. Final report: files changed, final SHA, test + browser evidence, limitations (live T3 unverified). Keep PR #36 draft until the owner explicitly approves merging.

### Architecture & decisions (short)
- T3 view only is on `react-force-graph-2d` (MIT). React Flow remains for the legacy ledger graph. Independent evaluation (Astra, **GO-WITH-CHANGES**): keep stable node objects, replace `graphData` identity only on topology change (otherwise the engine reheats), restore camera after topology updates (library auto-rescales), ambient motion must not call `d3ReheatSimulation` (alpha→1) — implemented as a bounded zero-mean per-frame offset; `d3AlphaTarget` is not exposed by the wrapper; emit particles only after link initialization; particle speed is per-frame; canvas needs an accessible DOM roster (implemented).
- Truthfulness rules: a delegation edge proves lineage only; animate only newly observed, evidence-backed delegations (one-shot), never continuous particles; observed status changes flash a caption (STARTED / BLOCKED / FAILED / COMPLETED / RESUMED); missing data reads "Not reported by T3"; replay is labelled simulated; no prompts/messages/tool output/credentials.
- QA hook: with `localStorage.mindmapDebug = "1"` the page exposes `window.__mindmap.nodes()` / `zoom()` (positions only).

### File ownership used for the parallel split (reuse it to avoid conflicts)
- Renderer/physics (Astra): `components/AgentNetwork.tsx`, `utils/networkModel.ts`, `utils/nodeDraw.ts`, `utils/networkPhysics.ts`, `utils/networkCamera.ts`, `hooks/useNetworkPointer.ts`, `hooks/useFreshEdges.ts`, `utils/edgeActivity.ts` + their tests.
- UI polish: `AgentRoster.tsx`, `NetworkLegend.tsx`, `SessionInspector.tsx`, `utils/sessionInspector.ts`, `utils/provider.ts`, `styles/{graph,responsive,theme}.css`, `Inspector.test.tsx`, `NetworkA11y.test.tsx`.
- QA: new files under `web/e2e/` only.
- Lead: `views/MindmapView.tsx`, `DetailPanel.tsx`, docs, `package.json`, `test/setup.tsx`, `test/helpers.ts`, `T3.test.tsx`.
All paths are under `web/src/` unless noted.

### Continue on a different Mac — exact steps
```sh
git clone https://github.com/ManpreetS2/agent-mindmap.git && cd agent-mindmap   # or `git fetch --all --prune` in an existing clone
git fetch origin
git checkout feat/t3-readonly-activity            # PR #36 head (includes this document)
# worker branches (read-only until you decide to merge):
git branch --track t3/tune-network-physics-renderer origin/t3/tune-network-physics-renderer
git branch --track t3/polish-agent-roster-inspector origin/t3/polish-agent-roster-inspector
git branch --track t3/browser-qa-harness origin/t3/browser-qa-harness
# optional: inspect a worker without disturbing the PR branch
git worktree add ../mm-renderer t3/tune-network-physics-renderer

# toolchain: Node 24.x (dev used 24.19) + npm, Python 3.12
python3 -m venv .venv && .venv/bin/pip install -e '.[dev,t3]'
npm ci --prefix web
.venv/bin/python -m pytest -q                      # expect 249 passed
(cd web && npx tsc --noEmit -p tsconfig.json && npx vitest run && npm run build)   # expect 113 tests on the PR branch
# deterministic demos (never port 8787 — that is the legacy daemon):
.venv/bin/python -m ingest.live --source t3-demo --demo-replay --demo-step-sec 5 --port 8899
.venv/bin/python -m ingest.live --source t3-demo --port 8898
# browser QA harness (from the QA branch): npm i --no-save playwright-core ; node web/e2e/run.mjs   (set CHROME_PATH to your Chrome/Chromium)
```
Integrate in this order (smallest blast radius first): `t3/browser-qa-harness` (new files only) → `t3/polish-agent-roster-inspector` → `t3/tune-network-physics-renderer`; run `npx vitest run && npx tsc --noEmit -p tsconfig.json` after each merge. Live T3: follow `docs/t3-integration.md` (`python -m ingest.t3_mcp login --url <your MCP URL>`); do not copy credential files between machines — re-authorize on the new Mac.

### What could NOT be transferred (by design or by nature)
- **T3 delegated-agent threads/transcripts** (Astra ×2, UI polish, QA, security review) live in the old Mac's T3 app, not in Git; the branches carry their code, and their findings/briefs are summarised above. Agents cannot be resumed on another machine — re-brief new ones using the ownership list.
- Scratch tooling outside the repo: `/tmp/pw/*.mjs` (superseded by `web/e2e/` on the QA branch), `/tmp/shots/*.png` screenshots, `/tmp/legacy-dist`.
- Local-only: `.venv/`, `web/node_modules/`, `web/dist/`, `ingest/.cache/`, the Claude auto-memory file `project_t3_force_graph_handoff.md`, and T3 OAuth credentials under `~/.config/agent-mindmap/` (never copy; re-run login).
- Working-tree state of a worker that was *mid-edit* at interrupt time is captured only as of its last file write; nothing was lost that was on disk, but unwritten in-flight reasoning was.

## Mission and operating principles

Build a professional, responsive, live **AI agent observability network** for Claude Code and Codex sessions run through T3 Code on a Mac. The UI should show:

- Actual provider/model identity when reported; unknown when unavailable.
- Current task label, reported status, last verified activity, and stale/unavailable state.
- Directed, *evidence-backed* parent-to-child delegations and other supported connections.
- Status changes (active, idle, blocked, failed, completed), with restrained transitions.
- Selectable agents opening a useful, **read-only** evidence inspector.
- Usable panning, zooming, dragging, keyboard navigation, filtering, and readable layouts.
- Later: **per-account** Claude/Codex allowance, remaining percentage, reset/countdown, and freshness **only when an authorized T3 API exposes this information**.

Do not infer dialogue, active communication, continuous streaming, token counts, quotas, model thinking levels, or conversation content from the existence of a child-thread/delegation edge. Live and simulated data must remain unmistakably separate.

## Current integration: preserve the working baseline

- Draft PR #36 is the integration under review. At research time its inspected head was `af61dc6c0df398a58718a9bd1af742362e05167e`; newer commits may supersede that SHA.
- The prior handoff reports 249 Python tests passing, 67 frontend tests passing, typecheck passing, and production build passing; these are **reported results**, not re-executed as part of this research.
- Previous local observations reported 13 real T3 session nodes and 9 real delegation edges; do not treat these as a permanent current count.
- The T3 source is authenticated, read-only MCP; metadata-only publishing, safety checks, real session IDs, replay mode, and current legacy ingestion remain.
- Existing UI architecture: React 18, `@xyflow/react` 12, Dagre, `motion`, `AgentGraph.tsx`, `AgentFlowNode.tsx`, `AgentNodeCard.tsx`, `HandoffEdge.tsx`, `DetailPanel.tsx`, `MindmapView.tsx`, and existing timeline/tests.
- On the original machine, the T3 dashboard was observed at `http://127.0.0.1:8799/`; the legacy daemon uses `http://127.0.0.1:8787/`. **Do not disturb port 8787, its daemon, or its output files.** On other laptops, ports must be checked; they are not universally assigned.
- Preserve the four fixes reported in the handoff: metadata credential sanitization, port-collision output isolation, out-of-order polling protection, and concurrent OAuth credential-write protection. The final small change still warrants independent review.

See [docs/t3-integration.md](docs/t3-integration.md) for supported MCP auth, source modes, and CLI instructions. Do not mix synthetic replay with real mode.

## GitHub UI research (source inspected 2026-10-23)

| Repository | Maintenance / license at inspection | Worth borrowing | Do **not** borrow |
| --- | --- | --- | --- |
| [xyflow/xyflow](https://github.com/xyflow/xyflow) | Actively maintained; MIT | React Flow custom-node/edge idioms, floating edges, viewport utilities, interaction examples | Another renderer or a wholesale graph rewrite |
| [langfuse/langfuse](https://github.com/langfuse/langfuse) | Actively maintained; MIT core; enterprise directories have separate restrictive license | Compact trace nodes, zoom-aware labels, search/selection sync, dimming nonmatches, aggregated vs expanded observation semantics | Its ELK/D3 graph renderer, observability backend, enterprise code, or trace content not in our source |
| [langflow-ai/langflow](https://github.com/langflow-ai/langflow) | Actively maintained; MIT | Readable model/status vocabulary, handles, polished node visual hierarchy | Its workflow editor controls, state stores, forms, and heavyweight flow execution logic |
| [myUdav4iik/agent-canvas](https://github.com/myUdav4iik/agent-canvas) | Small/limited maintenance evidence; MIT | Execution-state-to-node projection, compact trace chronology concept | Editable agent configuration inspector or streaming text UI without permission |
| [Zaid7829/AgentFlow](https://github.com/Zaid7829/AgentFlow) | Small/limited maintenance evidence; MIT | Selective status styling | Unconditionally animated edges; default-zero telemetry that appears measured |
| [Ptander01/agent-flow-visualizer](https://github.com/Ptander01/agent-flow-visualizer) | Small/limited maintenance evidence; `package.json` claims MIT but no root LICENSE found | Hover spotlight, focus/zoom, restrained replay ideas, gradient edge visuals | Substantial code until licensing is clarified, giant rotating HUD nodes, constant cinematic camera, or claims of real-time streaming: its README calls it static playback |

**Legal note:** This repository is Apache-2.0. Retain source notices for any permitted third-party code. The Langfuse root LICENSE excludes enterprise directories. Prefer adaptation of ideas with code written to our existing contracts; copying should be deliberate, not automatic.

### Exact source references

- React Flow [floating edge](https://github.com/xyflow/xyflow/blob/main/examples/react/src/examples/FloatingEdges/FloatingEdge.tsx) and [node inspector example](https://github.com/xyflow/xyflow/blob/main/examples/react/src/examples/DevTools/DevTools/NodeInspector.tsx).
- Langfuse [GraphNode](https://github.com/langfuse/langfuse/blob/main/web/src/features/trace-graph-view/components/GraphNode.tsx), [TraceGraphView](https://github.com/langfuse/langfuse/blob/main/web/src/features/trace-graph-view/components/TraceGraphView.tsx), [ElkGraphRenderer](https://github.com/langfuse/langfuse/blob/main/web/src/features/trace-graph-view/components/ElkGraphRenderer.tsx), and [elkLayout](https://github.com/langfuse/langfuse/blob/main/web/src/features/trace-graph-view/layout/elkLayout.ts).
- Langflow [NodeStatus](https://github.com/langflow-ai/langflow/blob/main/src/frontend/src/CustomNodes/GenericNode/components/NodeStatus/index.tsx) and [CustomEdges](https://github.com/langflow-ai/langflow/blob/main/src/frontend/src/CustomEdges/index.tsx).
- Agent Canvas [FlowCanvas](https://github.com/myUdav4iik/agent-canvas/blob/main/apps/web/src/components/canvas/FlowCanvas.tsx) and [TraceTimeline](https://github.com/myUdav4iik/agent-canvas/blob/main/apps/web/src/components/runs/TraceTimeline.tsx).
- AgentFlow [AgentNode](https://github.com/Zaid7829/AgentFlow/blob/main/apps/web/components/canvas/AgentNode.tsx) and [AnimatedDataEdge](https://github.com/Zaid7829/AgentFlow/blob/main/apps/web/components/canvas/AnimatedDataEdge.tsx).
- Agent Flow Visualizer [GraphCanvas](https://github.com/Ptander01/agent-flow-visualizer/blob/main/client/src/components/GraphCanvas.tsx), [AnimatedEdge](https://github.com/Ptander01/agent-flow-visualizer/blob/main/client/src/components/AnimatedEdge.tsx), and [ReplayGraphCanvas](https://github.com/Ptander01/agent-flow-visualizer/blob/main/client/src/components/ReplayGraphCanvas.tsx).

**Chosen combination:** retain React Flow as renderer; borrow Langfuse-style observability interactions, selective Langflow visual hierarchy, and only focused concepts from smaller demos. This is a **monitoring dashboard**, not an agent editor or decorative screensaver.

## Specific source-level problems to address

These were inspected on PR #36 (no local execution was performed during this research):

1. **T3 is grid-positioned.** `ingest/t3.py` computes `layout` as a four-column slot grid. In `AgentGraph.tsx`, `if (activity.meta.t3) return activity.nodes` bypasses Dagre. Move appropriate T3 topology-aware placement to the frontend, without breaking stable IDs or the legacy graph.
2. **Stale node coordinates override new automatic layouts.** `AgentGraph.tsx` maps every prior position back over `builtNodes`. Separate saved *user-pinned/dragged* positions from fresh auto-layout coordinates; otherwise relayout changes never appear. Preserve viewport/selection during polling.
3. **Delegation edges do not use the existing handoff particle condition.** `isRecentHandoff` returns false for non-`handoff` edges, while T3 relationships use `delegation`. Do not simply make delegation edges permanently animated: show a short transient effect only when a **new, supported** delegation event is observed.
4. **A 36-hour 'recent handoff' window is not active communication.** Distinguish persistent historical relationships, recent changes, and independently supported message/activity evidence. Never render an indefinitely flowing edge that implies a live conversation.
5. **Inspector content is metadata-only.** `DetailPanel.tsx` can show T3 session state, model/project/branch, reported time, source, and evidence links, but the adapter explicitly omits prompts, messages and tool outputs. Treat absent details as unavailable, not empty or invented.

## Proposed UI architecture

- **Canvas:** controlled React Flow with existing nodes, edges, minimap, and keyboard navigation. Node identity and location should not jump on each poll. Automatic layout must be deterministic, edge-aware, stable, and avoid collisions. Consider ELK only if real dense/compound examples prove Dagre insufficient.
- **Nodes:** compact labels, provider/model visibly differentiated, one short current-task line, strong but accessible status affordance. Use truncation and zoom-dependent simplification; keep full facts in inspector, not giant repeated cards.
- **Edges:** directed with verified type/provenance; clear distinction between delegation, task handoff, review verdict, PR, and merge. Route by actual handles/geometry. Animation signifies observed **new events**, not assumed continuous messaging. Honor `prefers-reduced-motion`.
- **Inspector:** contextual details, last verified activity, task/branch/project, reported status and provenance, and a chronological list of **authorized events**. Explicitly explain missing conversation content.
- **Navigation:** pan, zoom, fit, drag, hover focus, selected-neighborhood highlighting, filtering, and accessible keyboard interactions. Search misses may dim, but should not erase contextual paths. Avoid auto-pan every time new polling data arrives.
- **Live/demo trust:** explicit mode label, timestamps, freshness/stale/unavailable/error states, and deterministic replay that remains isolated from real T3 data.

### Usage feature — dependency, not permission to scrape

T3's internal `ServerProvider.usageLimits` / Usage → Limits holds usage windows, but the currently investigated external Read-only MCP API does **not** expose these limits. Preferred approach: propose a minimal upstream **read-only, sanitized, per-account MCP usage projection**, with session/weekly percentages, resets, observed time, and explicitly unsupported/missing states. Account labels must not leak tokens or credential paths. **No upstream contribution has been implemented or accepted.**

Do **not** build a private WebSocket RPC client, scrape the T3 GUI, inspect Keychain/private databases, guess quota numbers, or add paid API credentials. Until authorized exposure exists, use the in-app T3 Usage → Limits screen and leave dashboard quota values unavailable.

## Development sequence (no implementation authorized by this document)

1. Verify PR #36 remains green, draft, and isolated; independent review of the final hardening fix.
2. Stabilize T3 topology-aware layout and separation of automatic vs user-pinned coordinates.
3. Improve node density, labels, provider identity, connection geometry, status colors, and motion semantics.
4. Improve read-only inspector and event provenance without widening raw private-data exposure.
5. Validate live mode and replay independently in a real browser at useful viewport sizes; check keyboard/zoom/reduced-motion and no unnecessary viewport jumps.
6. Confirm privacy invariants, no port 8787 interruption, credentials absent from browser JSON, deterministic replay fixtures, and no fabricated telemetry.
7. Run frontend/Python tests, typecheck, production build, security review, and independent Codex review. Obtain explicit owner approval **before merging**.

## Acceptance checklist

- [ ] Live T3 graph resembles a connected communication **network**, not a fixed grid of task cards.
- [ ] Actual edge direction and attribution are correct; no inferred bidirectional chat.
- [ ] Nodes remain stable across polls, but graph can intelligently reflow when topology changes.
- [ ] Manual dragging/pinning and fit/zoom/pan work predictably.
- [ ] Provider/model/status/task metadata is legible; stale/unknown are honest.
- [ ] Real T3 delegation triggers event-sensitive visualization, never permanent false activity.
- [ ] Clicking a node opens an evidence-based, privacy-safe inspector.
- [ ] Live and demo replay cannot be mistaken for one another.
- [ ] Responsive layout, keyboard accessibility, and reduced-motion behavior are verified.
- [ ] No disruptions to the legacy daemon, no leaked credentials, and no unauthorized T3 writes.
- [ ] Tests, production build, and independent review are completed; PR remains unmerged until authorized.

**Decision update (2026-10-23):** the owner superseded the "no force physics" guidance. The T3 view now uses React Flow + `d3-force` (see docs/t3-integration.md → *Network UI*). `react-force-graph-2d` was evaluated on paper (canvas rendering would drop accessible DOM nodes and existing tests) and not prototyped. Account-usage integration remains an unimplemented plan (section above).
