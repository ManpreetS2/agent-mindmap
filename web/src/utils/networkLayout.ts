import dagre from "@dagrejs/dagre";
import type { Edge, Node } from "@shared/types";
import { findOverlappingPairs, type NodeRect } from "./graphLayout";

/** Rendered size of a compact session node (kept in sync with graph.css). */
export const NETWORK_NODE_WIDTH = 236;
export const NETWORK_NODE_HEIGHT = 96;

const RANK_SEP = 96;
const NODE_SEP = 28;
const COMPONENT_GAP = 56;
const MAX_ROW_WIDTH = 1440;
const ISOLATED_GAP = 24;

export type Positions = Map<string, { x: number; y: number }>;

interface Block {
  key: string;
  width: number;
  height: number;
  /** Positions relative to the block origin. */
  local: Positions;
}

function byProjectThenId(a: Node, b: Node): number {
  const pa = a.session?.project ?? "";
  const pb = b.session?.project ?? "";
  return pa.localeCompare(pb) || a.id.localeCompare(b.id);
}

/** Topology signature: relayout is needed only when this changes, not on status polls. */
export function topologyKey(nodes: Node[], edges: Edge[]): string {
  const n = nodes
    .map((x) => `${x.id}:${x.session?.project ?? ""}`)
    .sort()
    .join(",");
  const e = edges
    .map((x) => `${x.source}>${x.target}`)
    .sort()
    .join(",");
  return `${n}|${e}`;
}

function components(nodes: Node[], edges: Edge[]): Node[][] {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const parent = new Map<string, string>();
  const find = (x: string): string => {
    let r = x;
    while (parent.get(r) !== r) r = parent.get(r)!;
    parent.set(x, r);
    return r;
  };
  for (const n of nodes) parent.set(n.id, n.id);
  for (const e of edges) {
    if (!byId.has(e.source) || !byId.has(e.target) || e.source === e.target) continue;
    const a = find(e.source);
    const b = find(e.target);
    if (a !== b) parent.set(a < b ? b : a, a < b ? a : b);
  }
  const groups = new Map<string, Node[]>();
  for (const n of nodes) {
    const root = find(n.id);
    groups.set(root, [...(groups.get(root) ?? []), n]);
  }
  return [...groups.values()];
}

function layoutComponent(members: Node[], edges: Edge[]): Block {
  const ids = new Set(members.map((m) => m.id));
  const g = new dagre.graphlib.Graph({ directed: true });
  g.setGraph({
    rankdir: "LR",
    ranker: "network-simplex",
    nodesep: NODE_SEP,
    ranksep: RANK_SEP,
    marginx: 0,
    marginy: 0,
  });
  g.setDefaultEdgeLabel(() => ({}));
  const sorted = [...members].sort(byProjectThenId);
  for (const n of sorted) {
    g.setNode(n.id, { width: NETWORK_NODE_WIDTH, height: NETWORK_NODE_HEIGHT });
  }
  const own = edges
    .filter((e) => ids.has(e.source) && ids.has(e.target) && e.source !== e.target)
    .sort((a, b) => a.id.localeCompare(b.id));
  for (const e of own) g.setEdge(e.source, e.target);
  dagre.layout(g);

  const local: Positions = new Map();
  let maxX = 0;
  let maxY = 0;
  for (const n of sorted) {
    const p = g.node(n.id);
    const x = p.x - NETWORK_NODE_WIDTH / 2;
    const y = p.y - NETWORK_NODE_HEIGHT / 2;
    local.set(n.id, { x, y });
    maxX = Math.max(maxX, x + NETWORK_NODE_WIDTH);
    maxY = Math.max(maxY, y + NETWORK_NODE_HEIGHT);
  }
  return {
    key: sorted[0].id,
    width: maxX,
    height: maxY,
    local,
  };
}

function layoutIsolated(members: Node[]): Block {
  const sorted = [...members].sort(byProjectThenId);
  const cols = Math.min(4, Math.max(1, Math.ceil(Math.sqrt(sorted.length * 1.5))));
  const local: Positions = new Map();
  sorted.forEach((n, i) => {
    local.set(n.id, {
      x: (i % cols) * (NETWORK_NODE_WIDTH + ISOLATED_GAP),
      y: Math.floor(i / cols) * (NETWORK_NODE_HEIGHT + ISOLATED_GAP),
    });
  });
  const rows = Math.ceil(sorted.length / cols);
  return {
    key: "~isolated",
    width: cols * NETWORK_NODE_WIDTH + (cols - 1) * ISOLATED_GAP,
    height: rows * NETWORK_NODE_HEIGHT + (rows - 1) * ISOLATED_GAP,
    local,
  };
}

/**
 * Deterministic, edge-aware network layout.
 *
 * Delegation trees are laid out left→right by Dagre (parents left of children, crossing
 * minimised). Each connected component is then shelf-packed so unrelated trees do not form
 * one very wide strip, and sessions with no verified relationship are gathered into a compact
 * block grouped by project. Output depends only on node ids, projects and edges.
 */
export function computeNetworkLayout(nodes: Node[], edges: Edge[]): Positions {
  const out: Positions = new Map();
  if (nodes.length === 0) return out;

  const linked = new Set<string>();
  const ids = new Set(nodes.map((n) => n.id));
  const usable = edges.filter(
    (e) => ids.has(e.source) && ids.has(e.target) && e.source !== e.target,
  );
  for (const e of usable) {
    linked.add(e.source);
    linked.add(e.target);
  }

  const blocks: Block[] = components(
    nodes.filter((n) => linked.has(n.id)),
    usable,
  )
    .map((c) => layoutComponent(c, usable))
    .sort(
      (a, b) =>
        b.local.size - a.local.size || a.key.localeCompare(b.key),
    );
  const loose = nodes.filter((n) => !linked.has(n.id));
  if (loose.length) blocks.push(layoutIsolated(loose));

  let x = 0;
  let y = 0;
  let rowHeight = 0;
  for (const b of blocks) {
    if (x > 0 && x + b.width > MAX_ROW_WIDTH) {
      x = 0;
      y += rowHeight + COMPONENT_GAP;
      rowHeight = 0;
    }
    for (const [id, p] of b.local) out.set(id, { x: x + p.x, y: y + p.y });
    x += b.width + COMPONENT_GAP;
    rowHeight = Math.max(rowHeight, b.height);
  }
  return out;
}

export function networkRects(positions: Positions): NodeRect[] {
  return [...positions].map(([id, p]) => ({
    id,
    x: p.x,
    y: p.y,
    width: NETWORK_NODE_WIDTH,
    height: NETWORK_NODE_HEIGHT,
  }));
}

export function overlappingNetworkNodes(
  positions: Positions,
  minGap = NODE_SEP - 4,
): Array<[string, string]> {
  return findOverlappingPairs(networkRects(positions), minGap);
}

let lastKey = "";
let lastLayout: Positions = new Map();

/** Memoised wrapper so graph and keyboard navigation share one computation. */
export function networkLayoutFor(nodes: Node[], edges: Edge[]): Positions {
  const key = topologyKey(nodes, edges);
  if (key !== lastKey) {
    lastLayout = computeNetworkLayout(nodes, edges);
    lastKey = key;
  }
  return lastLayout;
}

let live: Positions | null = null;
/** Latest on-screen positions published by the graph (for keyboard navigation). */
export function publishLivePositions(p: Positions | null): void {
  live = p;
}
export function livePositions(): Positions | null {
  return live;
}
