import type { Event } from "@shared/types";

/** Matches ingest `UNDATED_SOURCE_TIME` (ledger_parser.py). */
export const UNDATED_SOURCE_TIME = "1970-01-01T00:00:00-08:00";

const UNDATED_ISO_PREFIXES = [
  UNDATED_SOURCE_TIME,
  "1970-01-01T00:00:00Z",
  "1970-01-01T00:00:00+00:00",
];

export function isUndatedSourceTime(iso: string): boolean {
  if (!iso) return true;
  if (UNDATED_ISO_PREFIXES.includes(iso)) return true;
  const ms = new Date(iso).getTime();
  if (Number.isNaN(ms)) return true;
  // Any timestamp on 1970-01-01 (ingest/github fallbacks).
  const d = new Date(ms);
  return d.getUTCFullYear() === 1970 && d.getUTCMonth() === 0 && d.getUTCDate() === 1;
}

export function isPlottableTimelineEvent(event: Event): boolean {
  if (event.type === "unparsed") return false;
  if (!event.source_time) return false;
  if (isUndatedSourceTime(event.source_time)) return false;
  const ms = new Date(event.source_time).getTime();
  return !Number.isNaN(ms);
}

export function plottableTimelineEvents(events: Event[]): Event[] {
  return events.filter(isPlottableTimelineEvent);
}

export function formatEventTimeLabel(iso: string): string | null {
  if (isUndatedSourceTime(iso)) return null;
  return iso;
}
