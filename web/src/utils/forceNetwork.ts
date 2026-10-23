import {
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type Simulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";
import {
  NETWORK_NODE_HEIGHT,
  NETWORK_NODE_WIDTH,
  type Positions,
} from "./networkLayout";

/** Tunables. Distances are in canvas px. */
export const FORCE = {
  linkDistance: 340,
  linkStrength: 0.55,
  charge: -950,
  chargeMax: 800,
  gravity: 0.018,
  /** Pulls a delegate to the right of its parent so arrows read left → right unless dragged. */
  flow: 0.05,
  gap: 28,
  /** Residual heat while active agents exist so the network keeps breathing. */
  ambientAlpha: 0.012,
  ambientKick: 0.5,
  settleTicks: 360,
} as const;

/** Global switch used by the test environment (no timers / animation frames). */
export const physicsConfig = { loop: true };

export interface SimNode extends SimulationNodeDatum {
  id: string;
  active: boolean;
  phase: number;
}
type SimLink = SimulationLinkDatum<SimNode>;

export interface NetworkNodeInput {
  id: string;
  active: boolean;
}
export interface NetworkLinkInput {
  source: string;
  target: string;
}

/** Deterministic PRNG so identical inputs always yield identical motion. */
function lcg(seed = 1): () => number {
  let s = seed >>> 0;
  return () => {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
    return s / 0x100000000;
  };
}

function hash(id: string): number {
  let h = 2166136261;
  for (let i = 0; i < id.length; i++) h = Math.imul(h ^ id.charCodeAt(i), 16777619);
  return (h >>> 0) / 0x100000000;
}

/** Axis-aligned card separation. Resolves along the axis of least penetration. */
function rectCollide(gap: number) {
  let nodes: SimNode[] = [];
  const w = NETWORK_NODE_WIDTH + gap;
  const h = NETWORK_NODE_HEIGHT + gap;
  const force = () => {
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i];
        const b = nodes[j];
        const dx = (b.x ?? 0) - (a.x ?? 0);
        const dy = (b.y ?? 0) - (a.y ?? 0);
        const ox = w - Math.abs(dx);
        const oy = h - Math.abs(dy);
        if (ox <= 0 || oy <= 0) continue;
        const aFixed = a.fx != null;
        const bFixed = b.fx != null;
        if (aFixed && bFixed) continue;
        const shareA = aFixed ? 0 : bFixed ? 1 : 0.5;
        const shareB = 1 - shareA;
        if (ox < oy) {
          const s = (dx >= 0 ? 1 : -1) * ox * 0.6;
          a.vx! -= s * shareA;
          b.vx! += s * shareB;
        } else {
          const s = (dy >= 0 ? 1 : -1) * oy * 0.6;
          a.vy! -= s * shareA;
          b.vy! += s * shareB;
        }
      }
    }
  };
  force.initialize = (n: SimNode[]) => {
    nodes = n;
  };
  return force;
}

/** Keeps a delegate to the right of its parent. */
function flowForce(links: () => SimLink[]) {
  const force = (alpha: number) => {
    for (const l of links()) {
      const s = l.source as SimNode;
      const t = l.target as SimNode;
      if (typeof s !== "object" || typeof t !== "object") continue;
      const want = (s.x ?? 0) + FORCE.linkDistance;
      t.vx! += (want - (t.x ?? 0)) * FORCE.flow * alpha;
      s.vx! -= (want - (t.x ?? 0)) * FORCE.flow * alpha * 0.5;
    }
  };
  force.initialize = () => {};
  return force;
}

/**
 * d3-force physics for the agent network. Owns node coordinates (centres); the canvas only
 * renders them. Positions persist across updates: only genuine topology changes add heat.
 */
export class ForceNetwork {
  private sim: Simulation<SimNode, SimLink>;
  private nodes = new Map<string, SimNode>();
  private links: SimLink[] = [];
  private topo = "";
  private raf = 0;
  private paused = false;
  private ticks = 0;
  private destroyed = false;
  private listeners = new Set<() => void>();
  /** Nodes the user pinned by dragging. */
  readonly pinned = new Set<string>();

