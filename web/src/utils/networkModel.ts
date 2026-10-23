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
  /** Ambient offset currently applied to x/y (bounded, zero-mean). */
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

  sync(activity: Activity): { topologyChanged: boolean; transitions: StatusTransition[]; baseline: boolean } {
    const transitions: StatusTransition[] = [];
    const incoming = [...activity.nodes].filter((n) => n.session).sort((a, b) => a.id.localeCompare(b.id));
    const ids = new Set(incoming.map((n) => n.id));
    const edges = activity.edges.filter(
      (e) => ids.has(e.source) && ids.has(e.target) && e.source !== e.target,
    );
    const parentOf = new Map(edges.map((e) => [e.target, e.source]));
    const wasBaseline = this.baseline;
    let changed = false;

    for (const id of [...this.nodes.keys()]) {
      if (!ids.has(id)) {
        this.nodes.delete(id);
        changed = true;
      }
    }

    let loose = 0;
    const linked = new Set(edges.flatMap((e) => [e.source, e.target]));
    for (const n of incoming) {
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
        Object.assign(existing, facts);
        continue;
      }
      changed = true;
      let x: number;
      let y: number;
      const parent = parentOf.get(n.id);
      const p = parent ? this.nodes.get(parent) : undefined;
      if (this.nodes.size === 0 || (wasBaseline && !p)) {
        // Deterministic sunflower seed for the first arrangement.
        const i = linked.has(n.id) ? this.nodes.size : loose++ + this.nodes.size;
        const r = 62 * Math.sqrt(i + 0.7);
        x = r * Math.cos(i * 2.399963);
        y = r * Math.sin(i * 2.399963);
      } else if (p) {
        const a = hash(n.id) * Math.PI * 2;
        x = (p.x ?? 0) + Math.cos(a) * 24;
        y = (p.y ?? 0) + Math.sin(a) * 24;
      } else {
        const all = [...this.nodes.values()];
        const cx = all.reduce((t, q) => t + (q.x ?? 0), 0) / all.length;
        const cy = all.reduce((t, q) => t + (q.y ?? 0), 0) / all.length;
        const a = hash(n.id) * Math.PI * 2;
        x = cx + Math.cos(a) * 140;
        y = cy + Math.sin(a) * 140;
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
      if (!this.links.has(e.id)) {
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
    return { topologyChanged: changed, transitions: wasBaseline ? [] : transitions, baseline: wasBaseline };
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

/** Bounded, zero-mean wobble for active, unpinned agents. Independent of the physics engine. */
export function stepAmbient(nodes: Iterable<GNode>, timeMs: number): void {
  const t = timeMs / 1000;
  for (const n of nodes) {
    if (!n.active || n.fx !== undefined || n.x === undefined || n.y === undefined) continue;
    const ox = AMBIENT_PX * Math.sin(t * 0.9 + n.phase * 6.28);
    const oy = AMBIENT_PX * Math.cos(t * 0.7 + n.phase * 6.28);
    n.x += ox - (n.ox ?? 0);
    n.y += oy - (n.oy ?? 0);
    n.ox = ox;
    n.oy = oy;
  }
}
