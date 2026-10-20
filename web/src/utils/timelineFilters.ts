import type { Event, EventType } from "@shared/types";
import { laneIdForEvent } from "./timelineLanes";

export type EventTypeGroup =
  | "handoffs"
  | "verdicts"
  | "prs"
  | "merged"
  | "blockers"
  | "notes"
  | "ci"
  | "unparsed";

export const EVENT_GROUP_TYPES: Record<EventTypeGroup, EventType[]> = {
  handoffs: ["assigned", "handoff"],
  verdicts: ["verdict"],
  prs: ["pr_opened", "pr_updated"],
  merged: ["merged"],
  blockers: ["blocker"],
  notes: ["note"],
  ci: ["ci"],
  unparsed: ["unparsed"],
};

export interface TimelineFilterState {
  /** Empty = all groups allowed. */
  eventGroups: Set<EventTypeGroup>;
  botIds: Set<string>;
  taskIds: Set<string>;
}

export const EMPTY_FILTERS: TimelineFilterState = {
  eventGroups: new Set(),
  botIds: new Set(),
  taskIds: new Set(),
};

export function eventMatchesTypeGroups(
  event: Event,
  groups: Set<EventTypeGroup>,
): boolean {
  if (groups.size === 0) return true;
  for (const group of groups) {
    if (EVENT_GROUP_TYPES[group].includes(event.type)) return true;
  }
  return false;
}

export function filterTimelineEvents(
  events: Event[],
  filters: TimelineFilterState,
  nodeIds: ReadonlySet<string>,
): Event[] {
  return events.filter((event) => {
    if (!eventMatchesTypeGroups(event, filters.eventGroups)) return false;
    if (filters.botIds.size > 0) {
      const lane = laneIdForEvent(event, nodeIds);
      if (!filters.botIds.has(lane)) return false;
    }
    if (filters.taskIds.size > 0) {
      if (!event.task_id || !filters.taskIds.has(event.task_id)) return false;
    }
    return true;
  });
}

export function uniqueTaskIds(events: Event[]): string[] {
  const ids = new Set<string>();
  for (const e of events) {
    if (e.task_id && /^(RP|MM)-/.test(e.task_id)) {
      ids.add(e.task_id);
    }
  }
  return [...ids].sort();
}
