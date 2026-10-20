/**
 * MM-020k / QA-MM020g-3: persist user-dragged node positions across reload.
 */

export const DRAG_POSITIONS_KEY = "mindmap:drag-positions:v1";

export type DragPositionMap = Record<string, { x: number; y: number }>;

export function loadDragPositions(
  storage: Pick<Storage, "getItem"> | null = typeof localStorage !== "undefined"
    ? localStorage
    : null,
): DragPositionMap {
  if (!storage) return {};
  try {
    const raw = storage.getItem(DRAG_POSITIONS_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== "object") return {};
    const out: DragPositionMap = {};
    for (const [id, pos] of Object.entries(parsed as Record<string, unknown>)) {
      if (!id || typeof pos !== "object" || pos === null) continue;
      const x = (pos as { x?: unknown }).x;
      const y = (pos as { y?: unknown }).y;
      if (typeof x === "number" && typeof y === "number" && Number.isFinite(x) && Number.isFinite(y)) {
        out[id] = { x, y };
      }
    }
    return out;
  } catch {
    return {};
  }
}

export function saveDragPositions(
  positions: DragPositionMap,
  storage: Pick<Storage, "setItem"> | null = typeof localStorage !== "undefined"
    ? localStorage
    : null,
): void {
  if (!storage) return;
  try {
    storage.setItem(DRAG_POSITIONS_KEY, JSON.stringify(positions));
  } catch {
    // Quota / private mode — ignore; in-session drag still works.
  }
}

/** Merge persisted coords into a React Flow node list (agents only). */
export function applyDragPositions<T extends { id: string; type?: string; position: { x: number; y: number } }>(
  nodes: T[],
  positions: DragPositionMap,
): T[] {
  if (!positions || Object.keys(positions).length === 0) return nodes;
  return nodes.map((n) => {
    if (n.type === "groupAnchor") return n;
    const p = positions[n.id];
    if (!p) return n;
    return { ...n, position: { x: p.x, y: p.y } };
  });
}
