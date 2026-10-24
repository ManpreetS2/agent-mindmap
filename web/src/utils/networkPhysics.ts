import { forceX, forceY, forceSimulation, forceManyBody, forceLink, type Force } from "d3-force";
import type { GLink, GNode } from "./networkModel";

// Includes the outer ring, three bounded label lines, ambient displacement and a gutter.
// Use a stable envelope: changing status or zoom must never reheat the simulation.
export const NODE_BOUNDS = { left: -86, right: 86, top: -44, bottom: 94 } as const;
export const MAX_SPEED = 5;

/** Sweep-and-prune rectangle collision, respecting fixed axes. Registered after other forces. */
export function labelCollision(): Force<GNode, GLink> {
  let nodes: GNode[] = [];
  const force = ((alpha: number) => {
    // Clear stale anchors only during an explicit drag; ordinary polls never release them.
    for (const n of nodes) {
      if (n.dragging || n.pinned) releaseSettled(n);
      else if (n.settledX != null && n.settledY != null) {
        n.x = n.settledX; n.y = n.settledY; n.vx = 0; n.vy = 0;
      }
    }
    for (let pass = 0; pass < 2; pass++) {
      const sorted = [...nodes].sort((a, b) => (a.x! + (a.vx ?? 0)) - (b.x! + (b.vx ?? 0)));
      for (let i = 0; i < sorted.length; i++) {
        const a = sorted[i];
        for (let j = i + 1; j < sorted.length; j++) {
          const b = sorted[j];
          const dx = b.x! + (b.vx ?? 0) - a.x! - (a.vx ?? 0);
          if (dx >= 172) continue;
          const dy = b.y! + (b.vy ?? 0) - a.y! - (a.vy ?? 0);
          const px = 172 - Math.abs(dx), py = 138 - Math.abs(dy);
          if (px <= 0 || py <= 0) continue;
          // Push along the centre-to-centre ray. Minimum-axis-only correction makes
          // wide labels collapse small networks into a tall, narrow column.
          const rx = Math.abs(dx) < 0.01 ? 0.01 : dx;
          const ry = Math.abs(dy) < 0.01 ? 0.01 : dy;
          const factor = (Math.min(172 / Math.abs(rx), 138 / Math.abs(ry)) - 1) * 0.8;
          for (const axis of ["x", "y"] as const) {
            const v = axis === "x" ? "vx" : "vy", f = axis === "x" ? "fx" : "fy";
            const am = a[f] == null && a.settledX == null, bm = b[f] == null && b.settledX == null;
            if (!am && !bm) continue;
            const delta = (axis === "x" ? rx : ry) * factor / (Number(am) + Number(bm));
            if (am) a[v] = (a[v] ?? 0) - delta;
            if (bm) b[v] = (b[v] ?? 0) + delta;
          }
        }
      }
    }
    // Bound arrival displacement; newcomers cannot kick the whole graph across the screen.
    for (const n of nodes) {
      const speed = Math.hypot(n.vx ?? 0, n.vy ?? 0);
      if (speed > MAX_SPEED) { n.vx = n.vx! * MAX_SPEED / speed; n.vy = n.vy! * MAX_SPEED / speed; }
      // Freeze before force-graph's alpha stop (0.0002). This also makes extra ticks exact no-ops.
      if (alpha <= 0.00025 && !n.pinned && !n.dragging && n.settledX == null) {
        n.settledX = n.x; n.settledY = n.y;
      }
      if (n.settledX != null && n.settledY != null && !n.pinned && !n.dragging) {
        n.x = n.settledX; n.y = n.settledY; n.vx = 0; n.vy = 0;
      }
    }
  }) as Force<GNode, GLink>;
  force.initialize = (next) => { nodes = next; };
  return force;
}

export function networkForces() {
  return {
    x: forceX<GNode>(0).strength(0.009),
    y: forceY<GNode>(0).strength(0.009),
    collide: labelCollision(),
  };
}

/** Explicit unpin is the only action that releases a settled node's layout anchor. */
export function releaseSettled(n: GNode): void {
  n.settledX = undefined; n.settledY = undefined;
}

/** Reduced motion: solve synchronously before publishing graphData, never show settling frames. */
export function settleLayout(nodes: GNode[], links: GLink[]): void {
  const sim = forceSimulation<GNode>(nodes).stop().alphaDecay(0.035).velocityDecay(0.55)
    .force("charge", forceManyBody<GNode>().strength(-180).distanceMax(500))
    .force("link", forceLink<GNode, GLink>(links).id(n => n.id).distance(154).strength(0.16));
  for (const [name, force] of Object.entries(networkForces())) sim.force(name, force);
  sim.tick(260);
  for (const n of nodes) { n.ox = 0; n.oy = 0; }
}

/** Explicit pause accepts the current arrangement without moving any agent. */
export function freezeLayout(nodes: Iterable<GNode>): void {
  for (const n of nodes) {
    if (!n.pinned && !n.dragging) { n.settledX = n.x; n.settledY = n.y; }
    n.vx = 0; n.vy = 0;
  }
}
