import type { Activity, Edge, Event, Provenance } from "@shared/types";
import { EDGE_VISUALS } from "./edgeStyles";
import { isGroupTarget, labelForGroup, parseGroupTarget } from "./groupMembership";

/**
 * Read provenance for tooltips.
 * Schema 1.1.0 requires it on every event; legacy 1.0.0 wire/fixtures may omit
 * it until migrate fills values — tolerate absence only in that case.
 */
export function readEventProvenance(ev: Event): Provenance | undefined {
  const value = (ev as Event & { provenance?: Provenance }).provenance;
  return value;
}

function targetLabel(target: string): string {
  const gid = parseGroupTarget(target);
  if (gid) return `group:${labelForGroup(gid)}`;
  return target;
}

/** Build an accessible tooltip including provenance when present. */
export function tooltipForEdge(edge: Edge, events: Event[]): string {
  const visual = EDGE_VISUALS[edge.type];
  const byId = new Map(events.map((e) => [e.id, e]));
  const provenances = new Set<string>();
  for (const id of edge.event_ids) {
    const ev = byId.get(id);
    if (!ev) continue;
    const p = readEventProvenance(ev);
    if (p) provenances.add(p);
  }
  const base = `${visual.label}: ${edge.source} → ${targetLabel(edge.target)} (${edge.count})`;
  if (provenances.size === 0) return base;
  return `${base} · provenance: ${[...provenances].join(", ")}`;
}

export function edgeTouchesVisibleAgents(
  edge: Edge,
  visibleAgentIds: ReadonlySet<string>,
  visibleGroupIds: ReadonlySet<string> | null,
): boolean {
  if (isGroupTarget(edge.target)) {
    const gid = parseGroupTarget(edge.target);
    if (gid && visibleGroupIds && !visibleGroupIds.has(gid)) return false;
    return visibleAgentIds.has(edge.source);
  }
  return visibleAgentIds.has(edge.source) && visibleAgentIds.has(edge.target);
}

export function activityHasMessageEdges(activity: Activity): boolean {
  return activity.edges.some((e) => e.type === "message");
}
