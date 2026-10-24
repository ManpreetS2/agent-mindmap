import type { Activity, ActivityMeta } from "@shared/types";

export const STALE_THRESHOLD_MS = 10 * 60 * 1000;

export const LEDGER_ERROR_PATH = "build/task-ledger.md";

export function isActivityEmpty(activity: Activity): boolean {
  if (activity.meta.t3) return activity.nodes.length === 0;
  return (
    activity.events.length === 0 &&
    activity.tasks.length === 0 &&
    activity.unparsed.length === 0
  );
}

export function isStaleGeneratedAt(
  generatedAt: string,
  nowMs = Date.now(),
): boolean {
  const t = new Date(generatedAt).getTime();
  if (Number.isNaN(t)) return false;
  return nowMs - t > STALE_THRESHOLD_MS;
}

/** Prefer ledger_last_entry_at (MM-010); fall back to generated_at. */
export function staleReferenceTime(activity: Activity): string {
  const last = activity.meta.ledger_last_entry_at;
  if (typeof last === "string" && last.length > 0) return last;
  return activity.generated_at;
}

export function isActivityStale(
  activity: Activity,
  nowMs = Date.now(),
): boolean {
  if (activity.meta.t3) return activity.meta.t3.connection === "unavailable" || activity.nodes.some(n => n.session?.stale);
  return isStaleGeneratedAt(staleReferenceTime(activity), nowMs);
}

export function staleAgeLabel(generatedAt: string, nowMs = Date.now()): string {
  const mins = Math.round((nowMs - new Date(generatedAt).getTime()) / 60_000);
  if (mins < 60) return `${mins} minutes ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours} hours ago`;
  return `${Math.round(hours / 24)} days ago`;
}

export function partialGithubBanner(meta: ActivityMeta): string | null {
  if (meta.t3) return meta.t3.connection === "unavailable" ? "T3 unavailable — last known sessions are stale. Reconnecting automatically." : null;
  const status = meta.github as string;
  if (status === "ok") return null;
  const sourceName =
    status === "rate_limited"
      ? "GitHub (rate limited)"
      : status === "skipped"
        ? "GitHub (skipped)"
        : "GitHub (error)";
  return `${sourceName} — showing ledger only. Retry refresh.`;
}

