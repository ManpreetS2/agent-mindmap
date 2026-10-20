import dagre from "@dagrejs/dagre";
import type { Edge, Node, NodeGroup } from "@shared/types";
import { NODE_HEIGHT, NODE_WIDTH } from "./groupFrames";
import {
  collectGroupIds,
  groupsForNode,
  homeGroupForNode,
} from "./groupMembership";

/** Minimum clear gap between node bounding boxes (px). */
export const MIN_NODE_GAP = 24;

/** Gap between group cluster bounding boxes. */
export const CLUSTER_GAP = 48;

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

export interface ClusterBounds {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface MembershipLink {
  botId: string;
  groupId: string;
}

export interface MultiGroupLayoutResult {
  positions: Map<string, { x: number; y: number }>;
  /** Anchor position for synthetic `group:{id}` nodes (label/center top). */
  groupAnchors: Map<string, { x: number; y: number }>;
  clusters: ClusterBounds[];
  /** Secondary memberships (bot belongs to group but is placed in home cluster). */
  membershipLinks: MembershipLink[];
}

/**
 * MM-020f: dagre layout per group cluster; one identity for multi-membership.
 * Multi-group agents sit in their home (`node.group`) cluster and get membership links.
 */
export function layoutMultiGroupClusters(
  nodes: Node[],
  edges: Edge[],
): MultiGroupLayoutResult {
  if (nodes.length === 0) {
    return {
      positions: new Map(),
      groupAnchors: new Map(),
      clusters: [],
      membershipLinks: [],
    };
  }

  const groupIds = collectGroupIds(nodes);
  const localLayouts = new Map<string, Map<string, { x: number; y: number }>>();

  for (const gid of groupIds) {
    // Prefer home-group placement; one identity — never duplicate node ids.
    const clusterNodes = nodes.filter((n) => homeGroupForNode(n) === gid);
    const idSet = new Set(clusterNodes.map((n) => n.id));
    const clusterEdges = edges.filter(
      (e) =>
        idSet.has(e.source) &&
        idSet.has(e.target) &&
        !e.target.startsWith("group:"),
    );
    localLayouts.set(
      gid,
      layoutWithDagreEngineLocal(clusterNodes, clusterEdges),
    );
  }

  const clusterSizes = new Map<
    string,
    { width: number; height: number; local: Map<string, { x: number; y: number }> }
  >();

  for (const gid of groupIds) {
    const local = localLayouts.get(gid) ?? new Map();
    let maxX = 0;
    let maxY = 0;
    for (const [, p] of local) {
      maxX = Math.max(maxX, p.x + LAYOUT_NODE_WIDTH);
      maxY = Math.max(maxY, p.y + LAYOUT_NODE_HEIGHT);
    }
    // Minimum cluster pad so empty-ish groups still get a frame.
    const width = Math.max(maxX + 16, LAYOUT_NODE_WIDTH + 32);
    const height = Math.max(maxY + 16, LAYOUT_NODE_HEIGHT + 32);
    clusterSizes.set(gid, { width, height, local });
  }

  const origins = placeClusterOrigins(groupIds, clusterSizes);
  const positions = new Map<string, { x: number; y: number }>();
  const clusters: ClusterBounds[] = [];
  const groupAnchors = new Map<string, { x: number; y: number }>();

  for (const gid of groupIds) {
    const size = clusterSizes.get(gid)!;
    const origin = origins.get(gid) ?? { x: 0, y: 0 };
    for (const [id, p] of size.local) {
      positions.set(id, { x: origin.x + p.x, y: origin.y + p.y });
    }
    clusters.push({
      id: gid,
      x: origin.x,
      y: origin.y,
      width: size.width,
      height: size.height,
    });
    groupAnchors.set(gid, {
      x: origin.x + size.width / 2 - 40,
      y: origin.y - 8,
    });
  }

  // Nodes not placed (e.g. home group missing from collect) — append.
  for (const n of nodes) {
    if (positions.has(n.id)) continue;
    const fallback = layoutWithDagreEngine([n], []);
    const p = fallback.get(n.id) ?? n.layout;
    positions.set(n.id, p);
  }

  const membershipLinks: MembershipLink[] = [];
  for (const n of nodes) {
    const home = String(homeGroupForNode(n));
    for (const g of groupsForNode(n)) {
      const gid = String(g);
      if (gid !== home) {
        membershipLinks.push({ botId: n.id, groupId: gid });
      }
    }
  }

  const gapEnforced = enforceMinGap(positions, nodes);
  // Recompute cluster bounds from final agent positions + membership for frames.
  const enrichedClusters = clusters.map((c) => {
    const members = nodes.filter((n) =>
      groupsForNode(n).some((g) => String(g) === c.id),
    );
    if (members.length === 0) return c;
    let minX = c.x;
    let minY = c.y;
    let maxX = c.x + c.width;
    let maxY = c.y + c.height;
    for (const m of members) {
      // Only expand frame toward home-placed nodes that belong; multi-members
      // stay in home cluster — secondary frames use membership links instead.
      if (homeGroupForNode(m) !== c.id) continue;
      const p = gapEnforced.get(m.id);
      if (!p) continue;
      minX = Math.min(minX, p.x);
      minY = Math.min(minY, p.y);
      maxX = Math.max(maxX, p.x + LAYOUT_NODE_WIDTH);
      maxY = Math.max(maxY, p.y + LAYOUT_NODE_HEIGHT);
    }
    const pad = 28;
    const label = 22;
    return {
      id: c.id,
      x: minX - pad,
      y: minY - pad - label,
      width: maxX - minX + pad * 2,
      height: maxY - minY + pad * 2 + label,
    };
  });

  for (const c of enrichedClusters) {
    groupAnchors.set(c.id, {
      x: c.x + Math.max(8, c.width / 2 - 40),
      y: c.y + 4,
    });
  }

  return {
    positions: gapEnforced,
    groupAnchors,
    clusters: enrichedClusters,
    membershipLinks,
  };
}

function layoutWithDagreEngineLocal(
  nodes: Node[],
  edges: Edge[],
): Map<string, { x: number; y: number }> {
  if (nodes.length === 0) return new Map();
  if (nodes.length === 1) {
    return new Map([[nodes[0].id, { x: 16, y: 16 }]]);
  }
  return layoutWithDagreEngine(nodes, edges);
}

function placeClusterOrigins(
  groupIds: string[],
  sizes: Map<string, { width: number; height: number }>,
): Map<string, { x: number; y: number }> {
  const origins = new Map<string, { x: number; y: number }>();
  const margin = 24;

  const owner = sizes.get("owner");
  let y = margin;
  if (groupIds.includes("owner") && owner) {
    origins.set("owner", { x: margin, y });
    y += owner.height + CLUSTER_GAP;
  }

  const build = sizes.get("build");
  const qr = sizes.get("qr");
  const buildY = y;
  if (groupIds.includes("build") && build) {
    origins.set("build", { x: margin, y: buildY });
  }
  if (groupIds.includes("qr") && qr) {
    const buildW = build?.width ?? 0;
    origins.set("qr", {
      x: margin + (groupIds.includes("build") ? buildW + CLUSTER_GAP : 0),
      y: buildY,
    });
  }

  const buildH = build?.height ?? 0;
  const qrH = qr?.height ?? 0;
  y =
    buildY +
    Math.max(
      groupIds.includes("build") ? buildH : 0,
      groupIds.includes("qr") ? qrH : 0,
      0,
    ) +
    CLUSTER_GAP;

  if (groupIds.includes("radar") && sizes.get("radar")) {
    origins.set("radar", { x: margin, y });
    y += sizes.get("radar")!.height + CLUSTER_GAP;
  }

  // Any dynamic / unknown groups: stack below.
  for (const gid of groupIds) {
    if (origins.has(gid)) continue;
    const size = sizes.get(gid);
    if (!size) continue;
    origins.set(gid, { x: margin, y });
    y += size.height + CLUSTER_GAP;
  }

  return origins;
}

/**
 * Stable group-band grid (gap ≥ 24px). Owner → build grid → QR column → radar row.
 * Falls back to dagre for unexpected rosters.
 * Prefer {@link layoutMultiGroupClusters} for MM-020 multi-membership.
 */
export function layoutNodesWithDagre(
  nodes: Node[],
  edges: Edge[],
): Map<string, { x: number; y: number }> {
  if (nodes.length === 0) return new Map();
  // Multi-membership or schema 1.1.0 → cluster layout.
  if (nodes.some((n) => (n.groups?.length ?? 0) > 1)) {
    return layoutMultiGroupClusters(nodes, edges).positions;
  }
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
