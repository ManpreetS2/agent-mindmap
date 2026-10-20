import type { Activity, Event } from "@shared/types";

const TASK_ID_PATTERN = /^(RP|MM)-[0-9]{3}/;

export function isLifecycleTaskId(id: string): boolean {
  return TASK_ID_PATTERN.test(id);
}

export function eventsForTask(activity: Activity, taskId: string): Event[] {
  const all = [...activity.events, ...activity.unparsed];
  return all.filter((e) => e.task_id === taskId);
}

export function nodeIdsForTaskLifecycle(
  activity: Activity,
  taskId: string,
): Set<string> {
  const ids = new Set<string>();
  for (const e of eventsForTask(activity, taskId)) {
    if (e.actor) ids.add(e.actor);
    if (e.target) ids.add(e.target);
  }
  for (const n of activity.nodes) {
    if (n.current_task === taskId) ids.add(n.id);
  }
  return ids;
}

export function edgeIdsForTaskLifecycle(
  activity: Activity,
  taskId: string,
): Set<string> {
  const eventIds = new Set(eventsForTask(activity, taskId).map((e) => e.id));
  const edgeIds = new Set<string>();
  for (const edge of activity.edges) {
    if (edge.event_ids.some((id) => eventIds.has(id))) {
      edgeIds.add(edge.id);
    }
  }
  return edgeIds;
}

export function eventIdsForTaskLifecycle(
  activity: Activity,
  taskId: string,
): Set<string> {
  return new Set(eventsForTask(activity, taskId).map((e) => e.id));
}