  constructor() {
    this.sim = forceSimulation<SimNode, SimLink>()
      .randomSource(lcg(7))
      .alphaDecay(0.028)
      .velocityDecay(0.42)
      .force("charge", forceManyBody<SimNode>().strength(FORCE.charge).distanceMax(FORCE.chargeMax))
      .force("x", forceX<SimNode>(0).strength(FORCE.gravity))
      .force("y", forceY<SimNode>(0).strength(FORCE.gravity))
      .force("rect", rectCollide(FORCE.gap) as never)
      .force("flow", flowForce(() => this.links) as never)
      .force(
        "link",
        forceLink<SimNode, SimLink>([])
          .id((n) => n.id)
          .distance(FORCE.linkDistance)
          .strength(FORCE.linkStrength),
      )
      .force("ambient", this.ambient as never)
      .stop();
  }

  /** Subtle, deterministic drift for active agents (a few px, never overlapping). */
  private ambient = Object.assign(
    () => {
      this.ticks++;
      const t = this.ticks * 0.016;
      for (const n of this.nodes.values()) {
        if (!n.active || n.fx != null) continue;
        n.vx! += Math.sin(t * 0.9 + n.phase * 6.28) * FORCE.ambientKick * 0.1;
        n.vy! += Math.cos(t * 0.7 + n.phase * 6.28) * FORCE.ambientKick * 0.1;
      }
    },
    { initialize: () => {} },
  );

  onChange(fn: () => void): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  private emit() {
    for (const l of this.listeners) l();
  }

  /** Top-left positions in canvas space. */
  positions(): Positions {
    const out: Positions = new Map();
    for (const n of this.nodes.values()) {
      out.set(n.id, {
        x: (n.x ?? 0) - NETWORK_NODE_WIDTH / 2,
        y: (n.y ?? 0) - NETWORK_NODE_HEIGHT / 2,
      });
    }
    return out;
  }

  /**
   * Reconcile nodes/links. `seed` gives initial top-left positions for brand-new nodes that
   * have no parent. Existing nodes keep their coordinates; heat is added only when the
   * topology (ids or links) actually changed.
   */
  update(nodes: NetworkNodeInput[], links: NetworkLinkInput[], seed: Positions): void {
    const ids = new Set(nodes.map((n) => n.id));
    const parentOf = new Map<string, string>();
    for (const l of links) if (ids.has(l.source) && ids.has(l.target)) parentOf.set(l.target, l.source);

    let changed = false;
    for (const id of [...this.nodes.keys()]) {
      if (!ids.has(id)) {
        this.nodes.delete(id);
        this.pinned.delete(id);
        changed = true;
      }
    }
    const first = this.nodes.size === 0;
    const linked = new Set<string>();
    for (const l of links) {
      linked.add(l.source);
      linked.add(l.target);
    }
    let loose = 0;
    for (const n of [...nodes].sort((a, b) => a.id.localeCompare(b.id))) {
      const existing = this.nodes.get(n.id);
      if (existing) {
        existing.active = n.active;
        continue;
      }
      changed = true;
      const s = seed.get(n.id);
      let x = (s?.x ?? 0) + NETWORK_NODE_WIDTH / 2;
      let y = (s?.y ?? 0) + NETWORK_NODE_HEIGHT / 2;
      if (first && !linked.has(n.id)) {
        // Unrelated agents start on a deterministic sunflower spiral so physics has a 2-D
        // arrangement to relax from (a flat row is an unstable equilibrium).
        const i = loose++;
        const r = 230 * Math.sqrt(i + 0.6);
        x = r * Math.cos(i * 2.399963);
        y = r * Math.sin(i * 2.399963) * 0.8;
      }
      const parent = parentOf.get(n.id);
      const p = parent ? this.nodes.get(parent) : undefined;
      if (!first && p) {
        // A delegate appears next to its parent and drifts out under the link force.
        x = (p.x ?? 0) + 40;
        y = (p.y ?? 0) + (hash(n.id) - 0.5) * 120;
      } else if (!first) {
        const xs = [...this.nodes.values()].map((q) => q.x ?? 0);
        const ys = [...this.nodes.values()].map((q) => q.y ?? 0);
        x = Math.max(...xs) + NETWORK_NODE_WIDTH + 80;
        y = ys.reduce((a, b) => a + b, 0) / ys.length + (hash(n.id) - 0.5) * 200;
      }
      this.nodes.set(n.id, { id: n.id, active: n.active, phase: hash(n.id), x, y, vx: 0, vy: 0 });
    }
    // Centre the first layout on the origin so gravity does not drag it across the canvas.
    if (first && this.nodes.size) {
      const arr = [...this.nodes.values()];
      const cx = arr.reduce((a, n) => a + (n.x ?? 0), 0) / arr.length;
      const cy = arr.reduce((a, n) => a + (n.y ?? 0), 0) / arr.length;
      for (const n of arr) {
        n.x = (n.x ?? 0) - cx;
        n.y = (n.y ?? 0) - cy;
      }
    }

    const key =
      [...ids].sort().join(",") +
      "|" +
      links
        .filter((l) => ids.has(l.source) && ids.has(l.target))
        .map((l) => `${l.source}>${l.target}`)
        .sort()
        .join(",");
    if (key !== this.topo) changed = true;
    this.topo = key;

    this.links = links
      .filter((l) => ids.has(l.source) && ids.has(l.target) && l.source !== l.target)
      .sort((a, b) => `${a.source}>${a.target}`.localeCompare(`${b.source}>${b.target}`))
      .map((l) => ({ source: l.source, target: l.target }));
    const arr = [...this.nodes.values()].sort((a, b) => a.id.localeCompare(b.id));
    this.sim.nodes(arr);
    (this.sim.force("link") as ReturnType<typeof forceLink<SimNode, SimLink>>).links(this.links);
    this.applyAmbient();
    if (first && changed) {
      // First paint starts near equilibrium (so the initial fit-to-view frames the final
      // network), then keeps a little residual heat so it visibly settles.
      this.settle(200);
      this.heat(0.12);
    } else if (changed) {
      this.heat(0.8);
    }
  }

