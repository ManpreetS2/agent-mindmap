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
  | "UNKNOWN";

export type NodeGroup = "owner" | "build" | "qr" | "radar";

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

export type EdgeType = "handoff" | "verdict" | "pr" | "merge";

export type Verdict = "PASS" | "FAIL" | "CHANGES";

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
  sha?: string;
  verdict?: Verdict | null;
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

export type GitHubMetaStatus = "ok" | "error" | "skipped";

export interface ActivityMeta {
  github: GitHubMetaStatus;
}

export interface Activity {
  schema_version: "1.0.0";
  generated_at: string;
  project: "fencepost";
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
