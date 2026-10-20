import type { Activity, Task } from "@shared/types";

export { taskForNode, lastEventForNode } from "./detailPanelFacts";

export function tasksOwnedByLabel(label: string, tasks: Task[]): Task[] {
  return tasks.filter((t) => t.owner === label);
}

export function handoffEdgeCount(activity: Activity): number {
  return activity.edges
    .filter((e) => e.type === "handoff")
    .reduce((sum, e) => sum + e.count, 0);
}
