import type { Activity, Event, Node, Task } from "@shared/types";

export function taskForNode(node: Node, tasks: Task[]): Task | undefined {
  if (!node.current_task) return undefined;
  return tasks.find((t) => t.id === node.current_task);
}

export function lastEventForNode(nodeId: string, events: Event[]): Event | undefined {
  const related = events.filter(
    (e) => e.actor === nodeId || e.target === nodeId,
  );
  if (related.length === 0) return undefined;
  return related.sort(
    (a, b) => new Date(b.source_time).getTime() - new Date(a.source_time).getTime(),
  )[0];
}

export function tasksOwnedByLabel(label: string, tasks: Task[]): Task[] {
  return tasks.filter((t) => t.owner === label);
}

export function handoffEdgeCount(activity: Activity): number {
  return activity.edges
    .filter((e) => e.type === "handoff")
    .reduce((sum, e) => sum + e.count, 0);
}
