import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Position,
  Background,
  Controls,
  MarkerType,
  MiniMap,
  Panel,
  ReactFlow,
  ViewportPortal,
  useEdgesState,
  useNodesState,
  type Edge as FlowEdge,
  type Node as FlowNode,
  type NodeChange,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { motion, useReducedMotion } from "motion/react";

import type { Activity } from "@shared/types";
import { EDGE_VISUALS, strokeWidthForCount } from "../utils/edgeStyles";
import {
  applyLayoutPositions,
  layoutNodesWithDagre,
} from "../utils/graphLayout";
import { buildGroupFrames } from "../utils/groupFrames";
import {
  NETWORK_NODE_HEIGHT,
  NETWORK_NODE_WIDTH,
  networkLayoutFor,
  publishLivePositions,
} from "../utils/networkLayout";
import { ForceNetwork } from "../utils/forceNetwork";
import { useFreshEdges } from "../hooks/useFreshEdges";
import { AgentFlowNode } from "./AgentFlowNode";
import { GroupFrameLayer } from "./GroupFrameLayer";
import { HandoffEdge } from "./HandoffEdge";

const nodeTypes = { agent: AgentFlowNode };
const edgeTypes = { handoffEdge: HandoffEdge };

const RECENT_HANDOFF_MS = 36 * 60 * 60 * 1000;

export interface AgentGraphProps {
  activity: Activity;
  selectedNodeId: string | null;
  onOpenNodeDetail: (id: string) => void;
  onClearNodeDetail: () => void;
  lifecycleNodeIds: ReadonlySet<string> | null;
  lifecycleEdgeIds: ReadonlySet<string> | null;
  statusPulseNodeIds?: ReadonlySet<string>;
  nowMs?: number;
}

function isDeemphasized(node: Activity["nodes"][number]): boolean {
  return node.group === "radar" && node.status === "IDLE";
}

function isRecentHandoff(
  edge: Activity["edges"][number],
  events: Activity["events"],
  nowMs: number,
): boolean {
  if (edge.type !== "handoff") return false;
  const byId = new Map(events.map((e) => [e.id, e]));
  return edge.event_ids.some((id) => {
    const ev = byId.get(id);
    if (!ev) return false;
    const t = new Date(ev.source_time).getTime();
    return !Number.isNaN(t) && nowMs - t <= RECENT_HANDOFF_MS;
  });
}

