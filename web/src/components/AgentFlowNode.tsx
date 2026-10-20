import { Handle, Position, type NodeProps } from "@xyflow/react";
import { AgentNodeCard, type AgentNodeData } from "./AgentNodeCard";

export function AgentFlowNode({ data }: NodeProps) {
  const cardData = data as unknown as AgentNodeData;
  return (
    <div className="agent-flow-node">
      <Handle type="target" position={Position.Left} className="agent-handle" />
      <AgentNodeCard data={cardData} />
      <Handle type="source" position={Position.Right} className="agent-handle" />
    </div>
  );
}
