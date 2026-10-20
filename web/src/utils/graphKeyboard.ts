import type { Node } from "@shared/types";

export type GraphDirection = "up" | "down" | "left" | "right";

export function hierarchyNodeOrder(nodes: Node[]): Node[] {
  return [...nodes].sort(
    (a, b) => a.layout.y - b.layout.y || a.layout.x - b.layout.x,
  );
}

export function nearestNodeInDirection(
  nodes: Node[],
  currentId: string,
  direction: GraphDirection,
): string | null {
  const current = nodes.find((n) => n.id === currentId);
  if (!current) return null;
  const cx = current.layout.x;
  const cy = current.layout.y;

  let best: Node | null = null;
  let bestScore = Infinity;

  for (const n of nodes) {
    if (n.id === currentId) continue;
    const dx = n.layout.x - cx;
    const dy = n.layout.y - cy;
    if (direction === "left" && dx >= -1) continue;
    if (direction === "right" && dx <= 1) continue;
    if (direction === "up" && dy >= -1) continue;
    if (direction === "down" && dy <= 1) continue;
    const primary =
      direction === "left" || direction === "right" ? Math.abs(dx) : Math.abs(dy);
    const secondary =
      direction === "left" || direction === "right" ? Math.abs(dy) : Math.abs(dx);
    const score = primary * 1000 + secondary;
    if (score < bestScore) {
      bestScore = score;
      best = n;
    }
  }
  return best?.id ?? null;
}

export function focusGraphNodeButton(nodeId: string): void {
  document
    .querySelector<HTMLButtonElement>(`[data-testid="agent-node-${nodeId}"]`)
    ?.focus();
}

export function focusGraphNodeIdFromActiveElement(): string | null {
  const testId = document.activeElement?.getAttribute("data-testid");
  if (!testId?.startsWith("agent-node-")) return null;
  return testId.slice("agent-node-".length);
}
