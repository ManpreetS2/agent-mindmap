/**
 * TypeScript mirror of schema/activity.schema.json (activity.json).
 * Keep in sync when the schema changes.
 *
 * MM-020a separates models:
 * - Identity: BotConfigEntry (config/bots.json)
 * - Membership: GroupConfig / Membership (config/groups.json)
 * - Messages: NetworkEvent (+ activity Event of type "message")
 * - Tasks: Task (ledger)
 * - Activity: Activity snapshot (nodes / events / edges)
 */

export type Status =
  | "IDLE"
  | "IN_PROGRESS"
  | "IN_REVIEW"
  | "BLOCKED"
  | "DONE"
  | "UNKNOWN";

/** Evidence-based live agent state (MM-020); maps from Status in later tasks. */
export type AgentState =
  | "ACTIVE"
  | "IDLE"
  | "BLOCKED"
  | "COMPLETED"
  | "UNKNOWN";

export type NodeGroup = "owner" | "build" | "qr" | "radar";

/** Group id string; known v1 ids are NodeGroup; later groups may be added via config. */
export type GroupId = NodeGroup | (string & {});

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
  | "unparsed"
  | "message";

/** MM-020a: message edges for bot↔bot or sender→group:{id}. */
export type EdgeType = "handoff" | "verdict" | "pr" | "merge" | "message";

export type Verdict =
  | "PASS"
  | "FAIL"
  | "CHANGES"
  | "CONDITIONAL"
  | "BLOCKED"
  | "INCONCLUSIVE";

export type AttributionMethod = "signature" | "ledger_owner" | "unknown";

/** Provenance of a live / network fact (MM-020a). */
export type Provenance = "observed" | "agent-reported" | "github-verified";

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
  /** Primary / layout-home group (backward compatible). */
  group: NodeGroup;
  /**
   * Full membership from config/groups.json (schema ≥ 1.1.0).
   * One identity across groups — do not duplicate node ids.
   */
  groups?: GroupId[];
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
  /** owner/name — PR joins use (repo, number), never number alone. */
  repo?: string;
  sha?: string;
  /** Known tokens preferred; UI must fall back cleanly on unknown strings. */
  verdict?: Verdict | (string & {}) | null;
  attribution: Attribution;
  source_url: string;
  source_time: string;
  raw: string;
  /**
   * Required on schema 1.1.0 events. Legacy 1.0.0 fixtures omit it on disk;
   * migrate_activity fills it (GitHub → github-verified; ledger/signature →
   * agent-reported). Never invent recipients.
   */
  provenance: Provenance;
  /**
   * Explicit recipients only (schema ≥ 1.1.0). Never invent from ambient context.
   * Untargeted group messages omit this and use edge target `group:{id}`.
   */
  recipients?: string[];
  /** Group context for a message event (schema ≥ 1.1.0). */
  group?: GroupId;
  related_id?: string | null;
}

export interface Edge {
  id: string;
  source: string;
  /** Bot id, or `group:{groupId}` for untargeted group messages. */
  target: string;
  type: EdgeType;
  count: number;
  event_ids: string[];
}

export type GitHubMetaStatus = "ok" | "error" | "skipped" | "rate_limited";

export type LedgerMetaStatus = "ok" | "error" | "skipped";

export interface ActivityMeta {
  github: GitHubMetaStatus;
  /** Present when ingest reports ledger read status (MM-010). */
  ledger?: LedgerMetaStatus;
  /** Latest dated ledger entry; preferred for the stale banner (MM-010). */
  ledger_last_entry_at?: string | null;
  /** Optional live overlay marker (schema ≥ 1.1.0). */
  events_source?: string;
}

/** 1.0.0 fixtures remain valid; new builds emit 1.1.0. */
export type ActivitySchemaVersion = "1.0.0" | "1.1.0";

export interface Activity {
  schema_version: ActivitySchemaVersion;
  generated_at: string;
  project: "fencepost";
  meta: ActivityMeta;
  nodes: Node[];
  tasks: Task[];
  events: Event[];
  edges: Edge[];
  unparsed: Event[];
}

/** Live collector / SSE payload (messages model). Not required on activity.json. */
export interface NetworkEvent {
  id: string;
  ts: string;
  sender: string;
  /** Only when explicit; never invented. */
  recipients?: string[];
  group: GroupId;
  type: string;
  task_id?: string | null;
  /** Sanitized short summary — never raw transcript. */
  summary: string;
  provenance: Provenance;
  related_id?: string | null;
}

/** Identity entry from config/bots.json. */
export interface BotConfigEntry {
  id: string;
  display_name: string;
  aliases: string[];
  /** Layout / home group for backward-compatible nodes. */
  group: NodeGroup;
  layout: Layout;
  note?: string;
}

export interface BotsConfig {
  schema_version: ActivitySchemaVersion;
  description?: string;
  bots: BotConfigEntry[];
}

/** Membership entry from config/groups.json. */
export interface GroupConfigEntry {
  id: GroupId;
  label: string;
  members: string[];
}

export interface GroupsConfig {
  schema_version: string;
  description?: string;
  groups: GroupConfigEntry[];
}

/** Logical membership row: one bot in one group. */
export interface Membership {
  bot_id: string;
  group_id: GroupId;
}
