import type { ReactNode } from "react";
import type { Activity, Node } from "@shared/types";
import {
  attributionLabel,
  formatSourceTime,
  sourceKindFromUrl,
} from "../utils/format";
import {
  lastEventForNode,
  taskForNode,
  tasksOwnedByLabel,
} from "../utils/nodeFacts";
import { StatusPill } from "./StatusPill";

interface DetailPanelProps {
  node: Node;
  activity: Activity;
  onClose: () => void;
}

function FactRow({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="detail-fact">
      <div className="detail-fact__label">{label}</div>
      <div className="detail-fact__value">{children}</div>
    </div>
  );
}

function AgentLinkChip({ id }: { id: string }) {
  const href = `https://cursor.com/agents/${id}`;
  return (
    <a
      href={href}
      className="agent-chip mono"
      target="_blank"
      rel="noopener noreferrer"
      title="May not open (short id)"
    >
      {id}
      <span className="agent-chip__icon" aria-hidden="true">↗</span>
      <span className="sr-only"> (external link, may not open)</span>
    </a>
  );
}

export function DetailPanel({ node, activity, onClose }: DetailPanelProps) {
  const task = taskForNode(node, activity.tasks);
  const lastEvent = lastEventForNode(node.id, activity.events);
  const ownedTasks = tasksOwnedByLabel(node.label, activity.tasks);

  return (
    <aside className="detail-panel" aria-label={`Details for ${node.label}`}>
      <div className="detail-panel__header">
        <h2>{node.label}</h2>
        <button
          type="button"
          className="detail-panel__close"
          onClick={onClose}
          aria-label="Close detail panel"
        >
          ×
        </button>
      </div>

      <FactRow label="Status">
        <StatusPill status={node.status} />
      </FactRow>

      <FactRow label="Current task">
        {task ? (
          <>
            <a href={task.source_url} className="mono">
              {task.id}
            </a>
            <div>{task.title}</div>
            <div className="detail-meta">
              from ledger table · status: {task.status_raw}
            </div>
            <div className="detail-attribution">
              attribution: {attributionLabel("ledger_owner")}
            </div>
          </>
        ) : node.current_task ? (
          <span className="mono">{node.current_task}</span>
        ) : (
          <span className="detail-muted">None assigned</span>
        )}
      </FactRow>

      <FactRow label="Last activity">
        {lastEvent ? (
          <>
            <a href={lastEvent.source_url}>
              {lastEvent.type.replace("_", " ")}
              {lastEvent.task_id ? ` · ${lastEvent.task_id}` : ""}
            </a>
            <div className="detail-meta">
              from {sourceKindFromUrl(lastEvent.source_url)},{" "}
              {formatSourceTime(lastEvent.source_time)}
            </div>
            <div className="detail-attribution">
              attribution: {attributionLabel(lastEvent.attribution.method)}
            </div>
            <p className="detail-raw">{lastEvent.raw}</p>
          </>
        ) : node.last_activity_ts ? (
          <div className="detail-meta">
            node snapshot · {formatSourceTime(node.last_activity_ts)}
          </div>
        ) : (
          <span className="detail-muted">No events yet</span>
        )}
      </FactRow>

      {ownedTasks.length > 0 && (
        <FactRow label="Tasks owned">
          <ul className="detail-list">
            {ownedTasks.map((t) => (
              <li key={t.id}>
                <a href={t.source_url} className="mono">{t.id}</a>
                {t.prs.length > 0 && (
                  <span className="detail-meta">
                    {" "}
                    · PR{ t.prs.length > 1 ? "s" : "" } #{t.prs.join(", #")}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </FactRow>
      )}

      {node.agent_links.length > 0 && (
        <FactRow label="Cloud agents">
          <div className="agent-chips">
            {node.agent_links.map((link) => (
              <AgentLinkChip key={link} id={link} />
            ))}
          </div>
        </FactRow>
      )}
    </aside>
  );
}
