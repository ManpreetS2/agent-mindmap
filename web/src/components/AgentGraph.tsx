import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ViewportPortal,
  useEdgesState,
  useNodesState,
  type Node as FlowNode,
  type NodeChange,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { motion, useReducedMotion } from "motion/react";

import type { Activity } from "@shared/types";
import { buildGraphEdges } from "../utils/buildGraphEdges";
import {
  applyLayoutPositions,
  layoutMultiGroupClusters,
  layoutNodesWithDagre,
} from "../utils/graphLayout";
import {
  buildGroupFrames,
  buildGroupFramesFromClusters,
} from "../utils/groupFrames";
import {
  collectGroupIds,
  groupTargetId,
  labelForGroup,
  nodeInSelectedGroups,
} from "../utils/groupMembership";
import {
  collectDraggedIds,
  mergeFlowNodes,
} from "../utils/mergeFlowNodes";
import { AgentFlowNode } from "./AgentFlowNode";
import { GroupAnchorNode } from "./GroupAnchorNode";
import { GroupFilter } from "./GroupFilter";
import { GroupFrameLayer } from "./GroupFrameLayer";
import { HandoffEdge } from "./HandoffEdge";
import { MembershipEdge } from "./MembershipEdge";
import { MessageEdge } from "./MessageEdge";

const nodeTypes = {
  agent: AgentFlowNode,
  groupAnchor: GroupAnchorNode,
};
const edgeTypes = {
  handoffEdge: HandoffEdge,
  messageEdge: MessageEdge,
  membershipEdge: MembershipEdge,
};

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
  return node.group === "historical";
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

  const allGroupIds = useMemo(
    () => collectGroupIds(activity.nodes),
    [activity.nodes],
  );
  const [selectedGroups, setSelectedGroups] = useState<Set<string>>(
    () => new Set(allGroupIds),
  );

  useEffect(() => {
    setSelectedGroups((prev) => {
      const next = new Set<string>();
      for (const g of allGroupIds) {
        if (prev.size === 0 || prev.has(g)) next.add(g);
      }
      return next.size > 0 ? next : new Set(allGroupIds);
    });
  }, [allGroupIds]);

  const useClusters = useMemo(
    () => activity.nodes.some((n) => (n.groups?.length ?? 0) > 0),
    [activity.nodes],
  );

  const clusterLayout = useMemo(() => {
    if (!useClusters) return null;
    return layoutMultiGroupClusters(activity.nodes, activity.edges);
  }, [activity.nodes, activity.edges, useClusters]);

  const laidOutNodes = useMemo(() => {
    if (clusterLayout) {
      return applyLayoutPositions(activity.nodes, clusterLayout.positions);
    }
    const positions = layoutNodesWithDagre(activity.nodes, activity.edges);
    return applyLayoutPositions(activity.nodes, positions);
  }, [activity.nodes, activity.edges, clusterLayout]);

  const frames = useMemo(() => {
    if (clusterLayout) {
      return buildGroupFramesFromClusters(clusterLayout.clusters, selectedGroups);
    }
    return buildGroupFrames(laidOutNodes);
  }, [clusterLayout, laidOutNodes, selectedGroups]);

  const visibleAgents = useMemo(
    () =>
      laidOutNodes.filter((n) => nodeInSelectedGroups(n, selectedGroups)),
    [laidOutNodes, selectedGroups],
  );
  const visibleAgentIds = useMemo(
    () => new Set(visibleAgents.map((n) => n.id)),
    [visibleAgents],
  );

  const builtNodes: FlowNode[] = useMemo(() => {
    const agents: FlowNode[] = visibleAgents.map((n) => ({
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
        lifecycleHighlighted: lifecycleActive && lifecycleNodeIds!.has(n.id),
        statusPulse: Boolean(statusPulseNodeIds?.has(n.id)),
        reduceMotion,
        onOpenDetail: (id: string) => onOpenNodeDetail(id),
      },
    }));

    const anchors: FlowNode[] = [];
    if (clusterLayout) {
      for (const gid of allGroupIds) {
        if (!selectedGroups.has(gid)) continue;
        const pos = clusterLayout.groupAnchors.get(gid) ?? { x: 0, y: 0 };
        anchors.push({
          id: groupTargetId(gid),
          type: "groupAnchor",
          position: pos,
          draggable: false,
          selectable: false,
          focusable: false,
          data: { label: labelForGroup(gid), groupId: gid },
        });
      }
    }

    return [...anchors, ...agents];
  }, [
    visibleAgents,
    selectedNodeId,
    onOpenNodeDetail,
    lifecycleActive,
    lifecycleNodeIds,
    statusPulseNodeIds,
    reduceMotion,
    clusterLayout,
    allGroupIds,
    selectedGroups,
  ]);

  const builtEdges = useMemo(
    () =>
      buildGraphEdges({
        activity,
        visibleAgentIds,
        selectedGroups,
        membershipLinks: clusterLayout?.membershipLinks ?? [],
        lifecycleActive,
        lifecycleEdgeIds,
        reduceMotion,
        nowMs,
      }),
    [
      activity,
      visibleAgentIds,
      selectedGroups,
      clusterLayout,
      lifecycleActive,
      lifecycleEdgeIds,
      reduceMotion,
      nowMs,
    ],
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(builtNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(builtEdges);
  const draggedIdsRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    // Merge layout into the live node list without treating user drags as
    // layout resets (QA-MM020f-1). New / structurally changed agents re-layout.
    setNodes((prev) => mergeFlowNodes(prev, builtNodes, draggedIdsRef.current));
  }, [builtNodes, setNodes]);

  useEffect(() => {
    setEdges(builtEdges);
  }, [builtEdges, setEdges]);

  const handleNodesChange = useCallback(
    (changes: NodeChange[]) => {
      draggedIdsRef.current = collectDraggedIds(changes, draggedIdsRef.current);
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
      <GroupFilter
        groupIds={allGroupIds}
        selected={selectedGroups}
        onChange={setSelectedGroups}
      />
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
        minZoom={0.35}
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
          nodeColor={(n) =>
            n.type === "groupAnchor"
              ? "hsl(187 92% 55% / 0.25)"
              : "hsl(var(--neon-cyan) / 0.55)"
          }
        />
        <ViewportPortal>
          <GroupFrameLayer frames={frames} />
        </ViewportPortal>
      </ReactFlow>
    </motion.div>
  );
}
