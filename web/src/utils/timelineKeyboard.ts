import type { Activity, Event } from "@shared/types";
import {
  buildTimelineLanes,
  laneIdForEvent,
} from "./timelineLanes";

export interface TimelineFocusItem {
  eventId: string;
  laneId: string;
}

export function orderedTimelineFocusItems(
  activity: Activity,
  events: Event[],
): TimelineFocusItem[] {
  const nodeIds = new Set(activity.nodes.map((n) => n.id));
  const lanes = buildTimelineLanes(activity.nodes);
  const laneOrder = new Map(lanes.map((l, i) => [l.id, i]));

  const sorted = [...events].sort((a, b) => {
    const laneA = laneOrder.get(laneIdForEvent(a, nodeIds)) ?? 999;
    const laneB = laneOrder.get(laneIdForEvent(b, nodeIds)) ?? 999;
    if (laneA !== laneB) return laneA - laneB;
    return (
      new Date(a.source_time).getTime() - new Date(b.source_time).getTime()
    );
  });

  return sorted.map((e) => ({
    eventId: e.id,
    laneId: laneIdForEvent(e, nodeIds),
  }));
}

export function adjacentTimelineEventId(
  items: TimelineFocusItem[],
  currentId: string | null,
  direction: "prev" | "next",
): string | null {
  if (items.length === 0) return null;
  const idx = currentId
    ? items.findIndex((i) => i.eventId === currentId)
    : -1;
  const base = idx >= 0 ? idx : 0;
  const nextIdx =
    direction === "next"
      ? Math.min(items.length - 1, base + 1)
      : Math.max(0, base - 1);
  return items[nextIdx]?.eventId ?? null;
}

export function focusTimelineEventControl(eventId: string): void {
  document
    .querySelector<HTMLElement>(`[data-timeline-focus="${eventId}"]`)
    ?.focus();
}
