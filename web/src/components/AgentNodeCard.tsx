import { motion, useReducedMotion } from "motion/react";
import type { Node as ActivityNode } from "@shared/types";
import { formatRelativeAgo } from "../utils/format";
import { StatusPill } from "./StatusPill";
import { providerKey, providerLabel } from "../utils/provider";

export interface AgentNodeData {
  node: ActivityNode;
  selected: boolean;
  deemphasized: boolean;
  lifecycleDimmed: boolean;
  lifecycleHighlighted: boolean;
  statusPulse?: boolean;
  reduceMotion?: boolean;
  /** Relationship to the hovered/selected node; null when nothing is focused. */
  relation?: "focus" | "neighbor" | "dim" | null;
  onOpenDetail: (id: string) => void;
}

interface AgentNodeCardProps {
  data: AgentNodeData;
}

function SessionNodeCard({ data }: AgentNodeCardProps) {
  const { node, selected, statusPulse, relation, onOpenDetail } = data;
  const session = node.session!;
  const reduceMotion = useReducedMotion() ?? data.reduceMotion ?? false;
  const key = providerKey(session.provider);
  const task = node.current_task ?? "No task reported";
  const model = session.model ?? "Model not reported";
  const cls = [
    "session-node nopan",
    `session-node--${key}`,
    `session-node--${node.status.toLowerCase().replace("_", "-")}`,
    selected ? "is-selected" : "",
    relation ? `is-${relation}` : "",
    statusPulse && !reduceMotion ? "is-status-pulse" : "",
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <button
      type="button"
      data-testid={`agent-node-${node.id}`}
      className={cls}
      onClick={() => onOpenDetail(node.id)}
      aria-pressed={selected}
      aria-label={`${providerLabel(session.provider)}, ${model}, ${node.status}, ${task}`}
    >
      <span className="session-node__row">
        <span className="session-node__provider">
          <span className="session-node__dot" aria-hidden="true" />
          {providerLabel(session.provider)}
        </span>
        <StatusPill status={node.status} />
      </span>
      <span className="session-node__model mono" title={model}>
        {model}
      </span>
      <span className="session-node__task" title={task}>
        {task}
      </span>
      <span className="session-node__meta" title={node.last_activity_ts}>
        {node.last_activity_ts
          ? `Updated ${formatRelativeAgo(node.last_activity_ts)}`
          : "No update time reported"}
      </span>
    </button>
  );
}

export function AgentNodeCard({ data }: AgentNodeCardProps) {
  if (data.node.session) return <SessionNodeCard data={data} />;
  return <LegacyNodeCard data={data} />;
}

function LegacyNodeCard({ data }: AgentNodeCardProps) {
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
          : statusPulse
            ? { type: "tween", duration: 0.7, ease: "easeOut" }
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

