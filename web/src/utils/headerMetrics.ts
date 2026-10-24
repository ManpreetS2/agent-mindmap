import type { Activity } from "@shared/types";

export interface AgentMetrics {
  total: number;
  working: number;
  blocked: number;
  failed: number;
  done: number;
  /** Idle, stale, unknown: sessions with no fresh work to report. */
  other: number;
  /**
   * Parent → child delegation relationships reported by T3. This is lineage only; it is a different
   * concept from the legacy ledger's "handoffs" (task hand-offs between bots), which T3 never produces.
   */
  delegations: number;
}

export function agentMetrics(activity: Activity): AgentMetrics {
  const m: AgentMetrics = { total: 0, working: 0, blocked: 0, failed: 0, done: 0, other: 0, delegations: 0 };
  for (const n of activity.nodes) {
    if (!n.session) continue;
    m.total++;
    if (n.status === "IN_PROGRESS" || n.status === "IN_REVIEW") m.working++;
    else if (n.status === "BLOCKED") m.blocked++;
    else if (n.status === "FAILED") m.failed++;
    else if (n.status === "DONE") m.done++;
    else m.other++;
  }
  m.delegations = activity.edges.filter((e) => e.type === "delegation").length;
  return m;
}

export type SourceKind = "ledger" | "live" | "unavailable" | "demo" | "replay";

/** What the data actually is. Only `live` may be presented as real T3 activity. */
export function sourceKind(activity: Activity): SourceKind {
  const t3 = activity.meta.t3;
  if (!t3) return "ledger";
  if (t3.mode === "demo") return t3.replay ? "replay" : "demo";
  return t3.connection === "connected" ? "live" : "unavailable";
}
