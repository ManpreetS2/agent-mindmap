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
  /** Empty = all repos allowed (MM-020k cross-project). */
  repos: Set<string>;
}

export const EMPTY_FILTERS: TimelineFilterState = {
  eventGroups: new Set(),
  botIds: new Set(),
  taskIds: new Set(),
  repos: new Set(),
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
    if (filters.repos.size > 0) {
      if (!event.repo || !filters.repos.has(event.repo)) return false;
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

/** Distinct owner/name repos present on events (MM-020k). */
export function uniqueRepos(events: Event[]): string[] {
  const ids = new Set<string>();
  for (const e of events) {
    if (typeof e.repo === "string" && e.repo.includes("/")) {
      ids.add(e.repo);
    }
  }
  return [...ids].sort();
}
