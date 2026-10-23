import { motion, useReducedMotion } from "motion/react";
import type { Node as ActivityNode } from "@shared/types";
import { formatRelativeAgo } from "../utils/format";
import { StatusPill } from "./StatusPill";

export interface AgentNodeData {
  node: ActivityNode;
  selected: boolean;
  deemphasized: boolean;
  lifecycleDimmed: boolean;
  lifecycleHighlighted: boolean;
  statusPulse?: boolean;
  reduceMotion?: boolean;
  onOpenDetail: (id: string) => void;
}

interface AgentNodeCardProps {
  data: AgentNodeData;
}

export function AgentNodeCard({ data }: AgentNodeCardProps) {
  const {
    node,
    selected,
    deemphasized,
    lifecycleDimmed,
    lifecycleHighlighted,
    statusPulse,
    onOpenDetail,
  } = data;
  const reduceMotion = useReducedMotion() ?? data.reduceMotion ?? false;
  const taskLine = node.current_task
    ? `${node.current_task}`
    : "No current task";

  const lastLine = node.last_activity_ts
    ? `Last activity ${formatRelativeAgo(node.last_activity_ts)}`
    : "No recent activity";

  return (
    <motion.button
      type="button"
      data-testid={`agent-node-${node.id}`}
      className={`agent-node-card nopan nodrag${node.session ? " agent-node-card--session" : ""}${selected ? " is-selected" : ""}${deemphasized ? " is-deemphasized" : ""}${lifecycleDimmed ? " is-lifecycle-dimmed" : ""}${lifecycleHighlighted ? " is-lifecycle-highlight" : ""}${statusPulse && !reduceMotion ? " is-status-pulse" : ""}`}
      onClick={() => onOpenDetail(node.id)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpenDetail(node.id);
        }
      }}
      aria-pressed={selected}
      aria-label={`${node.label}, ${node.status}, ${taskLine}`}
      layout={!reduceMotion}
      animate={
        reduceMotion
          ? undefined
          : statusPulse
            ? {
                boxShadow: [
                  "0 0 0 0 hsl(var(--neon-cyan) / 0)",
                  "0 0 0 8px hsl(var(--neon-cyan) / 0.35)",
                  "0 0 0 0 hsl(var(--neon-cyan) / 0)",
                ],
                scale: [1, 1.04, 1],
              }
            : lifecycleHighlighted
              ? {
                  boxShadow:
                    "0 0 0 2px hsl(var(--neon-cyan) / 0.75), 0 0 18px hsl(var(--neon-violet) / 0.45)",
                }
              : { boxShadow: "0 0 0 0 transparent", scale: 1 }
      }
      transition={
        reduceMotion
          ? { duration: 0 }
          : { type: "spring", stiffness: 320, damping: 22 }
      }
    >
      <div className="agent-node-card__header">
        <span className="agent-node-card__title">{node.label}</span>
        <StatusPill status={node.status} />
      </div>
      {node.session && <div className="agent-node-card__meta">
        {node.session.provider ?? "Unknown provider"} · {node.session.model ?? "Unknown model"}
      </div>}
      <div className="agent-node-card__task mono">{taskLine}</div>
      <div className="agent-node-card__meta" title={node.last_activity_ts}>{lastLine}</div>
    </motion.button>
  );
}

