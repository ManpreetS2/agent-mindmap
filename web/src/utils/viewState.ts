import type { Activity, ActivityMeta } from "@shared/types";

export const STALE_THRESHOLD_MS = 10 * 60 * 1000;

export const LEDGER_ERROR_PATH = "build/task-ledger.md";

export function isActivityEmpty(activity: Activity): boolean {
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
  return isStaleGeneratedAt(staleReferenceTime(activity), nowMs);
}

export function staleAgeLabel(generatedAt: string, nowMs = Date.now()): string {
  const timestampMs = new Date(generatedAt).getTime();
  if (Number.isNaN(timestampMs)) return "unknown age";
  const ageMs = nowMs - timestampMs;
  if (ageMs < 0) return "just now";

  const mins = Math.round(ageMs / 60_000);
  if (mins < 60) return `${mins} ${mins === 1 ? "minute" : "minutes"} ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours} ${hours === 1 ? "hour" : "hours"} ago`;
  const days = Math.round(hours / 24);
  return `${days} ${days === 1 ? "day" : "days"} ago`;
}

export function partialGithubBanner(meta: ActivityMeta): string | null {
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
