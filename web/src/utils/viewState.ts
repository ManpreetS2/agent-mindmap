import type { Activity, ActivityMeta } from "@shared/types";
import {
  asMindmapMeta,
  isGithubSourceHealthy,
  isLedgerSourceHealthy,
} from "./activityMeta";

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

export function partialGithubBanner(meta: ActivityMeta): string | null {
  const status = meta.github as string | undefined;
  if (isGithubSourceHealthy(status)) return null;
  if (status === "never_run") {
    return "GitHub (never run) — waiting for first poll.";
  }
  const sourceName =
    status === "skipped"
      ? "GitHub (skipped)"
      : status === "error"
        ? "GitHub (error)"
        : `GitHub (${status ?? "unknown"})`;
  return `${sourceName} — data may be incomplete. Retry refresh.`;
}

/** MM-020-P0: banner when ledger or GitHub is unhealthy (includes meta.ledger_error). */
export function sourceUnavailableMessage(meta: ActivityMeta): string | null {
  const extended = asMindmapMeta(meta);
  const ledger = extended.ledger as string | undefined;
  const github = extended.github as string | undefined;
  const ledgerBad = !isLedgerSourceHealthy(ledger);
  const githubBad = !isGithubSourceHealthy(github);
  if (!ledgerBad && !githubBad) return null;
  const parts = ["SOURCE UNAVAILABLE"];
  if (ledgerBad) {
    parts.push(`ledger: ${ledger ?? "unknown"}`);
  }
  if (githubBad) {
    parts.push(`GitHub: ${github ?? "unknown"}`);
  }
  const ledgerError = extended.ledger_error?.trim();
  if (ledgerError) {
    parts.push(ledgerError);
  }
  return parts.join(" — ");
}

export function refreshRateLimitMessage(retryAfterS: number): string {
  return `Refresh rate limited — try again in ${retryAfterS}s.`;
}

export const REFRESH_FORBIDDEN_MESSAGE =
  "Refresh denied (403) — check Host/Origin.";
