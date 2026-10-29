import type {
  Automation,
  AutomationTask,
  AutomationTaskState,
} from "@shared/automation";
import { looksPrivate } from "./observabilitySanitize";

/** Document older than this is stale even if it still says "running". */
export const AUTOMATION_STALE_MS = 15 * 60 * 1000;
/** A running task whose state was last observed longer ago than this is shown as unknown. */
export const RUNNING_STALE_MS = 30 * 60 * 1000;

const STATES = new Set<string>(["queued", "running", "blocked", "failed", "completed", "skipped", "unknown"]);
const SOURCE_STATUSES = new Set(["connected", "absent", "unreadable", "unsupported_schema"]);
const SEVERITIES = new Set(["info", "warning", "error"]);
const ISSUE_URL = /^https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/issues\/\d+$/;
const PR_URL = /^https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/pull\/\d+$/;
const MAX_TASKS = 50;
const MAX_TEXT = 300;

function obj(v: unknown): v is Record<string, unknown> {
  return !!v && typeof v === "object" && !Array.isArray(v);
}
const strOrNull = (v: unknown) => v === null || typeof v === "string";

function taskShapeOk(t: unknown): boolean {
  if (!obj(t)) return false;
  if (typeof t.id !== "string" || !/^taskbot:[\w.-]+\/[\w.-]+#\d+$/.test(t.id)) return false;
  if (typeof t.repo !== "string" || typeof t.state_basis !== "string") return false;
  if (typeof t.state !== "string" || !STATES.has(t.state)) return false;
  if (!obj(t.issue) || typeof t.issue.number !== "number" || !strOrNull(t.issue.title) || !strOrNull(t.issue.url)) return false;
  if (!strOrNull(t.state_observed_at) || !strOrNull(t.next_attempt_after)) return false;
  if (!(t.attempts === null || typeof t.attempts === "number")) return false;
  if (!obj(t.assignment) || typeof t.assignment.known !== "boolean") return false;
  for (const k of ["account", "model", "effort"]) if (!strOrNull((t.assignment as Record<string, unknown>)[k])) return false;
  if (!strOrNull(t.pull_request_url)) return false;
  if (!(t.current_run === null || (obj(t.current_run) && strOrNull(t.current_run.started_at) && strOrNull(t.current_run.ended_at)))) return false;
  if (!(t.error_evidence === null || (obj(t.error_evidence) && SEVERITIES.has(t.error_evidence.severity as string)))) return false;
  if (!Array.isArray(t.recent_events)) return false;
  return true;
}

/** Strict structural guard. Anything off-contract is rejected, never partially trusted. */
export function isAutomationShape(value: unknown): value is Automation {
  if (!obj(value)) return false;
  if (value.schema !== "agent-mindmap-automation/v1") return false;
  if (typeof value.generated_at !== "string") return false;
  if (value.mode !== "live" && value.mode !== "demo") return false;
  const s = value.source;
  if (!obj(s) || s.kind !== "agent-control-taskbot" || typeof s.status !== "string" || !SOURCE_STATUSES.has(s.status)) return false;
  if (!strOrNull(s.last_event_at) || !strOrNull(s.reason)) return false;
  if (!Array.isArray(value.tasks) || value.tasks.length > MAX_TASKS) return false;
  if (!value.tasks.every(taskShapeOk)) return false;
  if (!Array.isArray(value.notes) || !value.notes.every((n) => typeof n === "string")) return false;
  return true;
}

function text(v: string | null): string | null {
  if (v == null) return null;
  const clean = v.replace(/[\u0000-\u001f\u007f]+/g, " ").trim();
  if (looksPrivate(clean)) return "[redacted]";
  return clean.length > MAX_TEXT ? clean.slice(0, MAX_TEXT) : clean;
}

function sanitizeTask(t: AutomationTask): AutomationTask {
  return {
    ...t,
    repo: text(t.repo) ?? "[redacted]",
    issue: {
      number: t.issue.number,
      title: text(t.issue.title),
      url: t.issue.url && ISSUE_URL.test(t.issue.url) ? t.issue.url : null,
    },
    state_basis: text(t.state_basis) ?? "",
    assignment: {
      ...t.assignment,
      account: text(t.assignment.account),
      model: text(t.assignment.model),
      effort: text(t.assignment.effort),
    },
    pull_request_url: t.pull_request_url && PR_URL.test(t.pull_request_url) ? t.pull_request_url : null,
    current_run: t.current_run
      ? { ...t.current_run, run_id: text(t.current_run.run_id), outcome: text(t.current_run.outcome) }
      : null,
    error_evidence: t.error_evidence
      ? { ...t.error_evidence, type: text(t.error_evidence.type), summary: text(t.error_evidence.summary) }
      : null,
    recent_events: t.recent_events.slice(0, 6),
  };
}

/** Redact private-looking free text and drop non-GitHub links at the transport boundary. */
export function sanitizeAutomation(doc: Automation): Automation {
  return {
    ...doc,
    source: { ...doc.source, reason: text(doc.source.reason) },
    tasks: doc.tasks.slice(0, MAX_TASKS).map(sanitizeTask),
    notes: doc.notes.map((n) => text(n) ?? "[redacted]"),
  };
}

export interface EvaluatedTask extends AutomationTask {
  /** State after client-side checks. "running" never survives a stale document or an old observation. */
  effectiveState: AutomationTaskState;
  /** Set when the client downgraded the server's state. */
  downgradeReason: string | null;
  /** True for demo documents: every task is illustrative. */
  simulated: boolean;
}

export interface EvaluatedAutomation extends Omit<Automation, "tasks"> {
  documentStale: boolean;
  tasks: EvaluatedTask[];
  counts: Record<AutomationTaskState, number>;
}

function ms(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  return Number.isFinite(t) ? t : null;
}

export function evaluateAutomation(doc: Automation, nowMs: number): EvaluatedAutomation {
  const generated = ms(doc.generated_at);
  const documentStale = generated === null || nowMs - generated > AUTOMATION_STALE_MS;
  const counts = { queued: 0, running: 0, blocked: 0, failed: 0, completed: 0, skipped: 0, unknown: 0 } as Record<
    AutomationTaskState,
    number
  >;
  const tasks = doc.tasks.map((t): EvaluatedTask => {
    let effectiveState = t.state;
    let downgradeReason: string | null = null;
    if (t.state === "running") {
      const seen = ms(t.state_observed_at);
      if (documentStale) {
        effectiveState = "unknown";
        downgradeReason = "This document is stale; the job may have finished or died since.";
      } else if (seen === null || nowMs - seen > RUNNING_STALE_MS) {
        effectiveState = "unknown";
        downgradeReason = "No recent evidence that this job is still running.";
      }
    }
    counts[effectiveState] += 1;
    return { ...t, effectiveState, downgradeReason, simulated: doc.mode === "demo" };
  });
  return { ...doc, documentStale, tasks, counts };
}
