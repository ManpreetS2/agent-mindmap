import type { Activity, Status } from "@shared/types";
import { providerKey, providerLabel, type ProviderKey } from "./provider";

/** A canvas node. Objects are mutated in place by the force engine (x, y, vx, vy, fx, fy). */
export interface GNode {
  id: string;
  label: string;
  provider: ProviderKey;
  providerName: string;
  model: string | null;
  status: Status;
  reported: string;
  task: string | null;
  active: boolean;
  stale: boolean;
  phase: number;
  pinned: boolean;
  dragging?: boolean;
  /** Physics anchors after settle; separate from explicit user pins and ambient offsets. */
  settledX?: number;
  settledY?: number;
  /** Visual-only offset: never feeds back into the physics or pinned coordinates. */
  ox?: number;
  oy?: number;
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
  fx?: number;
  fy?: number;
}

export interface GLink {
  id: string;
  source: string | GNode;
  target: string | GNode;
  type: string;
}

export interface StatusTransition {
  id: string;
  from: Status;
  to: Status;
}

export const ACTIVE_STATUSES: ReadonlySet<Status> = new Set(["IN_PROGRESS", "IN_REVIEW"]);

function hash(id: string): number {
  let h = 2166136261;
  for (let i = 0; i < id.length; i++) h = Math.imul(h ^ id.charCodeAt(i), 16777619);
  return (h >>> 0) / 0x100000000;
}

export const endpointId = (e: string | GNode): string => (typeof e === "string" ? e : e.id);

/**
 * Holds stable node/link objects between polls. `sync` updates facts in place and only replaces
 * `data` (the identity the force engine watches) when ids or relationships change, so status
 * polls never re-heat or move the network. New agents spawn deterministically near their parent.
 */
export class NetworkModel {
  private nodes = new Map<string, GNode>();
  private links = new Map<string, GLink>();
  private topo = "";
  revision = 0;
  private baseline = true;
  data: { nodes: GNode[]; links: GLink[] } = { nodes: [], links: [] };

  /** Reset (mode/source switch): the next sync is a fresh baseline with nothing "new". */
  reset(): void {
    this.nodes.clear();
    this.links.clear();
    this.topo = "";
    this.baseline = true;
    this.data = { nodes: [], links: [] };
  }

  get node(): ReadonlyMap<string, GNode> {
    return this.nodes;
  }

  sync(activity: Activity): { topologyChanged: boolean; visualChanged: boolean; transitions: StatusTransition[]; baseline: boolean } {
    const transitions: StatusTransition[] = [];
    const incoming = [...activity.nodes].filter((n) => n.session).sort((a, b) => a.id.localeCompare(b.id));
    const ids = new Set(incoming.map((n) => n.id));
    const edges = activity.edges.filter(
      (e) => ids.has(e.source) && ids.has(e.target) && e.source !== e.target,
    );
    const parentOf = new Map(edges.map((e) => [e.target, e.source]));
    const wasBaseline = this.baseline;
    let changed = false;
    let visualChanged = false;

    for (const id of [...this.nodes.keys()]) {
      if (!ids.has(id)) {
        this.nodes.delete(id);
        changed = true;
      }
    }

    // Visit parents before new children even when IDs sort in the opposite order.
    const byId = new Map(incoming.map(n => [n.id, n]));
    const ordered: typeof incoming = [], visited = new Set<string>();
    const visit = (id: string) => {
      if (visited.has(id)) return;
      visited.add(id);
      const parent = parentOf.get(id);
      if (parent && byId.has(parent)) visit(parent);
      ordered.push(byId.get(id)!);
    };
    for (const n of incoming) visit(n.id);
    for (const n of ordered) {
      const s = n.session!;
      const facts = {
        label: n.label,
        provider: providerKey(s.provider),
        providerName: providerLabel(s.provider),
        model: s.model,
        status: n.status,
        reported: s.reported_status,
        task: n.current_task ?? null,
        stale: s.stale || n.status === "STALE",
        active: ACTIVE_STATUSES.has(n.status) && !s.stale,
      };
      const existing = this.nodes.get(n.id);
      if (existing) {
        if (existing.status !== facts.status) {
          transitions.push({ id: n.id, from: existing.status, to: facts.status });
        }
        if (Object.entries(facts).some(([key, value]) => existing[key as keyof GNode] !== value)) visualChanged = true;
        Object.assign(existing, facts);
        continue;
      }
      changed = true;
      let x: number;
      let y: number;
      const parent = parentOf.get(n.id);
      const p = parent ? this.nodes.get(parent) : undefined;
      if (this.nodes.size === 0 || wasBaseline) {
        // Deterministic sunflower seed for the first arrangement.
        const i = this.nodes.size;
        const r = 130 * Math.sqrt(i + 0.7);
        x = r * Math.cos(i * 2.399963);
        y = r * Math.sin(i * 2.399963);
      } else {
        const all = [...this.nodes.values()];
        const anchor = p ?? { x: all.reduce((v, q) => v + (q.x ?? 0), 0) / all.length,
          y: all.reduce((v, q) => v + (q.y ?? 0), 0) / all.length };
        // Pick a nearby free slot; never materialize a delegate on top of its parent.
        const start = hash(n.id) * Math.PI * 2;
        let best = { x: anchor.x ?? 0, y: (anchor.y ?? 0) + 150, score: Infinity };
        for (let ring = 1; ring <= 3; ring++) for (let i = 0; i < 24; i++) {
          const a = start + i * Math.PI / 12;
          const radius = Math.min(184 / Math.max(0.001, Math.abs(Math.cos(a))), 150 / Math.max(0.001, Math.abs(Math.sin(a)))) * ring;
          const px = (anchor.x ?? 0) + Math.cos(a) * radius, py = (anchor.y ?? 0) + Math.sin(a) * radius;
          let overlaps = 0;
          for (const q of this.nodes.values()) if (Math.abs(px - q.x!) < 180 && Math.abs(py - q.y!) < 146) overlaps++;
          const score = overlaps * 10000 + radius;
          if (score < best.score) best = { x: px, y: py, score };
        }
        x = best.x; y = best.y;
      }
      this.nodes.set(n.id, { id: n.id, ...facts, phase: hash(n.id), pinned: false, x, y, vx: 0, vy: 0 });
    }

    const wanted = new Set(edges.map((e) => e.id));
    for (const id of [...this.links.keys()]) {
      if (!wanted.has(id)) {
        this.links.delete(id);
        changed = true;
      }
    }
    for (const e of edges) {
      const old = this.links.get(e.id);
      if (!old || endpointId(old.source) !== e.source || endpointId(old.target) !== e.target || old.type !== e.type) {
        this.links.set(e.id, { id: e.id, source: e.source, target: e.target, type: e.type });
        changed = true;
      }
    }

    const key = [...ids].sort().join(",") + "|" + [...wanted].sort().join(",");
    if (key !== this.topo) changed = true;
    this.topo = key;
    this.baseline = false;

    if (changed) {
      this.data = {
        nodes: [...this.nodes.values()].sort((a, b) => a.id.localeCompare(b.id)),
        links: [...this.links.values()].sort((a, b) => a.id.localeCompare(b.id)),
      };
    }
    if (changed || visualChanged) this.revision++;
    return { topologyChanged: changed, visualChanged: changed || visualChanged, transitions: wasBaseline ? [] : transitions, baseline: wasBaseline };
  }
}

