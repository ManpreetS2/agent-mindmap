import { forceX, forceY, type Force } from "d3-force";
import type { GLink, GNode } from "./networkModel";

// Includes the outer ring, three bounded label lines, ambient displacement and a gutter.
// Use a stable envelope: changing status or zoom must never reheat the simulation.
export const NODE_BOUNDS = { left: -86, right: 86, top: -34, bottom: 82 } as const;
export const MAX_SPEED = 5;

/** Sweep-and-prune rectangle collision, respecting fixed axes. Registered after other forces. */
export function labelCollision(): Force<GNode, GLink> {
  let nodes: GNode[] = [];
  const force = (() => {
    for (let pass = 0; pass < 2; pass++) {
      const sorted = [...nodes].sort((a, b) => (a.x! + (a.vx ?? 0)) - (b.x! + (b.vx ?? 0)));
      for (let i = 0; i < sorted.length; i++) {
        const a = sorted[i];
        for (let j = i + 1; j < sorted.length; j++) {
          const b = sorted[j];
          const dx = b.x! + (b.vx ?? 0) - a.x! - (a.vx ?? 0);
          if (dx >= 172) continue;
          const dy = b.y! + (b.vy ?? 0) - a.y! - (a.vy ?? 0);
          const px = 172 - Math.abs(dx), py = 116 - Math.abs(dy);
          if (px <= 0 || py <= 0) continue;
          // Push along the centre-to-centre ray. Minimum-axis-only correction makes
          // wide labels collapse small networks into a tall, narrow column.
          const rx = Math.abs(dx) < 0.01 ? 0.01 : dx;
          const ry = Math.abs(dy) < 0.01 ? 0.01 : dy;
          const factor = (Math.min(172 / Math.abs(rx), 116 / Math.abs(ry)) - 1) * 0.8;
          for (const axis of ["x", "y"] as const) {
            const v = axis === "x" ? "vx" : "vy", f = axis === "x" ? "fx" : "fy";
            const am = a[f] == null, bm = b[f] == null;
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
