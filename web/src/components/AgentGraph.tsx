import { useCallback, useEffect, useMemo } from "react";
import {
  Background,
  Controls,
  MarkerType,
  MiniMap,
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

  const laidOutNodes = useMemo(() => {
    if (activity.meta.t3) return activity.nodes;
    const positions = layoutNodesWithDagre(activity.nodes, activity.edges);
    return applyLayoutPositions(activity.nodes, positions);
  }, [activity.nodes, activity.edges, activity.meta.t3]);

  const frames = useMemo(
    () => buildGroupFrames(laidOutNodes),
    [laidOutNodes],
  );

  const builtNodes: FlowNode[] = useMemo(
    () =>
      laidOutNodes.map((n) => ({
        id: n.id,
        type: "agent",
        position: { x: n.layout.x, y: n.layout.y },
        draggable: true,
        dragHandle: ".agent-node-drag-handle",
        selectable: true,
        focusable: true,
        data: {
          node: n,
          selected: selectedNodeId === n.id,
          deemphasized: isDeemphasized(n),
          lifecycleDimmed: lifecycleActive && !lifecycleNodeIds!.has(n.id),
          lifecycleHighlighted:
            lifecycleActive && lifecycleNodeIds!.has(n.id),
          statusPulse: Boolean(statusPulseNodeIds?.has(n.id)),
          reduceMotion,
          onOpenDetail: (id: string) => onOpenNodeDetail(id),
        },
      })),
    [
      laidOutNodes,
      selectedNodeId,
      onOpenNodeDetail,
      lifecycleActive,
      lifecycleNodeIds,
      statusPulseNodeIds,
      reduceMotion,
    ],
  );

  const builtEdges: FlowEdge[] = useMemo(
    () =>
      activity.edges.map((e) => {
        const visual = EDGE_VISUALS[e.type];
        const dimmed = lifecycleActive && !lifecycleEdgeIds!.has(e.id);
        const highlighted =
          lifecycleActive && lifecycleEdgeIds!.has(e.id);
        const tooltip = `${visual.label}: ${e.source} → ${e.target} (${e.count})`;
        const recent = isRecentHandoff(e, activity.events, nowMs);
        return {
          id: e.id,
          source: e.source,
          target: e.target,
          type: "handoffEdge",
          data: {
            labelText: String(e.count),
            tooltip,
            showParticles: recent && !reduceMotion,
            reduceMotion,
            glow: highlighted && !reduceMotion,
          },
          animated: recent && !reduceMotion,
          style: {
            stroke: visual.stroke,
            strokeWidth:
              strokeWidthForCount(e.count) + (highlighted ? 1.5 : 0),
            strokeDasharray: visual.strokeDasharray,
            opacity: dimmed ? 0.2 : 1,
          },
          markerEnd: {
            type: MarkerType.ArrowClosed,
            color: visual.stroke,
          },
        };
      }),
    [
      activity.edges,
      activity.events,
      lifecycleActive,
      lifecycleEdgeIds,
      nowMs,
      reduceMotion,
    ],
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(builtNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(builtEdges);

  useEffect(() => {
    // Re-apply layout positions when activity layout changes; drag is session-local
    // until the next layout pass (poll with identical node set keeps dagre/grid coords).
    setNodes((prev) => {
      const prevPos = new Map(prev.map((n) => [n.id, n.position]));
      return builtNodes.map((next) => ({
        ...next,
        position: prevPos.get(next.id) ?? next.position,
      }));
    });
  }, [builtNodes, setNodes]);

  useEffect(() => {
    setEdges(builtEdges);
  }, [builtEdges, setEdges]);

  const handleNodesChange = useCallback(
    (changes: NodeChange[]) => {
      onNodesChange(changes);
    },
    [onNodesChange],
  );

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
        nodesDraggable={true}
        nodesConnectable={false}
        elementsSelectable={true}
        fitView
        fitViewOptions={{ padding: 0.15, maxZoom: 1 }}
        minZoom={0.45}
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
        <ViewportPortal>
          <GroupFrameLayer frames={frames} />
        </ViewportPortal>
      </ReactFlow>
    </motion.div>
  );
}

