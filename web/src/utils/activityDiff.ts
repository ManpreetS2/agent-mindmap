import type { Activity, Edge, Event, Node, Task } from "@shared/types";

export interface ActivityPatch {
  activity: Activity;
  changedNodeIds: Set<string>;
  changedEventIds: Set<string>;
  changedEdgeIds: Set<string>;
  changedTaskIds: Set<string>;
  metaChanged: boolean;
  generatedAtChanged: boolean;
}

function byId<T extends { id: string }>(items: T[]): Map<string, T> {
  return new Map(items.map((item) => [item.id, item]));
}

function stableJson(value: unknown): string {
  return JSON.stringify(value);
}

function mergeById<T extends { id: string }>(
  prev: T[],
  next: T[],
): { items: T[]; changedIds: Set<string> } {
  const prevMap = byId(prev);
  const nextMap = byId(next);
  const changedIds = new Set<string>();
  const items: T[] = [];

  for (const item of next) {
    const prior = prevMap.get(item.id);
    if (!prior || stableJson(prior) !== stableJson(item)) {
      changedIds.add(item.id);
    }
    items.push(prior && stableJson(prior) === stableJson(item) ? prior : item);
  }
  for (const id of prevMap.keys()) {
    if (!nextMap.has(id)) {
      changedIds.add(id);
    }
  }
  return { items: changedIds.size === 0 ? prev : items, changedIds };
}

/** Patch activity collections by id so unchanged entities keep identity. */
export function patchActivity(
  previous: Activity | null,
  next: Activity,
): ActivityPatch {
  if (!previous) {
    return {
      activity: next,
      changedNodeIds: new Set(next.nodes.map((n) => n.id)),
      changedEventIds: new Set(next.events.map((e) => e.id)),
      changedEdgeIds: new Set(next.edges.map((e) => e.id)),
      changedTaskIds: new Set(next.tasks.map((t) => t.id)),
      metaChanged: true,
      generatedAtChanged: true,
    };
  }

  const nodes = mergeById<Node>(previous.nodes, next.nodes);
  const events = mergeById<Event>(previous.events, next.events);
  const edges = mergeById<Edge>(previous.edges, next.edges);
  const tasks = mergeById<Task>(previous.tasks, next.tasks);
  const unparsed = mergeById<Event>(previous.unparsed, next.unparsed);

  const activity: Activity = {
    ...next,
    nodes: nodes.items,
    events: events.items,
    edges: edges.items,
    tasks: tasks.items,
    unparsed: unparsed.items,
  };

  return {
    activity,
    changedNodeIds: nodes.changedIds,
    changedEventIds: new Set([...events.changedIds, ...unparsed.changedIds]),
    changedEdgeIds: edges.changedIds,
    changedTaskIds: tasks.changedIds,
    metaChanged: stableJson(previous.meta) !== stableJson(next.meta),
    generatedAtChanged: previous.generated_at !== next.generated_at,
  };
}

export function statusChangedNodeIds(
  previous: Activity | null,
  next: Activity,
): Set<string> {
  if (!previous) return new Set(next.nodes.map((n) => n.id));
  const prevMap = byId(previous.nodes);
  const changed = new Set<string>();
  for (const node of next.nodes) {
    const prior = prevMap.get(node.id);
    if (!prior || prior.status !== node.status) {
      changed.add(node.id);
    }
  }
  return changed;
}

