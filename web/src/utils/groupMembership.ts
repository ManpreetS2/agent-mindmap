import type { GroupId, Node, NodeGroup } from "@shared/types";

/** Display labels for known groups; unknown ids title-case the id. */
export const GROUP_LABELS: Record<string, string> = {
  owner: "Owner",
  build: "Build",
  qr: "Quality & Release",
  radar: "Research / Radar",
};

export const GROUP_LAYOUT_ORDER: string[] = [
  "owner",
  "build",
  "qr",
  "radar",
];

/** Membership list for a node (schema 1.1.0 `groups`, else primary `group`). */
export function groupsForNode(node: Node): GroupId[] {
  if (node.groups && node.groups.length > 0) {
    return [...node.groups];
  }
  return [node.group];
}

export function homeGroupForNode(node: Node): GroupId {
  return node.group;
}

export function labelForGroup(id: string): string {
  return GROUP_LABELS[id] ?? id.replace(/[-_]/g, " ");
}

export function parseGroupTarget(target: string): string | null {
  if (!target.startsWith("group:")) return null;
  const id = target.slice("group:".length);
  return id || null;
}

export function groupTargetId(groupId: string): string {
  return `group:${groupId}`;
}

export function isGroupTarget(id: string): boolean {
  return id.startsWith("group:");
}

/** Unique group ids present in the activity roster, stable order. */
export function collectGroupIds(nodes: Node[]): string[] {
  const seen = new Set<string>();
  for (const n of nodes) {
    for (const g of groupsForNode(n)) {
      seen.add(String(g));
    }
  }
  const ordered = GROUP_LAYOUT_ORDER.filter((g) => seen.has(g));
  const rest = [...seen].filter((g) => !GROUP_LAYOUT_ORDER.includes(g)).sort();
  return [...ordered, ...rest];
}

export function nodeInSelectedGroups(
  node: Node,
  selected: ReadonlySet<string> | null,
): boolean {
  if (!selected || selected.size === 0) return true;
  return groupsForNode(node).some((g) => selected.has(String(g)));
}

export function isKnownNodeGroup(id: string): id is NodeGroup {
  return id === "owner" || id === "build" || id === "qr" || id === "radar";
}