/** Caption for an *observed* status change (never implies anything beyond the status delta). */
export function transitionCaption(t: StatusTransition): string {
  if (t.to === "IN_PROGRESS" || t.to === "IN_REVIEW") {
    return t.from === "FAILED" || t.from === "BLOCKED" || t.from === "STALE" ? "RESUMED" : "STARTED";
  }
  if (t.to === "BLOCKED") return "BLOCKED";
  if (t.to === "FAILED") return "FAILED";
  if (t.to === "DONE") return "COMPLETED";
  if (t.to === "STALE") return "STALE";
  return t.to.replace("_", " ");
}

export const AMBIENT_PX = 3.2;
/** World units per painted frame, including active-status entry. At fit zoom <=1.8: <=0.216 px. */
export const AMBIENT_MAX_STEP = 0.12;

/** Accumulates only running time; clamping long frames prevents resume/background-tab jumps. */
export class AmbientClock {
  private last: number | null = null;
  private elapsed = 0;
  step(now: number, running: boolean): number {
    if (running && this.last !== null) this.elapsed += Math.min(32, Math.max(0, now - this.last));
    this.last = running ? now : null;
    return this.elapsed;
  }
}

/** Bounded visual motion; leaves simulation coordinates untouched, including on status changes. */
export function stepAmbient(nodes: Iterable<GNode>, timeMs: number): void {
  const t = timeMs / 1000;
  for (const n of nodes) {
    if (!n.active || n.pinned || n.dragging || n.fx != null || n.fy != null) {
      n.ox = 0; n.oy = 0;
      continue;
    }
    const dx = AMBIENT_PX * Math.sin(t * 0.9 + n.phase * 6.28) - (n.ox ?? 0);
    const dy = AMBIENT_PX * Math.cos(t * 0.7 + n.phase * 6.28) - (n.oy ?? 0);
    const fraction = Math.min(1, AMBIENT_MAX_STEP / (Math.hypot(dx, dy) || 1));
    n.ox = (n.ox ?? 0) + dx * fraction;
    n.oy = (n.oy ?? 0) + dy * fraction;
  }
}

export function nodePosition(n: GNode): { x: number; y: number } {
  const offset = n.active && !n.pinned && !n.dragging && n.fx == null && n.fy == null;
  return { x: (n.x ?? 0) + (offset ? n.ox ?? 0 : 0), y: (n.y ?? 0) + (offset ? n.oy ?? 0 : 0) };
}
