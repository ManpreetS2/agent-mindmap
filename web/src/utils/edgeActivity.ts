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

export type EdgeObservation = "new-delegation" | "newly-observed";
// One second is <= two polls even at the transport's minimum 1 s interval.
export const EVIDENCE_TOLERANCE_MS = 1000;

/** Conservatively treat any stale session as a gap in snapshot observation. */
export function snapshotConnected(activity: Activity): boolean {
  return activity.meta.t3?.connection === "connected"
    && Number.isFinite(Date.parse(activity.generated_at))
    && !activity.nodes.some(n => n.status === "STALE" || n.session?.stale);
}

export function continuousObservation(previous: Activity | null, current: Activity): boolean {
  if (!previous || sourceKey(previous) !== sourceKey(current)
    || !snapshotConnected(previous) || !snapshotConnected(current)) return false;
  const elapsed = Date.parse(current.generated_at) - Date.parse(previous.generated_at);
  // A missed/stalled producer must not turn cached history into fresh work.
  return elapsed >= 0 && elapsed <= Math.min(previous.meta.t3!.stale_after_sec, current.meta.t3!.stale_after_sec) * 1000;
}

export function edgeObservation(edge: Edge, current: Activity, previous: Activity | null): EdgeObservation {
  if (continuousObservation(previous, current)) {
    const cited = new Set(edge.event_ids);
    const earliest = Date.parse(previous!.generated_at) - EVIDENCE_TOLERANCE_MS;
    const latest = Date.parse(current.generated_at) + EVIDENCE_TOLERANCE_MS;
    // The cited event must actually describe this parent/child relationship.
    const evidence = current.events.filter(e => cited.has(e.id) && e.actor === edge.source && e.target === edge.target);
    if (evidence.some(e => Date.parse(e.source_time) >= earliest && Date.parse(e.source_time) <= latest)) return "new-delegation";
  }
  return "newly-observed";
}
