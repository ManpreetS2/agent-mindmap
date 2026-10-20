import type { Event } from "@shared/types";
import { plottableTimelineEvents } from "./eventTime";

const LA_TZ = "America/Los_Angeles";
const PAD_MS = 5 * 60 * 1000;

export function parseEventTime(iso: string): number {
  return new Date(iso).getTime();
}

export function formatAxisTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString("en-US", {
      timeZone: LA_TZ,
      hour: "numeric",
      minute: "2-digit",
      timeZoneName: "short",
    });
  } catch {
    return iso;
  }
}

export interface TimeScale {
  minMs: number;
  maxMs: number;
  toX: (ms: number) => number;
}

export function buildTimeScale(
  events: Event[],
  width: number,
  paddingPx = 24,
): TimeScale {
  const plottable = plottableTimelineEvents(events);
  const inner = Math.max(1, width - paddingPx * 2);
  if (plottable.length === 0) {
    const now = Date.now();
    return {
      minMs: now - 3600_000,
      maxMs: now,
      toX: () => paddingPx + inner / 2,
    };
  }
  let minMs = Infinity;
  let maxMs = -Infinity;
  for (const e of plottable) {
    const t = parseEventTime(e.source_time);
    minMs = Math.min(minMs, t);
    maxMs = Math.max(maxMs, t);
  }
  if (minMs === maxMs) {
    minMs -= PAD_MS;
    maxMs += PAD_MS;
  } else {
    minMs -= PAD_MS;
    maxMs += PAD_MS;
  }
  const span = maxMs - minMs;
  return {
    minMs,
    maxMs,
    toX: (ms: number) => paddingPx + ((ms - minMs) / span) * inner,
  };
}
