import dagre from "@dagrejs/dagre";
import type { Edge, Node, NodeGroup } from "@shared/types";
import { NODE_HEIGHT, NODE_WIDTH } from "./groupFrames";

/** Minimum clear gap between node bounding boxes (px). */
export const MIN_NODE_GAP = 24;

export interface NodeRect {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

/** Card height used for layout (matches rendered agent-node-card + padding). */
export const LAYOUT_NODE_HEIGHT = Math.max(NODE_HEIGHT, 96);
export const LAYOUT_NODE_WIDTH = NODE_WIDTH;

const CELL_W = LAYOUT_NODE_WIDTH + MIN_NODE_GAP;
const CELL_H = LAYOUT_NODE_HEIGHT + MIN_NODE_GAP;

/**
 * Stable group-band grid (gap ≥ 24px). Owner → build grid → QR column → radar row.
 * Falls back to dagre for unexpected rosters.
 */
export function layoutNodesWithDagre(
  nodes: Node[],
  edges: Edge[],
): Map<string, { x: number; y: number }> {
  if (nodes.length === 0) return new Map();
  const known = new Set(["owner", "build", "qr", "radar"]);
  if (nodes.every((n) => known.has(n.group))) {
    return enforceMinGap(layoutByGroupBands(nodes), nodes);
  }
  return layoutWithDagreEngine(nodes, edges);
}

function sortMembers(members: Node[]): Node[] {
  return [...members].sort(
    (a, b) => a.layout.x - b.layout.x || a.layout.y - b.layout.y,
  );
}

function layoutByGroupBands(
  nodes: Node[],
): Map<string, { x: number; y: number }> {
  const byGroup = new Map<NodeGroup, Node[]>();
  for (const n of nodes) {
    const list = byGroup.get(n.group) ?? [];
    list.push(n);
    byGroup.set(n.group, list);
  }

  const positions = new Map<string, { x: number; y: number }>();
  const originX = 16;
  let y = 16;

  const owner = sortMembers(byGroup.get("owner") ?? []);
  for (let i = 0; i < owner.length; i++) {
    positions.set(owner[i].id, { x: originX, y: y + i * CELL_H });
  }
  if (owner.length) y += owner.length * CELL_H + MIN_NODE_GAP;

  const buildY = y;
  const build = sortMembers(byGroup.get("build") ?? []);
  const buildCols = Math.min(4, Math.max(1, build.length));
  for (let i = 0; i < build.length; i++) {
    const col = i % buildCols;
    const row = Math.floor(i / buildCols);
    positions.set(build[i].id, {
      x: originX + col * CELL_W,
      y: buildY + row * CELL_H,
    });
  }
  const buildRows = build.length ? Math.ceil(build.length / buildCols) : 0;
  const buildBottom = buildY + buildRows * CELL_H;

  const qr = sortMembers(byGroup.get("qr") ?? []);
  const qrX = originX + buildCols * CELL_W + MIN_NODE_GAP;
  for (let i = 0; i < qr.length; i++) {
    positions.set(qr[i].id, { x: qrX, y: buildY + i * CELL_H });
  }
  const qrBottom = buildY + qr.length * CELL_H;

  y = Math.max(buildBottom, qrBottom) + MIN_NODE_GAP;

  const radar = sortMembers(byGroup.get("radar") ?? []);
  for (let i = 0; i < radar.length; i++) {
    positions.set(radar[i].id, { x: originX + i * CELL_W, y });
  }

  return positions;
}

function layoutWithDagreEngine(
  nodes: Node[],
  edges: Edge[],
): Map<string, { x: number; y: number }> {
  const g = new dagre.graphlib.Graph({ compound: false, directed: true });
  g.setGraph({
    rankdir: "TB",
    nodesep: MIN_NODE_GAP,
    ranksep: MIN_NODE_GAP,
    edgesep: MIN_NODE_GAP,
    marginx: 16,
    marginy: 16,
  });
  g.setDefaultEdgeLabel(() => ({}));

  for (const n of nodes) {
    g.setNode(n.id, {
      width: LAYOUT_NODE_WIDTH,
      height: LAYOUT_NODE_HEIGHT,
    });
  }

  for (const e of edges) {
    if (g.hasNode(e.source) && g.hasNode(e.target) && e.source !== e.target) {
      g.setEdge(e.source, e.target, { weight: 1 });
    }
  }

  dagre.layout(g);

  const positions = new Map<string, { x: number; y: number }>();
  for (const n of nodes) {
    const laid = g.node(n.id);
    if (!laid) {
      positions.set(n.id, { x: n.layout.x, y: n.layout.y });
      continue;
    }
    positions.set(n.id, {
      x: laid.x - LAYOUT_NODE_WIDTH / 2,
      y: laid.y - LAYOUT_NODE_HEIGHT / 2,
    });
  }
  return enforceMinGap(positions, nodes);
}

/** Expand positions so axis-aligned boxes keep {@link MIN_NODE_GAP}. */
export function enforceMinGap(
  positions: Map<string, { x: number; y: number }>,
  nodes: Node[],
): Map<string, { x: number; y: number }> {
  const rects: NodeRect[] = nodes.map((n) => {
    const p = positions.get(n.id) ?? n.layout;
    return {
      id: n.id,
      x: p.x,
      y: p.y,
      width: LAYOUT_NODE_WIDTH,
      height: LAYOUT_NODE_HEIGHT,
    };
  });

  for (let pass = 0; pass < 12; pass++) {
    let moved = false;
    for (let i = 0; i < rects.length; i++) {
      for (let j = i + 1; j < rects.length; j++) {
        const a = rects[i];
        const b = rects[j];
        const gapX = separationGap(a.x, a.width, b.x, b.width);
        const gapY = separationGap(a.y, a.height, b.y, b.height);
        if (gapX >= MIN_NODE_GAP || gapY >= MIN_NODE_GAP) continue;
        const needX = MIN_NODE_GAP - gapX;
        const needY = MIN_NODE_GAP - gapY;
        if (needX <= needY) {
          const dir = a.x + a.width / 2 <= b.x + b.width / 2 ? -1 : 1;
          a.x += (dir * needX) / 2;
          b.x -= (dir * needX) / 2;
        } else {
          const dir = a.y + a.height / 2 <= b.y + b.height / 2 ? -1 : 1;
          a.y += (dir * needY) / 2;
          b.y -= (dir * needY) / 2;
        }
        moved = true;
      }
    }
    if (!moved) break;
  }

  const out = new Map<string, { x: number; y: number }>();
  for (const r of rects) {
    out.set(r.id, { x: r.x, y: r.y });
  }
  return out;
}

function separationGap(
  a0: number,
  aSize: number,
  b0: number,
  bSize: number,
): number {
  const a1 = a0 + aSize;
  const b1 = b0 + bSize;
  if (a1 <= b0) return b0 - a1;
  if (b1 <= a0) return a0 - b1;
  return -Math.min(a1 - b0, b1 - a0);
}

export function nodeRectsFromPositions(
  nodes: Node[],
  positions: Map<string, { x: number; y: number }>,
): NodeRect[] {
  return nodes.map((n) => {
    const p = positions.get(n.id) ?? n.layout;
    return {
      id: n.id,
      x: p.x,
      y: p.y,
      width: LAYOUT_NODE_WIDTH,
      height: LAYOUT_NODE_HEIGHT,
    };
  });
}

export function findOverlappingPairs(
  rects: NodeRect[],
  minGap = MIN_NODE_GAP,
): Array<[string, string]> {
  const pairs: Array<[string, string]> = [];
  for (let i = 0; i < rects.length; i++) {
    for (let j = i + 1; j < rects.length; j++) {
      const a = rects[i];
      const b = rects[j];
      const gapX = separationGap(a.x, a.width, b.x, b.width);
      const gapY = separationGap(a.y, a.height, b.y, b.height);
      if (gapX < minGap && gapY < minGap) {
        pairs.push([a.id, b.id]);
      }
    }
  }
  return pairs;
}

export function applyLayoutPositions(
  nodes: Node[],
  positions: Map<string, { x: number; y: number }>,
): Node[] {
  return nodes.map((n) => {
    const p = positions.get(n.id);
    if (!p) return n;
    return { ...n, layout: { x: p.x, y: p.y } };
  });
}
