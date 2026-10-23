import { describe, expect, it } from "vitest";
import { ForceNetwork, FORCE } from "../utils/forceNetwork";
import {
  computeNetworkLayout,
  overlappingNetworkNodes,
  type Positions,
} from "../utils/networkLayout";
import type { Edge, Node } from "@shared/types";

const node = (id: string, project = "p"): Node => ({
  id, label: id, group: "sessions", status: "IN_PROGRESS", agent_links: [], layout: { x: 0, y: 0 },
  session: { source: "s", thread_id: id, project, provider: "Codex", model: "m", reported_status: "running", branch: null, source_links: [], stale: false },
});
const edge = (s: string, t: string): Edge => ({ id: `${s}-${t}`, source: s, target: t, type: "delegation", count: 1, event_ids: [`${s}-${t}`] });

function run(nodes: Node[], edges: Edge[]): { net: ForceNetwork; pos: Positions } {
  const net = new ForceNetwork();
  net.update(nodes.map((n) => ({ id: n.id, active: true })), edges, computeNetworkLayout(nodes, edges));
  return { net, pos: net.positions() };
}

const nodes = ["a", "b", "c", "d", "e", "f", "g"].map((id) => node(id));
const edges = [edge("a", "b"), edge("a", "c"), edge("c", "d")];

describe("force network", () => {
  it("is deterministic for identical inputs", () => {
    const one = run(nodes, edges).pos;
    const two = run(nodes, edges).pos;
    expect([...one]).toEqual([...two]);
  });

  it("separates cards (no overlap) and keeps delegates near their parent and to its right", () => {
    const { pos } = run(nodes, edges);
    expect(overlappingNetworkNodes(pos, FORCE.gap - 6)).toEqual([]);
    const a = pos.get("a")!, b = pos.get("b")!, d = pos.get("d")!, g = pos.get("g")!;
    expect(b.x).toBeGreaterThan(a.x);
    const dist = (p: { x: number; y: number }, q: { x: number; y: number }) => Math.hypot(p.x - q.x, p.y - q.y);
    expect(dist(a, b)).toBeLessThan(FORCE.linkDistance * 1.5);
    expect(dist(a, b)).toBeLessThan(dist(a, g));
    expect(d).toBeDefined();
  });

  it("keeps positions across status-only updates and adds heat only on topology change", () => {
    const { net, pos } = run(nodes, edges);
    net.update(nodes.map((n) => ({ id: n.id, active: false })), edges, new Map());
    expect([...net.positions()]).toEqual([...pos]);
  });

  it("adds a new delegate near its parent without moving settled nodes far", () => {
    const { net, pos } = run(nodes, edges);
    const withNew = [...nodes, node("h")];
    net.update(withNew.map((n) => ({ id: n.id, active: true })), [...edges, edge("e", "h")], new Map());
    const after = net.positions();
    expect(overlappingNetworkNodes(after, FORCE.gap - 6)).toEqual([]);
    const e = after.get("e")!, h = after.get("h")!;
    expect(Math.hypot(e.x - h.x, e.y - h.y)).toBeLessThan(FORCE.linkDistance * 1.6);
    for (const id of ["a", "b", "c"]) {
      const p = pos.get(id)!, q = after.get(id)!;
      expect(Math.hypot(p.x - q.x, p.y - q.y)).toBeLessThan(500);
    }
  });

  it("pins dragged nodes exactly and unpinAll releases them", () => {
    const { net } = run(nodes, edges);
    net.drag("b", { x: 543, y: 321 }, false);
    net.update(nodes.map((n) => ({ id: n.id, active: true })), [...edges, edge("b", "e")], new Map());
    expect(net.positions().get("b")).toEqual({ x: 543, y: 321 });
    expect(net.pinned.has("b")).toBe(true);
    net.unpinAll();
    expect(net.pinned.size).toBe(0);
    expect(net.positions().get("b")).not.toEqual({ x: 543, y: 321 });
  });

  it("removes departed nodes and their pins", () => {
    const { net } = run(nodes, edges);
    net.drag("g", { x: 5, y: 5 }, false);
    net.update(nodes.slice(0, 6).map((n) => ({ id: n.id, active: true })), edges, new Map());
    expect(net.positions().has("g")).toBe(false);
    expect(net.pinned.has("g")).toBe(false);
  });

});
