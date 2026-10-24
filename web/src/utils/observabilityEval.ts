import type {
  Observability,
  QuotaPool,
  QuotaStatus,
} from "@shared/observability";
import { QUOTA_POOL_ORDER } from "@shared/observability";

/** Document older than this is treated as stale even if pools look fresh. */
export const OBSERVABILITY_STALE_MS = 15 * 60 * 1000;

export type EvaluatedQuotaPool = QuotaPool & {
  /** Status after client-side expiry / reset checks. */
  effectiveStatus: QuotaStatus;
  /** True when the client downgraded VERIFIED/MANUAL to STALE. */
  clientExpired: boolean;
};

export type EvaluatedObservability = Observability & {
  documentStale: boolean;
  pools: EvaluatedQuotaPool[];
};

function parseMs(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  return Number.isFinite(t) ? t : null;
}

/** Downgrade a pool when expires_at or any window resets_at has passed. */
export function evaluatePool(pool: QuotaPool, nowMs: number): EvaluatedQuotaPool {
  const expires = parseMs(pool.expires_at);
  const resetPassed = pool.windows.some((w) => {
    const r = parseMs(w.resets_at);
    return r !== null && r <= nowMs;
  });
  const expired = (expires !== null && expires <= nowMs) || resetPassed;
  const wasFresh = pool.status === "VERIFIED" || pool.status === "MANUAL";
  if (expired && wasFresh) {
    return {
      ...pool,
      effectiveStatus: "STALE",
      clientExpired: true,
      reason:
        pool.reason ??
        (resetPassed
          ? "A quota window reset time has passed; reading is no longer current"
          : "Reading expired on the client"),
    };
  }
  if (expired && pool.status !== "STALE") {
    return { ...pool, effectiveStatus: "STALE", clientExpired: true };
  }
  return {
    ...pool,
    effectiveStatus: pool.status,
    clientExpired: false,
  };
}

export function evaluateObservability(
  doc: Observability,
  nowMs: number,
): EvaluatedObservability {
  const generated = parseMs(doc.generated_at);
  const documentStale =
    generated === null || nowMs - generated > OBSERVABILITY_STALE_MS;
  const byId = new Map(doc.quota.pools.map((p) => [p.id, p]));
  const pools = QUOTA_POOL_ORDER.map((id) => {
    const pool = byId.get(id);
    if (!pool) {
      return evaluatePool(
        {
          id,
          label: id,
          provider: id.startsWith("claude")
            ? "claude"
            : id.startsWith("cursor")
              ? "cursor"
              : id.startsWith("devin")
                ? "devin"
                : "codex",
          account_alias: id,
          plan: null,
          status: "UNKNOWN",
          windows: [],
          source: {
            kind: "none",
            method: "pool missing from document",
            supported_programmatically: false,
          },
          observed_at: null,
          expires_at: null,
          reason: "Pool missing from observability document",
        },
        nowMs,
      );
    }
    return evaluatePool(pool, nowMs);
  });
  return { ...doc, documentStale, pools };
}

const POOL_IDS = new Set(QUOTA_POOL_ORDER);

/** Lightweight runtime check — rejects clearly invalid payloads without a full JSON Schema engine. */
export function isObservabilityShape(value: unknown): value is Observability {
  if (!value || typeof value !== "object") return false;
  const o = value as Record<string, unknown>;
  if (o.schema !== "agent-mindmap-observability/v1") return false;
  if (typeof o.generated_at !== "string") return false;
  if (o.mode !== "live" && o.mode !== "demo") return false;
  if (!o.machine || typeof o.machine !== "object") return false;
  const machine = o.machine as Record<string, unknown>;
  if (typeof machine.id !== "string" || typeof machine.label !== "string") return false;
  if (machine.role !== "publisher" && machine.role !== "reader") return false;
  if (!o.collector || typeof o.collector !== "object") return false;
  const collector = o.collector as Record<string, unknown>;
  if (
    collector.status !== "connected" &&
    collector.status !== "unavailable" &&
    collector.status !== "unknown"
  ) {
    return false;
  }
  if (!o.feed || typeof o.feed !== "object") return false;
  const feed = o.feed as Record<string, unknown>;
  const feedStatuses = ["fresh", "stale", "unknown", "unpublished", "disabled"];
  if (!feedStatuses.includes(feed.status as string)) return false;
  if (!o.quota || typeof o.quota !== "object") return false;
  const quota = o.quota as Record<string, unknown>;
  if (!Array.isArray(quota.pools) || quota.pools.length !== 5) return false;
  for (const p of quota.pools) {
    if (!p || typeof p !== "object") return false;
    const pool = p as Record<string, unknown>;
    if (typeof pool.id !== "string" || !POOL_IDS.has(pool.id as never)) return false;
    const statuses = ["VERIFIED", "MANUAL", "STALE", "UNKNOWN", "UNSUPPORTED", "ERROR"];
    if (!statuses.includes(pool.status as string)) return false;
    if (!Array.isArray(pool.windows)) return false;
    if (!pool.source || typeof pool.source !== "object") return false;
  }
  if (!Array.isArray(o.notes)) return false;
  return true;
}

export function formatAge(iso: string | null, nowMs: number): string {
  if (!iso) return "never";
  const t = parseMs(iso);
  if (t === null) return "unknown time";
  const mins = Math.round((nowMs - t) / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

export function countdownTo(iso: string | null, nowMs: number): string | null {
  const t = parseMs(iso);
  if (t === null) return null;
  const diff = t - nowMs;
  if (diff <= 0) return "passed";
  const mins = Math.round(diff / 60_000);
  if (mins < 60) return `in ${mins}m`;
  const hours = Math.floor(mins / 60);
  const rem = mins % 60;
  return rem ? `in ${hours}h ${rem}m` : `in ${hours}h`;
}
