import type { Event, Node, Task } from "@shared/types";

function sortEventsNewestFirst(events: Event[]): Event[] {
  return [...events].sort(
    (a, b) =>
      new Date(b.source_time).getTime() - new Date(a.source_time).getTime(),
  );
}

export function lastEventForNode(
  nodeId: string,
  events: Event[],
): Event | undefined {
  const related = events.filter(
    (e) => e.actor === nodeId || e.target === nodeId,
  );
  return sortEventsNewestFirst(related)[0];
}

export function latestEventForTask(
  taskId: string,
  events: Event[],
  nodeId?: string,
): Event | undefined {
  let candidates = events.filter((e) => e.task_id === taskId);
  if (nodeId) {
    const forNode = candidates.filter(
      (e) => e.actor === nodeId || e.target === nodeId,
    );
    if (forNode.length > 0) {
      candidates = forNode;
    }
  }
  return sortEventsNewestFirst(candidates)[0];
}

/** Latest event tied to this node (by role or current task). */
export function latestEventForNodeContext(
  node: Node,
  events: Event[],
): Event | undefined {
  const byRole = lastEventForNode(node.id, events);
  if (byRole) return byRole;
  if (node.current_task) {
    return latestEventForTask(node.current_task, events, node.id);
  }
  return undefined;
}

export function eventMatchingNodeTimestamp(
  node: Node,
  events: Event[],
): Event | undefined {
  if (!node.last_activity_ts) return undefined;
  return events.find((e) => e.source_time === node.last_activity_ts);
}

export function taskForNode(node: Node, tasks: Task[]): Task | undefined {
  if (!node.current_task) return undefined;
  return tasks.find((t) => t.id === node.current_task);
}

export type FactSource =
  | { kind: "linked"; href: string }
  | { kind: "unsourced" };

export function resolveStatusSource(
  node: Node,
  tasks: Task[],
  events: Event[],
): FactSource {
  const task = taskForNode(node, tasks);
  if (task?.source_url) {
    return { kind: "linked", href: task.source_url };
  }
  const event = latestEventForNodeContext(node, events);
  if (event?.source_url) {
    return { kind: "linked", href: event.source_url };
  }
  return { kind: "unsourced" };
}

export function resolveCurrentTaskSource(
  node: Node,
  tasks: Task[],
  events: Event[],
): FactSource | null {
  if (!node.current_task) return null;
  const task = taskForNode(node, tasks);
  if (task?.source_url) {
    return { kind: "linked", href: task.source_url };
  }
  const event = latestEventForTask(node.current_task, events, node.id);
  if (event?.source_url) {
    return { kind: "linked", href: event.source_url };
  }
  return { kind: "unsourced" };
}

export type LastActivityPresentation =
  | { mode: "event"; event: Event }
  | { mode: "timestamp"; ts: string; source: FactSource }
  | { mode: "empty"; source: FactSource };

export function resolveLastActivity(
  node: Node,
  events: Event[],
): LastActivityPresentation {
  const byRole = lastEventForNode(node.id, events);
  if (byRole) {
    return { mode: "event", event: byRole };
  }

  const byTaskOrTime =
    latestEventForNodeContext(node, events) ??
    eventMatchingNodeTimestamp(node, events);

  if (node.last_activity_ts) {
    if (byTaskOrTime?.source_url) {
      return {
        mode: "timestamp",
        ts: node.last_activity_ts,
        source: { kind: "linked", href: byTaskOrTime.source_url },
      };
    }
    return {
      mode: "timestamp",
      ts: node.last_activity_ts,
      source: { kind: "unsourced" },
    };
  }

  if (byTaskOrTime) {
    return { mode: "event", event: byTaskOrTime };
  }

  return { mode: "empty", source: { kind: "unsourced" } };
}
