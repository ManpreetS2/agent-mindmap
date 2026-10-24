import type { Activity, Node, Task } from "@shared/types";
import type { Observability, QuotaPoolId } from "@shared/observability";
import { QUOTA_POOL_ORDER } from "@shared/observability";
import {
  evaluateObservability,
  OBSERVABILITY_STALE_MS,
  type EvaluatedQuotaPool,
} from "./observabilityEval";
import { isActivityStale, STALE_THRESHOLD_MS } from "./viewState";
import { formatRelativeAgo } from "./format";

/** Pools at or above this used% on any numeric window are ineligible. */
export const QUOTA_USED_PCT_LIMIT = 85;
/** Clock skew tolerance for future timestamps. */
export const FUTURE_EVIDENCE_SKEW_MS = 60_000;

export interface RecommendationCandidate {
  poolId: QuotaPoolId;
  label: string;
  provider: string;
  rank: number;
  evidence: string[];
  limitations: string[];
}

export interface WorkloadBlocker {
  kind: "session" | "task";
  id: string;
  label: string;
  status: string;
  age: string;
}

export interface RecommendationResult {
  status: "RECOMMENDATIONS" | "INSUFFICIENT_DATA";
  candidates: RecommendationCandidate[];
  reasons: string[];
  blockers: WorkloadBlocker[];
}

const BASE_LIMITATIONS = [
  "Which Claude account a session ran under is unknown unless session.account is present",
  "T3 updates are not proof of execution",
  "Quota is per account and never combined",
] as const;

function parseMs(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  return Number.isFinite(t) ? t : null;
}

function collectorPollFresh(doc: Observability, nowMs: number): boolean {
  if (doc.collector.status !== "connected") return false;
  const poll = parseMs(doc.collector.last_t3_poll);
  if (poll === null) return false;
  if (poll > nowMs + FUTURE_EVIDENCE_SKEW_MS) return false;
  const staleAfter =
    (doc.collector.stale_after_sec ?? 300) * 1000;
  return nowMs - poll <= staleAfter;
}

function activityEvidenceOk(activity: Activity, nowMs: number): string | null {
  const generated = parseMs(activity.generated_at);
  if (generated === null) return "Activity generated_at is missing or invalid";
  if (generated > nowMs + FUTURE_EVIDENCE_SKEW_MS) {
    return "Activity generated_at is in the future";
  }
  if (nowMs - generated > STALE_THRESHOLD_MS) {
    return "Activity generated_at is stale";
  }
  if (isActivityStale(activity, nowMs)) {
    return "Activity is stale or T3 connection unavailable";
  }
  return null;
}

function maxUsedPct(pool: EvaluatedQuotaPool): number | null {
  let max: number | null = null;
  for (const w of pool.windows) {
    if (typeof w.used_pct === "number" && Number.isFinite(w.used_pct)) {
      max = max === null ? w.used_pct : Math.max(max, w.used_pct);
    }
  }
  return max;
}

function poolIneligibilityReason(pool: EvaluatedQuotaPool, nowMs: number): string {
  if (pool.clientExpired) {
    return `${pool.id}: expired on client (expires_at/resets_at vs now=${new Date(nowMs).toISOString()})`;
  }
  if (pool.effectiveStatus !== "VERIFIED" && pool.effectiveStatus !== "MANUAL") {
    return `${pool.id}: status ${pool.effectiveStatus}${pool.reason ? ` (${pool.reason})` : ""}`;
  }
  if (!pool.observed_at || parseMs(pool.observed_at) === null) {
    return `${pool.id}: observed_at missing`;
  }
  const observed = parseMs(pool.observed_at)!;
  if (observed > nowMs + FUTURE_EVIDENCE_SKEW_MS) {
    return `${pool.id}: observed_at is in the future`;
  }
  if (!pool.expires_at || parseMs(pool.expires_at) === null) {
    return `${pool.id}: expires_at missing`;
  }
  if (parseMs(pool.expires_at)! <= nowMs) {
    return `${pool.id}: expires_at has passed`;
  }
  if (pool.windows.length < 1) {
    return `${pool.id}: no windows reported`;
  }
  for (const w of pool.windows) {
    if (typeof w.used_pct !== "number" || !Number.isFinite(w.used_pct)) {
      return `${pool.id}: window "${w.label}" used_pct is null or not finite`;
    }
    const r = parseMs(w.resets_at);
    if (r !== null && r <= nowMs) {
      return `${pool.id}: window "${w.label}" resets_at ${w.resets_at} has passed`;
    }
    if (w.used_pct >= QUOTA_USED_PCT_LIMIT) {
      return `${pool.id}: window "${w.label}" used_pct=${w.used_pct} >= ${QUOTA_USED_PCT_LIMIT}`;
    }
  }
  return `${pool.id}: ineligible`;
}