  private anyActive(): boolean {
    for (const n of this.nodes.values()) if (n.active) return true;
    return false;
  }

  private applyAmbient() {
    const on = !this.paused && physicsConfig.loop && this.anyActive();
    this.sim.alphaTarget(on ? FORCE.ambientAlpha : 0);
    if (on) this.run();
  }

  /** Add heat and make sure the loop is running (or settle at once when paused/static). */
  private heat(alpha: number) {
    this.sim.alpha(Math.max(this.sim.alpha(), alpha));
    if (this.paused || !physicsConfig.loop) this.settle();
    else this.run();
  }

  /** Run the simulation to rest synchronously (reduced motion, paused, tests). */
  settle(ticks: number = FORCE.settleTicks) {
    const target = this.sim.alphaTarget();
    this.sim.alphaTarget(0);
    this.sim.alpha(Math.max(this.sim.alpha(), 0.5));
    for (let i = 0; i < ticks && this.sim.alpha() > this.sim.alphaMin(); i++) this.sim.tick();
    this.sim.alphaTarget(target);
    this.emit();
  }

  private run() {
    if (this.raf || this.destroyed || this.paused || !physicsConfig.loop) return;
    const step = () => {
      this.raf = 0;
      if (this.destroyed || this.paused) return;
      this.sim.tick();
      this.emit();
      if (this.sim.alpha() > this.sim.alphaMin() || this.sim.alphaTarget() > 0) {
        this.raf = requestAnimationFrame(step);
      }
    };
    this.raf = requestAnimationFrame(step);
  }

  setPaused(paused: boolean) {
    if (paused === this.paused) return;
    this.paused = paused;
    if (paused) {
      if (this.raf) cancelAnimationFrame(this.raf);
      this.raf = 0;
      this.sim.alphaTarget(0);
    } else {
      this.applyAmbient();
      if (this.sim.alpha() > this.sim.alphaMin()) this.run();
    }
  }

  isPaused(): boolean {
    return this.paused;
  }

  /** Called with the dragged card's top-left position. Pins the node where it is dropped. */
  drag(id: string, topLeft: { x: number; y: number }, dragging: boolean) {
    const n = this.nodes.get(id);
    if (!n) return;
    n.fx = topLeft.x + NETWORK_NODE_WIDTH / 2;
    n.fy = topLeft.y + NETWORK_NODE_HEIGHT / 2;
    n.x = n.fx;
    n.y = n.fy;
    this.pinned.add(id);
    if (dragging) {
      if (!this.paused && physicsConfig.loop) {
        this.sim.alphaTarget(Math.max(this.sim.alphaTarget(), 0.2));
        this.run();
      }
    } else {
      this.applyAmbient();
      this.heat(0.3);
    }
    this.emit();
  }

  unpin(id: string) {
    const n = this.nodes.get(id);
    if (!n) return;
    n.fx = n.fy = null;
    this.pinned.delete(id);
    this.heat(0.5);
  }

  unpinAll() {
    for (const id of [...this.pinned]) {
      const n = this.nodes.get(id);
      if (n) n.fx = n.fy = null;
    }
    this.pinned.clear();
    this.heat(0.6);
  }

  destroy() {
    this.destroyed = true;
    if (this.raf) cancelAnimationFrame(this.raf);
    this.sim.stop();
    this.listeners.clear();
  }
}