export function AgentGraph({
  activity,
  selectedNodeId,
  onOpenNodeDetail,
  onClearNodeDetail,
  lifecycleNodeIds,
  lifecycleEdgeIds,
  statusPulseNodeIds,
  nowMs = Date.now(),
}: AgentGraphProps) {
  const reduceMotion = useReducedMotion() ?? false;
  const lifecycleActive = lifecycleNodeIds !== null;

  const isT3 = Boolean(activity.meta.t3);
  const freshEdgeIds = useFreshEdges(activity);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  // Legacy (ledger) graph: user-dragged positions survive until "Re-layout".
  const pinned = useRef(new Map<string, { x: number; y: number }>());
  const [pinCount, setPinCount] = useState(0);

  // T3 network: d3-force owns coordinates; React Flow renders them.
  const engineRef = useRef<ForceNetwork | null>(null);
  if (isT3 && !engineRef.current) engineRef.current = new ForceNetwork();
  const engine = engineRef.current;
  const [userPaused, setUserPaused] = useState(false);
  const motionPaused = userPaused || reduceMotion;
  const [enginePinned, setEnginePinned] = useState(0);

  const enginePositions = useMemo(() => {
    if (!isT3 || !engine) return null;
    engine.setPaused(motionPaused);
    engine.update(
      activity.nodes.map((n) => ({
        id: n.id,
        active: (n.status === "IN_PROGRESS" || n.status === "IN_REVIEW") && !n.session?.stale,
      })),
      activity.edges,
      networkLayoutFor(activity.nodes, activity.edges),
    );
    return engine.positions();
  }, [isT3, engine, activity.nodes, activity.edges, motionPaused]);

  useEffect(() => () => engineRef.current?.destroy(), []);

  const laidOutNodes = useMemo(() => {
    if (isT3) {
      return applyLayoutPositions(activity.nodes, enginePositions ?? new Map());
    }
    const positions = layoutNodesWithDagre(activity.nodes, activity.edges);
    return applyLayoutPositions(activity.nodes, positions);
  }, [activity.nodes, activity.edges, isT3, enginePositions]);

  const frames = useMemo(
    () => buildGroupFrames(laidOutNodes),
    [laidOutNodes],
  );

  const focusId = hoveredId ?? selectedNodeId;
  const neighborIds = useMemo(() => {
    const out = new Set<string>();
    if (!focusId) return out;
    for (const e of activity.edges) {
      if (e.source === focusId) out.add(e.target);
      if (e.target === focusId) out.add(e.source);
    }
    return out;
  }, [activity.edges, focusId]);

  const builtNodes: FlowNode[] = useMemo(
    () =>
      laidOutNodes.map((n) => ({
        id: n.id,
        type: "agent",
        position: (!isT3 && pinned.current.get(n.id)) || { x: n.layout.x, y: n.layout.y },
        draggable: true,
        dragHandle: n.session ? undefined : ".agent-node-drag-handle",
        selectable: true,
        focusable: true,
        selected: selectedNodeId === n.id,
        // Session cards have a fixed size and floating edges, so declare handles up front:
        // edges then never depend on React Flow's handle measurement surviving a controlled update.
        ...(n.session
          ? {
              initialWidth: NETWORK_NODE_WIDTH,
              initialHeight: NETWORK_NODE_HEIGHT,
              handles: [
                { type: "target" as const, position: Position.Left, x: 0, y: NETWORK_NODE_HEIGHT / 2, width: 1, height: 1 },
                { type: "source" as const, position: Position.Right, x: NETWORK_NODE_WIDTH, y: NETWORK_NODE_HEIGHT / 2, width: 1, height: 1 },
              ],
            }
          : {}),
        data: {
          node: n,
          selected: selectedNodeId === n.id,
          deemphasized: isDeemphasized(n),
          lifecycleDimmed: lifecycleActive && !lifecycleNodeIds!.has(n.id),
          lifecycleHighlighted:
            lifecycleActive && lifecycleNodeIds!.has(n.id),
          statusPulse: Boolean(statusPulseNodeIds?.has(n.id)),
          reduceMotion,
          relation: !focusId
            ? null
            : n.id === focusId
              ? "focus"
              : neighborIds.has(n.id)
                ? "neighbor"
                : "dim",
          onOpenDetail: (id: string) => onOpenNodeDetail(id),
        },
      })),
    [
      isT3,
      laidOutNodes,
      selectedNodeId,
      onOpenNodeDetail,
      lifecycleActive,
      lifecycleNodeIds,
      statusPulseNodeIds,
      reduceMotion,
      focusId,
      neighborIds,
    ],
  );

  const builtEdges: FlowEdge[] = useMemo(
    () =>
      activity.edges.map((e) => {
        const visual = EDGE_VISUALS[e.type];
        const dimmed = lifecycleActive && !lifecycleEdgeIds!.has(e.id);
        const lifecycleHi = lifecycleActive && lifecycleEdgeIds!.has(e.id);
        const incident = focusId !== null && (e.source === focusId || e.target === focusId);
        const focusDim = focusId !== null && !incident;
        const highlighted = lifecycleHi || incident;
        const fresh = freshEdgeIds.has(e.id);
        const nameOf = (id: string) =>
          activity.nodes.find((n) => n.id === id)?.label ?? id;
        const kind =
          activity.meta.t3?.replay && e.type === "delegation"
            ? "Simulated delegation"
            : visual.label;
        const tooltip = `${kind}: ${e.source} → ${e.target} (${e.count})`;
        const recent = isRecentHandoff(e, activity.events, nowMs);
        return {
          id: e.id,
          source: e.source,
          target: e.target,
          type: "handoffEdge",
          ariaLabel: `${kind}: ${nameOf(e.source)} to ${nameOf(e.target)}`,
          data: {
            labelText: isT3 ? "delegated" : String(e.count),
            tooltip,
            showParticles: recent && !reduceMotion,
            reduceMotion,
            glow: highlighted && !reduceMotion && !isT3,
            curved: isT3,
            fresh,
            showLabel: isT3 ? incident || fresh : true,
          },
          animated: recent && !reduceMotion,
          style: {
            stroke: visual.stroke,
            strokeWidth:
              (isT3 ? 2 : strokeWidthForCount(e.count)) + (highlighted ? 1.5 : 0),
            strokeDasharray: visual.strokeDasharray,
            opacity: dimmed || focusDim ? 0.18 : 1,
          },
          markerEnd: {
            type: MarkerType.ArrowClosed,
            color: visual.stroke,
            width: 18,
            height: 18,
          },
        };
      }),
    [
      activity.edges,
      activity.events,
      activity.nodes,
      activity.meta.t3?.replay,
      isT3,
      lifecycleActive,
      lifecycleEdgeIds,
      nowMs,
      reduceMotion,
      focusId,
      freshEdgeIds,
    ],
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(builtNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(builtEdges);

  useEffect(() => {
    // Drop pins for sessions that no longer exist, then merge: keep React Flow's measured
    // size / drag state from the previous node so polling never remeasures or flickers.
    if (!isT3) {
      const live = new Set(builtNodes.map((n) => n.id));
      for (const id of [...pinned.current.keys()]) {
        if (!live.has(id)) pinned.current.delete(id);
      }
      setPinCount(pinned.current.size);
    }
    const live = engine?.positions();
    setNodes((prev) => {
      const before = new Map(prev.map((n) => [n.id, n]));
      return builtNodes.map((next) => {
        const old = before.get(next.id);
        if (old?.dragging) return { ...old, ...next, position: old.position };
        // Physics owns T3 coordinates: never let a stale memoised position win.
        const merged = old ? { ...old, ...next } : next;
        const p = live?.get(next.id);
        return p ? { ...merged, position: p } : merged;
      });
    });
  }, [builtNodes, setNodes, isT3, engine]);

  // Physics ticks move only positions; node data keeps identity so cards do not re-render.
  useEffect(() => {
    if (!engine) return;
    return engine.onChange(() => {
      const pos = engine.positions();
      publishLivePositions(pos);
      setEnginePinned(engine.pinned.size);
      setNodes((prev) =>
        prev.map((n) => {
          const p = pos.get(n.id);
          return p && !n.dragging ? { ...n, position: p } : n;
        }),
      );
    });
  }, [engine, setNodes]);

  useEffect(() => {
    if (!enginePositions) return;
    publishLivePositions(enginePositions);
    return () => publishLivePositions(null);
  }, [enginePositions]);

  useEffect(() => {
    setEdges(builtEdges);
  }, [builtEdges, setEdges]);

  const handleNodesChange = useCallback(
    (changes: NodeChange[]) => {
      let pinnedNow = false;
      for (const c of changes) {
        if (c.type !== "position") continue;
        if (engine) {
          const at = c.position ?? engine.positions().get(c.id);
          if (at) engine.drag(c.id, at, c.dragging === true);
        } else if (c.position) {
          pinned.current.set(c.id, c.position);
          pinnedNow = true;
        }
      }
      if (pinnedNow) setPinCount(pinned.current.size);
      onNodesChange(changes);
    },
    [onNodesChange, engine],
  );

  const relayout = useCallback(() => {
    if (engine) {
      engine.unpinAll();
      setEnginePinned(0);
      return;
    }
    pinned.current.clear();
    setPinCount(0);
    setNodes((prev) =>
      prev.map((n) => {
        const laid = laidOutNodes.find((l) => l.id === n.id);
        return laid ? { ...n, position: { x: laid.layout.x, y: laid.layout.y } } : n;
      }),
    );
  }, [engine, laidOutNodes, setNodes]);

  const onPaneClick = useCallback(() => {
    onClearNodeDetail();
  }, [onClearNodeDetail]);

  return (
    <motion.div
      className="agent-graph"
      layout={!reduceMotion}
      transition={
        reduceMotion
          ? { duration: 0 }
          : { type: "spring", stiffness: 280, damping: 28 }
      }
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodesChange={handleNodesChange}
        onEdgesChange={onEdgesChange}
        onPaneClick={onPaneClick}
        onNodeMouseEnter={(_, node) => setHoveredId(node.id)}
        onNodeMouseLeave={() => setHoveredId(null)}
        nodesDraggable={true}
        nodesConnectable={false}
        elementsSelectable={true}
        fitView
        fitViewOptions={{ padding: 0.15, maxZoom: 1 }}
        minZoom={0.25}
        maxZoom={1.5}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="var(--border-subtle)" gap={16} />
        <Controls showInteractive={false} />
        <MiniMap
          pannable
          zoomable
          nodeStrokeWidth={2}
          className="agent-minimap"
          maskColor="rgba(8, 12, 20, 0.65)"
          nodeColor={() => "hsl(var(--neon-cyan) / 0.55)"}
        />
        <Panel position="top-left" className="graph-controls">
          {isT3 && (
            <button
              type="button"
              className="relayout-btn"
              aria-pressed={userPaused}
              disabled={reduceMotion}
              title={reduceMotion ? "Motion is off (reduced-motion preference)" : undefined}
              onClick={() => setUserPaused((p) => !p)}
            >
              {motionPaused ? "Resume motion" : "Pause motion"}
            </button>
          )}
          {(isT3 ? enginePinned : pinCount) > 0 && (
            <button type="button" className="relayout-btn" onClick={relayout}>
              {isT3 ? `Release ${enginePinned} pinned` : `Re-layout (${pinCount} pinned)`}
            </button>
          )}
        </Panel>
        <ViewportPortal>
          <GroupFrameLayer frames={frames} />
        </ViewportPortal>
      </ReactFlow>
    </motion.div>
  );
}

