import type { Activity, Edge } from "@shared/types";

/** How long a newly observed verified relationship keeps its one-shot highlight. */
export const FRESH_EDGE_MS = 6000;

/** Identity of the data source; a change means "start a new baseline", never "new events". */
export function sourceKey(activity: Activity): string {
  const t3 = activity.meta.t3;
  if (!t3) return "legacy";
  return `${t3.source}|${t3.mode}|${t3.replay ? "replay" : "plain"}`;
}

/** An edge is verified when it cites at least one event present in the snapshot. */
export function isEvidenced(edge: Edge, activity: Activity): boolean {
  if (edge.event_ids.length === 0) return false;
  const ids = new Set(activity.events.map((e) => e.id));
  return edge.event_ids.some((id) => ids.has(id));
}

/**
 * Edges first observed in this snapshot. `seen === null` is the baseline load (nothing is
 * "new"), so historical relationships are never animated on page load or source switch.
 */
export function newlyObservedEdgeIds(
  seen: ReadonlySet<string> | null,
  activity: Activity,
): Set<string> {
  const fresh = new Set<string>();
  if (seen === null) return fresh;
  for (const e of activity.edges) {
    if (e.type === "delegation" && !seen.has(e.id) && isEvidenced(e, activity)) {
      fresh.add(e.id);
    }
  }
  return fresh;
}
