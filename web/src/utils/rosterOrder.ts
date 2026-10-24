import type { Node, Status } from "@shared/types";
import { providerLabel } from "./provider";

export type RosterGroupKey = "attention" | "working" | "settled";

export const ROSTER_GROUPS: ReadonlyArray<{ key: RosterGroupKey; label: string }> = [
  { key: "attention", label: "Needs attention" },
  { key: "working", label: "Working" },
  { key: "settled", label: "Done / idle / stale" },
];

export function rosterGroupOf(status: Status): RosterGroupKey {
  if (status === "FAILED" || status === "BLOCKED") return "attention";
  if (status === "IN_PROGRESS" || status === "IN_REVIEW") return "working";
  return "settled";
}

/** Case-insensitive match on provider / model / task / status text only. Empty query matches all. */
export function matchesRosterQuery(node: Node, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  const s = node.session;
  const hay = [
    providerLabel(s?.provider),
    s?.provider,
    s?.model,
    s?.account?.label,
    s?.account?.id,
    node.current_task,
    node.status,
    node.status.replace("_", " "),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return q.split(/\s+/).every((t) => hay.includes(t));
}

/** Groups by attention; inside a group order is by id so it never jumps on refresh. Empty groups are dropped. */
export function groupRoster(nodes: Node[], query: string) {
  const matched = nodes.filter((n) => matchesRosterQuery(n, query)).sort((a, b) => a.id.localeCompare(b.id));
  return ROSTER_GROUPS.map((g) => ({ ...g, nodes: matched.filter((n) => rosterGroupOf(n.status) === g.key) })).filter(
    (g) => g.nodes.length > 0,
  );
}

/** Honest relative update time; missing timestamps are stated, never invented. */
export function updatedLabel(iso: string | null | undefined, formatAgo: (iso: string) => string): string {
  return iso ? `updated ${formatAgo(iso)}` : "Update time not reported by T3";
}
