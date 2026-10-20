import type { Node as FlowNode } from "@xyflow/react";

export type AgentStructureKey = string;

/** Stable structural fingerprint for an agent node (id + membership). */
export function agentStructureKey(node: FlowNode): AgentStructureKey {
  const data = node.data as {
    node?: { group?: string; groups?: string[] };
  };
  const group = data.node?.group ?? "";
  const groups = (data.node?.groups ?? []).slice().sort().join(",");
  return `${node.id}|${group}|${groups}`;
}

/**
 * Merge layout-built nodes with the live React Flow node list.
 *
 * - Group anchors always take the new layout position.
 * - User-dragged agent positions are always kept.
 * - Existing agents keep their session position unless structurally changed
 *   (new membership / home group) and not user-dragged.
 * - Brand-new agent ids take the layout position.
 *
 * Never treats a user drag as a full layout reset (QA-MM020f-1).
 */
export function mergeFlowNodes(
  prev: FlowNode[],
  built: FlowNode[],
  draggedIds: ReadonlySet<string>,
): FlowNode[] {
  const prevById = new Map(prev.map((n) => [n.id, n]));
  const prevStructure = new Map(
    prev
      .filter((n) => n.type !== "groupAnchor")
      .map((n) => [n.id, agentStructureKey(n)]),
  );

  return built.map((n) => {
    if (n.type === "groupAnchor") return n;

    const existing = prevById.get(n.id);
    if (!existing) return n;

    if (draggedIds.has(n.id)) {
      return { ...n, position: existing.position };
    }

    const was = prevStructure.get(n.id);
    const now = agentStructureKey(n);
    if (was !== undefined && was === now) {
      // Same structure — keep session position across poll/layout rebuilds.
      return { ...n, position: existing.position };
    }

    // Structurally changed (e.g. home group / membership) → re-layout.
    return n;
  });
}

/** Record agent ids that the user has repositioned via drag. */
export function collectDraggedIds(
  changes: Array<{ type: string; id?: string; dragging?: boolean }>,
  previous: ReadonlySet<string>,
): Set<string> {
  const next = new Set(previous);
  for (const c of changes) {
    if (c.type !== "position" || !c.id) continue;
    // Mark while dragging and when the drag ends.
    if (c.dragging === true || c.dragging === false) {
      next.add(c.id);
    }
  }
  return next;
}
