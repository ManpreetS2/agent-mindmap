import type { Activity, Event, Node } from "@shared/types";

export const UNKNOWN_LANE_ID = "unknown";

export interface TimelineLane {
  id: string;
  label: string;
}

export function buildTimelineLanes(nodes: Node[]): TimelineLane[] {
  const lanes: TimelineLane[] = nodes.map((n) => ({ id: n.id, label: n.label }));
  lanes.push({ id: UNKNOWN_LANE_ID, label: "unknown" });
  return lanes;
}

export function laneIdForEvent(
  event: Event,
  nodeIds: ReadonlySet<string>,
): string {
  if (event.attribution.method === "unknown") {
    return UNKNOWN_LANE_ID;
  }
  if (event.actor && nodeIds.has(event.actor)) {
    return event.actor;
  }
  if (event.target && nodeIds.has(event.target)) {
    return event.target;
  }
  return UNKNOWN_LANE_ID;
}

export function allTimelineEvents(activity: Activity): Event[] {
  return [...activity.events, ...activity.unparsed];
}
