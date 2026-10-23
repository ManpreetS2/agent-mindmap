import type { ReactNode } from "react";
import type { Activity, Node } from "@shared/types";
import {
  attributionLabel,
  formatSourceTime,
  sourceKindFromUrl,
} from "../utils/format";
import {
  resolveCurrentTaskSource,
  resolveLastActivity,
  resolveStatusSource,
  taskForNode,
} from "../utils/detailPanelFacts";
import { tasksOwnedByLabel } from "../utils/nodeFacts";
import { isHttpSourceUrl } from "../utils/sourceUrl";
import { FactSourceLink } from "./FactSourceLink";
import { StatusPill } from "./StatusPill";
import { UnsourcedTag } from "./UnsourcedTag";

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
  const ownedTasks = tasksOwnedByLabel(node.label, activity.tasks);
  const statusSource = resolveStatusSource(node, activity.tasks, activity.events);
  const taskSource = resolveCurrentTaskSource(
    node,
    activity.tasks,
    activity.events,
  );
  const lastActivity = resolveLastActivity(node, activity.events);

  if (node.session) return (
    <aside className="detail-panel" aria-label={`Details for ${node.label}`}>
      <div className="detail-panel__header"><h2>{node.label}</h2>
        <button type="button" className="detail-panel__close" onClick={onClose} aria-label="Close detail panel">×</button>
      </div>
      <FactRow label="Status"><StatusPill status={node.status} />
        <div>Last reported: {node.session.reported_status}</div>
      </FactRow>
      <FactRow label="Provider / model">{node.session.provider ?? "Unknown provider"} / {node.session.model ?? "Unknown model"}</FactRow>
      <FactRow label="Current task">{node.current_task ?? "Unknown task"}</FactRow>
      <FactRow label="Project">{node.session.project}</FactRow>
      <FactRow label="Branch">{node.session.branch ?? "Not reported"}</FactRow>
      <FactRow label={activity.meta.t3?.replay ? "Simulated activity time" : "Last verified T3 activity"}>{node.last_activity_ts ? formatSourceTime(node.last_activity_ts) : "Not reported"}</FactRow>
      <FactRow label="Source">{node.session.source}<div className="mono">Thread: {node.session.thread_id}</div></FactRow>
      <FactRow label="Source links">{node.session.source_links.length ? node.session.source_links.filter(isHttpSourceUrl).map(url => (
        <div key={url}><a href={url} target="_blank" rel="noopener noreferrer">{url}</a></div>
      )) : "No external links reported"}</FactRow>
      <p className="detail-muted">{activity.meta.t3?.replay ? "Synthetic replay metadata. These are simulated agents, models, tasks and delegation." : "Read-only metadata. Conversation text and tool output are not published."}</p>
    </aside>
  );

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
        <div className="detail-status-row">
          <StatusPill status={node.status} />
          {statusSource.kind === "linked" ? (
            <a href={statusSource.href} className="detail-source-link">
              source
            </a>
          ) : (
            <UnsourcedTag />
          )}
        </div>
      </FactRow>

      <FactRow label="Current task">
        {!node.current_task ? (
          <span className="detail-muted">None assigned</span>
        ) : task ? (
          <>
            {isHttpSourceUrl(task.source_url) ? (
              <a href={task.source_url} className="mono">
                {task.id}
              </a>
            ) : (
              <span className="mono">
                {task.id} <UnsourcedTag />
              </span>
            )}
            <div>{task.title}</div>
            <div className="detail-meta">
              from ledger table · status: {task.status_raw}
            </div>
            <div className="detail-attribution">
              attribution: {attributionLabel("ledger_owner")}
            </div>
          </>
        ) : taskSource ? (
          <>
            <FactSourceLink source={taskSource} className="mono">
              {node.current_task}
            </FactSourceLink>
            <div className="detail-meta">
              from event (task not in ledger table)
            </div>
          </>
        ) : (
          <span className="mono">{node.current_task}</span>
        )}
      </FactRow>

      <FactRow label="Last activity">
        {lastActivity.mode === "event" ? (
          <>
            {isHttpSourceUrl(lastActivity.event.source_url) ? (
              <a href={lastActivity.event.source_url}>
                {lastActivity.event.type.replace("_", " ")}
                {lastActivity.event.task_id
                  ? ` · ${lastActivity.event.task_id}`
                  : ""}
              </a>
            ) : (
              <span>
                {lastActivity.event.type.replace("_", " ")}
                {lastActivity.event.task_id
                  ? ` · ${lastActivity.event.task_id}`
                  : ""}{" "}
                <UnsourcedTag />
              </span>
            )}
            <div className="detail-meta">
              from {sourceKindFromUrl(lastActivity.event.source_url)},{" "}
              {formatSourceTime(lastActivity.event.source_time)}
            </div>
            <div className="detail-attribution">
              attribution:{" "}
              {attributionLabel(lastActivity.event.attribution.method)}
            </div>
            <p className="detail-raw">{lastActivity.event.raw}</p>
          </>
        ) : lastActivity.mode === "timestamp" ? (
          <>
            <FactSourceLink source={lastActivity.source}>
              node snapshot · {formatSourceTime(lastActivity.ts)}
            </FactSourceLink>
          </>
        ) : (
          <span className="detail-muted">
            No events yet <UnsourcedTag />
          </span>
        )}
      </FactRow>

      {ownedTasks.length > 0 && (
        <FactRow label="Tasks owned">
          <ul className="detail-list">
            {ownedTasks.map((t) => (
              <li key={t.id}>
                {isHttpSourceUrl(t.source_url) ? (
                  <a href={t.source_url} className="mono">{t.id}</a>
                ) : (
                  <span className="mono">
                    {t.id} <UnsourcedTag />
                  </span>
                )}
                {t.prs.length > 0 && (
                  <span className="detail-meta">
                    {" "}
                    · PR{t.prs.length > 1 ? "s" : ""} #{t.prs.join(", #")}
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

