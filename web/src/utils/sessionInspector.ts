import type { Activity, Edge, Event, Node } from "@shared/types";

export interface Relationship {
  edge: Edge;
  direction: "parent" | "child";
  other: Node | null;
  /** Events cited by the edge that exist in the snapshot. */
  evidence: Event[];
}

export function relationshipsFor(node: Node, activity: Activity): Relationship[] {
  const events = new Map(activity.events.map((e) => [e.id, e]));
  const byId = new Map(activity.nodes.map((n) => [n.id, n]));
  const out: Relationship[] = [];
  for (const edge of activity.edges) {
    if (edge.source !== node.id && edge.target !== node.id) continue;
    const isChild = edge.target === node.id;
    out.push({
      edge,
      direction: isChild ? "parent" : "child",
      other: byId.get(isChild ? edge.source : edge.target) ?? null,
      evidence: edge.event_ids
        .map((id) => events.get(id))
        .filter((e): e is Event => Boolean(e)),
    });
  }
  return out.sort((a, b) => a.edge.id.localeCompare(b.edge.id));
}

/** Observed events that involve this node, newest first. */
export function chronologyFor(node: Node, activity: Activity): Event[] {
  return activity.events
    .filter((e) => e.actor === node.id || e.target === node.id)
    .sort(
      (a, b) =>
        new Date(b.source_time).getTime() - new Date(a.source_time).getTime() ||
        a.id.localeCompare(b.id),
    );
}

export type Freshness =
  | { kind: "unavailable" }
  | { kind: "stale" }
  | { kind: "unknown" }
  | { kind: "ok" };

/** Honest freshness state: connection loss and stale flags are explicit, never hidden. */
export function freshnessOf(node: Node, activity: Activity): Freshness {
  if (activity.meta.t3?.connection === "unavailable") return { kind: "unavailable" };
  if (node.session?.stale || node.status === "STALE") return { kind: "stale" };
  if (node.status === "UNKNOWN") return { kind: "unknown" };
  return { kind: "ok" };
}