function isPoolEligible(pool: EvaluatedQuotaPool, nowMs: number): boolean {
  if (pool.effectiveStatus !== "VERIFIED" && pool.effectiveStatus !== "MANUAL") {
    return false;
  }
  if (pool.clientExpired) return false;
  if (!pool.observed_at || parseMs(pool.observed_at) === null) return false;
  const observed = parseMs(pool.observed_at)!;
  if (observed > nowMs + FUTURE_EVIDENCE_SKEW_MS) return false;
  if (!pool.expires_at || parseMs(pool.expires_at) === null) return false;
  if (parseMs(pool.expires_at)! <= nowMs) return false;
  if (pool.windows.length < 1) return false;
  for (const w of pool.windows) {
    if (typeof w.used_pct !== "number" || !Number.isFinite(w.used_pct)) return false;
    const r = parseMs(w.resets_at);
    if (r !== null && r <= nowMs) return false;
    if (w.used_pct >= QUOTA_USED_PCT_LIMIT) return false;
  }
  return true;
}

function evidenceFor(pool: EvaluatedQuotaPool): string[] {
  const out: string[] = [
    `pool id=${pool.id} status=${pool.effectiveStatus} source.method=${pool.source.method}`,
  ];
  if (pool.observed_at) out.push(`observed_at=${pool.observed_at}`);
  for (const w of pool.windows) {
    out.push(
      `window "${w.label}" used_pct=${w.used_pct ?? "null"} remaining_pct=${w.remaining_pct ?? "null"} resets_at=${w.resets_at ?? "null"}`,
    );
  }
  return out;
}

function blockersFrom(activity: Activity, now: Date): WorkloadBlocker[] {
  const blockers: WorkloadBlocker[] = [];
  for (const n of activity.nodes) {
    if (n.status === "BLOCKED" || n.status === "FAILED") {
      blockers.push({
        kind: "session",
        id: n.id,
        label: n.label,
        status: n.status,
        age: n.last_activity_ts
          ? formatRelativeAgo(n.last_activity_ts, now)
          : "age not reported",
      });
    }
  }
  for (const t of activity.tasks) {
    const raw = (t.status_raw || "").toLowerCase();
    if (
      t.status === "BLOCKED" ||
      t.status === "FAILED" ||
      raw.includes("wait") ||
      raw.includes("blocked")
    ) {
      blockers.push({
        kind: "task",
        id: t.id,
        label: t.title,
        status: t.status_raw || t.status,
        age: "task age not reported",
      });
    }
  }
  return blockers.sort((a, b) => a.id.localeCompare(b.id));
}

/**
 * Deterministic workload suggestions. Never recommends dispatch/billing actions.
 * Demo mode is always INSUFFICIENT_DATA (illustrative).
 */
export function recommend(
  activity: Activity,
  observability: Observability | null,
  now: Date | number,
): RecommendationResult {
  const nowMs = typeof now === "number" ? now : now.getTime();
  const nowDate = new Date(nowMs);
  const blockers = blockersFrom(activity, nowDate);

  if (!observability) {
    return {
      status: "INSUFFICIENT_DATA",
      candidates: [],
      reasons: ["Observability document is absent"],
      blockers,
    };
  }

  if (observability.mode === "demo") {
    return {
      status: "INSUFFICIENT_DATA",
      candidates: [],
      reasons: [
        "Illustrative DEMO data — recommendations require mode=live",
      ],
      blockers,
    };
  }

  const activityBad = activityEvidenceOk(activity, nowMs);
  if (activityBad) {
    return {
      status: "INSUFFICIENT_DATA",
      candidates: [],
      reasons: [activityBad],
      blockers,
    };
  }

  if (!collectorPollFresh(observability, nowMs)) {
    return {
      status: "INSUFFICIENT_DATA",
      candidates: [],
      reasons: [
        `Collector not connected with a fresh last_t3_poll (status=${observability.collector.status}, last_t3_poll=${observability.collector.last_t3_poll})`,
      ],
      blockers,
    };
  }

  const evaluated = evaluateObservability(observability, nowMs);
  if (evaluated.documentStale) {
    return {
      status: "INSUFFICIENT_DATA",
      candidates: [],
      reasons: [
        `Observability document is stale (generated_at older than ${OBSERVABILITY_STALE_MS / 60000}m)`,
      ],
      blockers,
    };
  }
  const eligible = evaluated.pools.filter((p) => isPoolEligible(p, nowMs));

  if (eligible.length === 0) {
    const reasons = QUOTA_POOL_ORDER.map((id) => {
      const pool = evaluated.pools.find((p) => p.id === id)!;
      return poolIneligibilityReason(pool, nowMs);
    });
    return {
      status: "INSUFFICIENT_DATA",
      candidates: [],
      reasons,
      blockers,
    };
  }

  const ranked = [...eligible].sort((a, b) => {
    const ma = maxUsedPct(a) ?? 100;
    const mb = maxUsedPct(b) ?? 100;
    if (ma !== mb) return ma - mb;
    return QUOTA_POOL_ORDER.indexOf(a.id) - QUOTA_POOL_ORDER.indexOf(b.id);
  });

  const candidates: RecommendationCandidate[] = ranked.map((pool, i) => ({
    poolId: pool.id,
    label: pool.label,
    provider: pool.provider,
    rank: i + 1,
    evidence: evidenceFor(pool),
    limitations: [...BASE_LIMITATIONS],
  }));

  return {
    status: "RECOMMENDATIONS",
    candidates,
    reasons: [
      `Ranked ${candidates.length} eligible pool(s) by lowest max used_pct then fixed pool order`,
    ],
    blockers,
  };
}

/** Exposed for tests: session helper typing. */
export type { Node, Task };
