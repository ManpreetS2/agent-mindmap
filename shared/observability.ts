/**
 * TypeScript mirror of schema/observability.schema.json (served at /observability.json).
 * Keep in sync with the schema. The document never contains session content, hostnames,
 * usernames, filesystem paths or credentials.
 */

export type QuotaPoolId = "claude-1" | "claude-2" | "cursor-premium" | "devin-free" | "codex";
export type QuotaProvider = "claude" | "cursor" | "devin" | "codex";

/**
 * VERIFIED     fresh reading from a supported programmatic source
 * MANUAL       fresh, explicitly entered by the owner (source + timestamp required)
 * STALE        a reading existed but its expires_at has passed: values are history, not current state
 * UNKNOWN      no reading at all
 * UNSUPPORTED  no supported programmatic source exists (reason says what is visible only in a UI)
 * ERROR        collection failed (reason, e.g. authentication); no values
 */
export type QuotaStatus = "VERIFIED" | "MANUAL" | "STALE" | "UNKNOWN" | "UNSUPPORTED" | "ERROR";

export type QuotaWindowType = "session" | "weekly" | "monthly" | "other";

export interface QuotaWindow {
  type: QuotaWindowType;
  label: string;
  window_minutes: number | null;
  used_pct: number | null;
  remaining_pct: number | null;
  /** ISO time; a window whose reset time has passed is no longer current. */
  resets_at: string | null;
}

export interface QuotaSource {
  kind: "codex-app-server" | "claude-statusline" | "cursor-cli" | "manual" | "t3-ui" | "none";
  method: string;
  supported_programmatically: boolean;
}

export interface QuotaPool {
  id: QuotaPoolId;
  label: string;
  provider: QuotaProvider;
  account_alias: string;
  plan: string | null;
  status: QuotaStatus;
  windows: QuotaWindow[];
  source: QuotaSource;
  observed_at: string | null;
  /** After this instant the reading must be treated as STALE even if the server did not say so. */
  expires_at: string | null;
  reason: string | null;
}

export interface MachineInfo {
  /** Stable random id (never derived from hostname, username or hardware). */
  id: string;
  /** Owner-chosen non-identifying label, e.g. "Mac A". */
  label: string;
  role: "publisher" | "reader";
  platform: string;
}

export interface CollectorHealth {
  status: "connected" | "unavailable" | "unknown";
  last_t3_poll: string | null;
  stale_after_sec: number | null;
  reason: string | null;
}

export interface FeedOwner {
  machine_id: string;
  label: string;
  epoch: number;
}

export interface FeedHealth {
  status: "fresh" | "stale" | "unknown" | "unpublished" | "disabled";
  last_published_at: string | null;
  last_observed_at: string | null;
  trusted_until: string | null;
  owner: FeedOwner | null;
  owned_by_this_machine: boolean | null;
  last_error: string | null;
}

export interface Observability {
  schema: "agent-mindmap-observability/v1";
  generated_at: string;
  /** "demo" = synthetic fixture data; must be labelled as such everywhere. */
  mode: "live" | "demo";
  machine: MachineInfo;
  collector: CollectorHealth;
  feed: FeedHealth;
  quota: { pools: QuotaPool[]; collected_at: string | null };
  notes: string[];
}

export const QUOTA_POOL_ORDER: readonly QuotaPoolId[] = [
  "claude-1", "claude-2", "cursor-premium", "devin-free", "codex",
];
