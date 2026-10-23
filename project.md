# Agent Mind Map — Project Plan & UI Research

> Research and planning document, updated 2026-10-23. **Proposal, not implementation completion evidence.**
>
> Repository: https://github.com/ManpreetS2/agent-mindmap  
> Active work: [draft PR #36](https://github.com/ManpreetS2/agent-mindmap/pull/36), branch `feat/t3-readonly-activity`.
>
> **Scope:** improve the **existing** read-only Agent Mind Map for real T3 Code activity. Do not create a replacement repository, rewrite the backend unnecessarily, merge PR #36 without explicit permission, or expand into a general-purpose workflow editor.

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

**Current decision:** no implementation prompt has been issued. This file documents research and a recommended direction only.
