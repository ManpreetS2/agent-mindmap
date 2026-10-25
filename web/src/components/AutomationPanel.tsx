import type { AutomationTaskState } from "@shared/automation";
import { AUTOMATION_STATES } from "@shared/automation";
import type { AutomationState } from "../hooks/useAutomation";
import { evaluateAutomation, type EvaluatedTask } from "../utils/automationEval";
import { countdownTo, formatAge } from "../utils/observabilityEval";

interface Props {
  state: AutomationState;
  nowMs: number;
}

const LABEL: Record<AutomationTaskState, string> = {
  running: "Running",
  blocked: "Blocked",
  queued: "Queued",
  failed: "Failed",
  unknown: "Unknown",
  completed: "Completed",
  skipped: "Skipped",
};
const ICON: Record<AutomationTaskState, string> = {
  running: "▶",
  blocked: "⏸",
  queued: "◌",
  failed: "✕",
  unknown: "?",
  completed: "✓",
  skipped: "–",
};

function Assignment({ task }: { task: EvaluatedTask }) {
  const a = task.assignment;
  if (!a.known && !a.account) {
    return <span className="automation-task__muted">Model and account not reported</span>;
  }
  return (
    <span>
      {a.account ?? "account not reported"} ·{" "}
      {a.model ? `${a.model}${a.effort ? ` ${a.effort}` : ""}` : "model not reported"}
    </span>
  );
}

function TaskRow({ task, nowMs }: { task: EvaluatedTask; nowMs: number }) {
  const s = task.effectiveState;
  const run = task.current_run;
  const next = task.next_attempt_after ? countdownTo(task.next_attempt_after, nowMs) : null;
  return (
    <li
      className={`automation-task automation-task--${s}`}
      data-testid="automation-task"
      data-state={s}
      data-task-id={task.id}
    >
      <div className="automation-task__head">
        <span className="automation-task__title">
          {task.issue.url ? (
            <a href={task.issue.url} target="_blank" rel="noopener noreferrer">
              #{task.issue.number}
            </a>
          ) : (
            <span>#{task.issue.number}</span>
          )}{" "}
          {task.issue.title ?? "Untitled issue"}
        </span>
        <span className={`automation-badge automation-badge--${s}`}>
          <span aria-hidden="true">{ICON[s]}</span> {LABEL[s]}
          {task.simulated ? " · simulated" : ""}
        </span>
      </div>
      <p className="automation-task__basis">
        {task.downgradeReason ? `${task.downgradeReason} ` : ""}
        {task.state_basis}
      </p>
      <p className="automation-task__meta">
        <Assignment task={task} />
        {task.attempts != null && ` · attempt${task.attempts === 1 ? "" : "s"} used: ${task.attempts}`}
        {task.state_observed_at && ` · observed ${formatAge(task.state_observed_at, nowMs)}`}
      </p>
      {run && (
        <p className="automation-task__meta">
          Run <span className="mono">{run.run_id ?? "id not reported"}</span>
          {run.started_at && `, started ${formatAge(run.started_at, nowMs)}`}
          {run.ended_at ? `, ended ${formatAge(run.ended_at, nowMs)}` : ", no end recorded"}
          {run.outcome && ` (${run.outcome})`}
        </p>
      )}
      {next && <p className="automation-task__meta">Next attempt not before: {next}</p>}
      {task.pull_request_url && (
        <p className="automation-task__meta">
          <a href={task.pull_request_url} target="_blank" rel="noopener noreferrer">
            Draft PR opened by taskbot
          </a>{" "}
          — awaiting human review; this link is bookkeeping, not model delegation.
        </p>
      )}
      {task.error_evidence && (
        <p className="automation-task__evidence" data-testid="automation-evidence">
          <strong>{task.error_evidence.severity}</strong>
          {task.error_evidence.type ? ` · ${task.error_evidence.type}` : ""}
          {task.error_evidence.time ? ` · ${formatAge(task.error_evidence.time, nowMs)}` : ""}
          {task.error_evidence.summary ? `: ${task.error_evidence.summary}` : ""}
        </p>
      )}
    </li>
  );
}

/** Taskbot job records. Not T3 sessions; states come from Agent Control's own records and say why. */
export function AutomationPanel({ state, nowMs }: Props) {
  if (state.status === "loading") return null;
  if (state.status === "absent" || state.status === "rejected") {
    return (
      <section className="automation-panel automation-panel--unavailable" aria-label="Taskbot automation" data-testid="automation-panel">
        <h3 className="automation-panel__title">Taskbot automation</h3>
        <p role="status">
          {state.status === "rejected"
            ? `Taskbot activity rejected (${state.reason}).`
            : "Taskbot activity is not connected to this server, so queued, running and failed jobs are unknown. This is not evidence that nothing is queued."}
        </p>
      </section>
    );
  }
  const doc = evaluateAutomation(state.data, nowMs);
  const demo = doc.mode === "demo";
  const src = doc.source;
  return (
    <section className="automation-panel" aria-label="Taskbot automation" data-testid="automation-panel">
      <h3 className="automation-panel__title">Taskbot automation</h3>
      {demo && (
        <p className="automation-panel__demo" role="status">
          <strong>DEMO — SYNTHETIC TASKS</strong> Example jobs only: none of this is real taskbot activity.
        </p>
      )}
      {!demo && doc.documentStale && (
        <p className="automation-panel__stale" role="status">
          <strong>Stale</strong> — this document was generated {formatAge(doc.generated_at, nowMs)}. Running jobs are shown as unknown.
        </p>
      )}
      {src.status !== "connected" ? (
        <p className="automation-panel__source" role="status" data-testid="automation-source">
          Taskbot source <strong>{src.status.replace("_", " ")}</strong>
          {src.reason ? `: ${src.reason}` : ""}. Job state is unknown.
        </p>
      ) : (
        <p className="automation-panel__source" data-testid="automation-source">
          Last taskbot event {formatAge(src.last_event_at, nowMs)}. An old event does not show that the scheduler is healthy or idle.
        </p>
      )}
      <ul className="automation-panel__counts" aria-label="Task counts">
        {AUTOMATION_STATES.filter((s) => doc.counts[s] > 0).map((s) => (
          <li key={s} className={`automation-badge automation-badge--${s}`}>
            <span aria-hidden="true">{ICON[s]}</span> {doc.counts[s]} {LABEL[s].toLowerCase()}
          </li>
        ))}
      </ul>
      {doc.tasks.length === 0 ? (
        <p className="automation-panel__empty">No taskbot tickets in the last 14 days.</p>
      ) : (
        <ul className="automation-panel__list">
          {doc.tasks.map((t) => (
            <TaskRow key={t.id} task={t} nowMs={nowMs} />
          ))}
        </ul>
      )}
      <ul className="automation-panel__notes">
        {doc.notes.map((n, i) => (
          <li key={i}>{n}</li>
        ))}
      </ul>
    </section>
  );
}
