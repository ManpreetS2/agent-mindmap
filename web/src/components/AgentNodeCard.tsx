import type { Node as ActivityNode } from "@shared/types";
import { formatRelativeAgo } from "../utils/format";
import { StatusPill } from "./StatusPill";

export interface AgentNodeData {
  node: ActivityNode;
  selected: boolean;
  deemphasized: boolean;
  onSelect: (id: string) => void;
}

interface AgentNodeCardProps {
  data: AgentNodeData;
}

export function AgentNodeCard({ data }: AgentNodeCardProps) {
  const { node, selected, deemphasized, onSelect } = data;
  const taskLine = node.current_task
    ? `${node.current_task}`
    : "No current task";

  const lastLine = node.last_activity_ts
    ? `Last activity ${formatRelativeAgo(node.last_activity_ts)}`
    : "No recent activity";

  return (
    <button
      type="button"
      data-testid={`agent-node-${node.id}`}
      className={`agent-node-card nopan nodrag${selected ? " is-selected" : ""}${deemphasized ? " is-deemphasized" : ""}`}
      onClick={() => onSelect(node.id)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect(node.id);
        }
      }}
      aria-pressed={selected}
      aria-label={`${node.label}, ${node.status}, ${taskLine}`}
    >
      <div className="agent-node-card__header">
        <span className="agent-node-card__title">{node.label}</span>
        <StatusPill status={node.status} />
      </div>
      <div className="agent-node-card__task mono">{taskLine}</div>
      <div className="agent-node-card__meta">{lastLine}</div>
    </button>
  );
}
