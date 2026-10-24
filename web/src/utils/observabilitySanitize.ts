import type { Observability, QuotaPool, QuotaWindow } from "@shared/observability";

const MAX_TEXT = 200;
const REDACTED = "[redacted]";

/** Entire-field private-pattern match (never partial scrub). */
const PRIVATE_PATTERN =
  /(?:\/Users\/|\/home\/|~\/\.config|~\/\.local|[A-Z]:\\Users\\)|(?:[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})|(?:\bBearer\s+\S+)|(?:\b(?:sk|ghp|gho|xox[baprs])-[A-Za-z0-9_-]{8,})|(?:[A-Fa-f0-9]{32,})|(?:[A-Za-z0-9+/]{40,}={0,2})|(?:[a-z][a-z0-9+.-]*:\/\/[^/\s]*:[^/\s]*@)/i;

export function looksPrivate(value: string): boolean {
  return PRIVATE_PATTERN.test(value);
}

function sanitizeText(value: string | null | undefined): string | null {
  if (value == null) return value ?? null;
  if (typeof value !== "string") return REDACTED;
  if (looksPrivate(value)) return REDACTED;
  return value.length > MAX_TEXT ? value.slice(0, MAX_TEXT) : value;
}

const WINDOW_TYPES = new Set(["session", "weekly", "monthly", "other"]);

function pctOk(v: unknown): v is number | null {
  if (v === null) return true;
  return typeof v === "number" && Number.isFinite(v) && v >= 0 && v <= 100;
}

/** Returns a valid window or null if the entry is unusable. */
export function sanitizeWindow(raw: unknown): QuotaWindow | null {
  if (!raw || typeof raw !== "object") return null;
  const w = raw as Record<string, unknown>;
  if (typeof w.type !== "string" || !WINDOW_TYPES.has(w.type)) return null;
  if (typeof w.label !== "string") return null;
  if (!(w.window_minutes === null || (typeof w.window_minutes === "number" && Number.isFinite(w.window_minutes) && w.window_minutes >= 1))) {
    return null;
  }
  if (!pctOk(w.used_pct) || !pctOk(w.remaining_pct)) return null;
  if (!(w.resets_at === null || typeof w.resets_at === "string")) return null;
  return {
    type: w.type as QuotaWindow["type"],
    label: sanitizeText(w.label) ?? REDACTED,
    window_minutes: w.window_minutes as number | null,
    used_pct: w.used_pct as number | null,
    remaining_pct: w.remaining_pct as number | null,
    resets_at: w.resets_at as string | null,
  };
}

function sanitizePool(raw: QuotaPool): QuotaPool {
  const windowsIn = Array.isArray(raw.windows) ? raw.windows : [];
  const hadInvalid = windowsIn.some((w) => sanitizeWindow(w) === null);
  const windows = windowsIn
    .map((w) => sanitizeWindow(w))
    .filter((w): w is QuotaWindow => w !== null);

  let status = raw.status;
  let reason = sanitizeText(raw.reason);
  if (hadInvalid) {
    status = "UNKNOWN";
    reason = "invalid reading";
  }

  return {
    ...raw,
    label: sanitizeText(raw.label) ?? REDACTED,
    account_alias: sanitizeText(raw.account_alias) ?? REDACTED,
    plan: raw.plan == null ? null : sanitizeText(raw.plan),
    status,
    windows: hadInvalid ? [] : windows,
    source: {
      ...raw.source,
      method: sanitizeText(raw.source.method) ?? REDACTED,
    },
    reason,
  };
}

/**
 * Redact private free-text and normalize malformed windows at the transport boundary.
 * Returns null when the payload cannot be made safe (e.g. only-null windows with no salvage).
 * For entirely null window arrays that produce zero windows from a pool that claimed readings,
 * the pool is marked UNKNOWN with reason "invalid reading" (still a valid document).
 */
export function sanitizeObservability(doc: Observability): Observability {
  const owner = doc.feed.owner
    ? {
        ...doc.feed.owner,
        label: sanitizeText(doc.feed.owner.label) ?? REDACTED,
      }
    : null;

  return {
    ...doc,
    machine: {
      ...doc.machine,
      label: sanitizeText(doc.machine.label) ?? REDACTED,
    },
    collector: {
      ...doc.collector,
      reason: sanitizeText(doc.collector.reason),
    },
    feed: {
      ...doc.feed,
      owner,
      last_error: sanitizeText(doc.feed.last_error),
    },
    quota: {
      ...doc.quota,
      pools: doc.quota.pools.map(sanitizePool),
    },
    notes: doc.notes.map((n) => sanitizeText(n) ?? REDACTED),
  };
}
