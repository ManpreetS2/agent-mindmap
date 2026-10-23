import { Handle, Position, type NodeProps } from "@xyflow/react";
import { AgentNodeCard, type AgentNodeData } from "./AgentNodeCard";

export function AgentFlowNode({ data }: NodeProps) {
  const cardData = data as unknown as AgentNodeData;
  const session = Boolean(cardData.node.session);
  return (
    <div className={`agent-flow-node${session ? " agent-flow-node--session" : ""}`}>
      <Handle type="target" position={Position.Left} className="agent-handle" />
      {!session && (
        <div
          className="agent-node-drag-handle"
          title="Drag to reposition"
          aria-hidden="true"
        >
          ⋮⋮
        </div>
      )}
      <AgentNodeCard data={cardData} />
      <Handle type="source" position={Position.Right} className="agent-handle" />
    </div>
  );
}
