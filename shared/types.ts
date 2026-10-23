/**
 * TypeScript mirror of schema/activity.schema.json (activity.json).
 * Keep in sync when the schema changes.
 */

export type Status =
  | "IDLE"
  | "IN_PROGRESS"
  | "IN_REVIEW"
  | "BLOCKED"
  | "DONE"
  | "UNKNOWN"
  | "FAILED"
  | "STALE";

export type NodeGroup = "owner" | "build" | "qr" | "radar" | "sessions";

export type EventType =
  | "assigned"
  | "handoff"
  | "pr_opened"
  | "pr_updated"
  | "verdict"
  | "merged"
  | "blocker"
  | "ci"
  | "note"
  | "unparsed";

export type EdgeType = "handoff" | "verdict" | "pr" | "merge" | "delegation";

export type Verdict =
  | "PASS"
  | "FAIL"
  | "CHANGES"
  | "CONDITIONAL"
  | "BLOCKED"
  | "INCONCLUSIVE";

export type AttributionMethod = "signature" | "ledger_owner" | "unknown";

export interface Attribution {
  method: AttributionMethod;
}

export interface Layout {
  x: number;
  y: number;
}

export interface Node {
  id: string;
  label: string;
  group: NodeGroup;
  status: Status;
  current_task?: string;
  last_activity_ts?: string;
  agent_links: string[];
  layout: Layout;
  session?: SessionMetadata;
}

/**
 * Ledger / backlog task id.
 * Pattern: `^[A-Z]{2,}-[0-9]{3}[A-Za-z0-9]*(-[0-9]+)?$`
 * (e.g. `RP-005D`, `MM-001`, `QA-RP004-1`).
 */
export type TaskId = string;

export interface Task {
  id: TaskId;
  title: string;
  project: string;
  owner: string;
  status_raw: string;
  status: Status;
  prs: number[];
  source_url: string;
}

export interface Event {
  id: string;
  type: EventType;
  actor: string | null;
  target: string | null;
  /** Same pattern as {@link TaskId}. */
  task_id: TaskId | null;
  pr?: number;
  /** owner/name — PR joins use (repo, number), never number alone. */
  repo?: string;
  sha?: string;
  /** Known tokens preferred; UI must fall back cleanly on unknown strings. */
  verdict?: Verdict | (string & {}) | null;
  attribution: Attribution;
  source_url: string;
  source_time: string;
  raw: string;
}

export interface Edge {
  id: string;
  source: string;
  target: string;
  type: EdgeType;
  count: number;
  event_ids: string[];
}

export type GitHubMetaStatus = "ok" | "error" | "skipped" | "rate_limited";

export type LedgerMetaStatus = "ok" | "error" | "skipped";

export interface SessionMetadata {
  source: string;
  thread_id: string;
  project: string;
  provider: string | null;
  model: string | null;
  reported_status: string;
  branch: string | null;
  source_links: string[];
  stale: boolean;
}

export interface ActivityMeta {
  t3?: { source: string; mode: "live" | "demo"; connection: "connected" | "unavailable"; server_version: string | null; stale_after_sec: number; replay?: { stage: number; stage_count: number; cycle: number; step_sec: number; label: string } };
  github: GitHubMetaStatus;
  /** Present when ingest reports ledger read status (MM-010). */
  ledger?: LedgerMetaStatus;
  /** Latest dated ledger entry; preferred for the stale banner (MM-010). */
  ledger_last_entry_at?: string | null;
}

export interface Activity {
  schema_version: "1.0.0";
  generated_at: string;
  project: string;
  meta: ActivityMeta;
  nodes: Node[];
  tasks: Task[];
  events: Event[];
  edges: Edge[];
  unparsed: Event[];
}

/** Bot roster entry from config/bots.json (fixed layout + aliases). */
export interface BotConfigEntry {
  id: string;
  display_name: string;
  aliases: string[];
  group: NodeGroup;
  layout: Layout;
}

export interface BotsConfig {
  schema_version: "1.0.0";
  bots: BotConfigEntry[];
}

