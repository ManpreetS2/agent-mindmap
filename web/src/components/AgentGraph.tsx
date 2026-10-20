import { useCallback, useMemo } from "react";
import {
  Background,
  Controls,
  MarkerType,
  ReactFlow,
  ViewportPortal,
  type Edge as FlowEdge,
  type Node as FlowNode,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import type { Activity } from "@shared/types";
import { EDGE_VISUALS, strokeWidthForCount } from "../utils/edgeStyles";
import { buildGroupFrames } from "../utils/groupFrames";
import { AgentFlowNode } from "./AgentFlowNode";
import { GroupFrameLayer } from "./GroupFrameLayer";

const nodeTypes = { agent: AgentFlowNode };

export interface AgentGraphProps {
  activity: Activity;
  selectedNodeId: string | null;
  onSelectNode: (id: string | null) => void;
  lifecycleNodeIds: ReadonlySet<string> | null;
  lifecycleEdgeIds: ReadonlySet<string> | null;
}

function isDeemphasized(node: Activity["nodes"][number]): boolean {
  return node.group === "radar" && node.status === "IDLE";
}

export function AgentGraph({
  activity,
  selectedNodeId,
  onSelectNode,
  lifecycleNodeIds,
  lifecycleEdgeIds,
}: AgentGraphProps) {
  const lifecycleActive = lifecycleNodeIds !== null;
  const frames = useMemo(
    () => buildGroupFrames(activity.nodes),
    [activity.nodes],
  );

  const flowNodes: FlowNode[] = useMemo(
    () =>
      activity.nodes.map((n) => ({
        id: n.id,
        type: "agent",
        position: { x: n.layout.x, y: n.layout.y },
        draggable: false,
        selectable: true,
        focusable: true,
        data: {
          node: n,
          selected: selectedNodeId === n.id,
          deemphasized: isDeemphasized(n),
          lifecycleDimmed:
            lifecycleActive && !lifecycleNodeIds!.has(n.id),
          lifecycleHighlighted:
            lifecycleActive && lifecycleNodeIds!.has(n.id),
          onSelect: (id: string) => onSelectNode(id),
        },
      })),
    [activity.nodes, selectedNodeId, onSelectNode, lifecycleActive, lifecycleNodeIds],
  );

  const flowEdges: FlowEdge[] = useMemo(
    () =>
      activity.edges.map((e) => {
        const visual = EDGE_VISUALS[e.type];
        const dimmed =
          lifecycleActive && !lifecycleEdgeIds!.has(e.id);
        return {
          id: e.id,
          source: e.source,
          target: e.target,
          type: "smoothstep",
          label: String(e.count),
          animated: false,
          style: {
            stroke: visual.stroke,
            strokeWidth: strokeWidthForCount(e.count),
            strokeDasharray: visual.strokeDasharray,
            opacity: dimmed ? 0.2 : 1,
          },
          labelStyle: { fill: "var(--text-secondary)", fontSize: 11 },
          labelBgStyle: { fill: "var(--bg-card)", fillOpacity: 0.9 },
          markerEnd: {
            type: MarkerType.ArrowClosed,
            color: visual.stroke,
          },
        };
      }),
    [activity.edges, lifecycleActive, lifecycleEdgeIds],
  );

  const onPaneClick = useCallback(() => {
    onSelectNode(null);
  }, [onSelectNode]);

  return (
    <div className="agent-graph">
      <ReactFlow
        nodes={flowNodes}
        edges={flowEdges}
        nodeTypes={nodeTypes}
        onPaneClick={onPaneClick}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={true}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.4}
        maxZoom={1.5}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="var(--border-subtle)" gap={16} />
        <Controls showInteractive={false} />
        <ViewportPortal>
          <GroupFrameLayer frames={frames} />
        </ViewportPortal>
      </ReactFlow>
    </div>
  );
}
