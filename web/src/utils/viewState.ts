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
  const mins = Math.round((nowMs - new Date(generatedAt).getTime()) / 60_000);
  if (mins < 60) return `${mins} minutes ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours} hours ago`;
  return `${Math.round(hours / 24)} days ago`;
}

/** MM-020k: banner from real GitHub poller state (ok / skipped / error / never_run). */
export function partialGithubBanner(meta: ActivityMeta): string | null {
  const status = meta.github as string;
  if (status === "ok") return null;
  if (status === "never_run") {
    return "GitHub (never run) — waiting for first poll.";
  }
  const sourceName =
    status === "rate_limited"
      ? "GitHub (rate limited)"
      : status === "skipped"
        ? "GitHub (skipped)"
        : "GitHub (error)";
  return `${sourceName} — GitHub data incomplete. Retry refresh.`;
}

/** MM-020k: honest ledger unavailable when data/ledger is missing. */
export function ledgerStatusBanner(meta: ActivityMeta): string | null {
  const status = meta.ledger as string | undefined;
  if (!status || status === "ok" || status === "skipped" || status === "demo") {
    return null;
  }
  if (status === "unavailable") {
    return "Ledger unavailable — data/ledger mirror missing or unreadable.";
  }
  return "Ledger (error) — could not load task ledger.";
}
