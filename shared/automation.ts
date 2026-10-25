/**
 * TypeScript mirror of schema/automation.schema.json (served at /automation.json).
 * Read-only view of Agent Control taskbot job records. A task is NOT a T3 session, and an
 * issue -> PR link is taskbot's own bookkeeping, not model-to-model delegation. The document has no
 * edges, no prompts, no raw logs, and no hostnames, usernames, paths or credentials.
 */

export type AutomationTaskState =
  | "queued"
  | "running"
  | "blocked"
  | "failed"
  | "completed"
  | "skipped"
  | "unknown";

export type AutomationSourceStatus = "connected" | "absent" | "unreadable" | "unsupported_schema";

export interface AutomationAssignment {
  account: string | null;
  /** null unless a run record or the run_start event stated it. */
  model: string | null;
  effort: string | null;
  known: boolean;
  source: "run_record" | "event_message" | "none";
}

export interface AutomationRun {
  run_id: string | null;
  started_at: string | null;
  ended_at: string | null;
  outcome: string | null;
  duration_sec: number | null;
}

export interface AutomationEvidence {
  type: string | null;
  time: string | null;
  severity: "info" | "warning" | "error";
  /** One redacted line; never the raw event message. */
  summary: string | null;
}

export interface AutomationEventRef {
  time: string | null;
  type: string | null;
  severity: "info" | "warning" | "error";
  run_id: string | null;
}

export interface AutomationTask {
  /** taskbot:<owner>/<repo>#<n> */
  id: string;
  repo: string;
  issue: { number: number; title: string | null; url: string | null };
  state: AutomationTaskState;
  /** Why this state: the record(s) it was derived from. */
  state_basis: string;
  state_observed_at: string | null;
  attempts: number | null;
  assignment: AutomationAssignment;
  /** Only for a draft PR taskbot itself opened (or one that was merged). */
  pull_request_url: string | null;
  current_run: AutomationRun | null;
  next_attempt_after: string | null;
  error_evidence: AutomationEvidence | null;
  recent_events: AutomationEventRef[];
}

export interface Automation {
  schema: "agent-mindmap-automation/v1";
  generated_at: string;
  /** "demo" = synthetic fixture; must be labelled as such everywhere. */
  mode: "live" | "demo";
  source: {
    kind: "agent-control-taskbot";
    status: AutomationSourceStatus;
    last_event_at: string | null;
    reason: string | null;
  };
  tasks: AutomationTask[];
  notes: string[];
}

export const AUTOMATION_STATES: readonly AutomationTaskState[] = [
  "running", "blocked", "queued", "failed", "unknown", "completed", "skipped",
];
