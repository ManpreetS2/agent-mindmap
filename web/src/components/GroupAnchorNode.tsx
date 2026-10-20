import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";

export type GroupAnchorData = {
  label: string;
  groupId: string;
};

function GroupAnchorNodeInner({ data }: NodeProps) {
  const d = data as GroupAnchorData;
  return (
    <div
      className="group-anchor-node"
      data-testid={`group-anchor-${d.groupId}`}
      aria-label={`Group ${d.label}`}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="group-anchor-handle"
        isConnectable={false}
      />
      <Handle
        type="target"
        position={Position.Top}
        id="top"
        className="group-anchor-handle"
        isConnectable={false}
      />
      <Handle
        type="source"
        position={Position.Right}
        className="group-anchor-handle"
        isConnectable={false}
      />
      <span className="group-anchor-node__label">{d.label}</span>
    </div>
  );
}

export const GroupAnchorNode = memo(GroupAnchorNodeInner);
