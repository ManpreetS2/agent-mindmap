import { describe, expect, it } from "vitest";
import { forceSimulation, forceManyBody, forceLink } from "d3-force";
import { NetworkModel, type GNode, type GLink } from "../utils/networkModel";
import { networkForces, NODE_BOUNDS, settleLayout } from "../utils/networkPhysics";
import { fittedCamera } from "../utils/networkCamera";
import { sessionNode, t3Activity } from "./helpers";

function layout(count: number) {
  const m = new NetworkModel();
  m.sync(t3Activity(Array.from({ length: count }, (_, i) => sessionNode(`${i}`)), Array.from({ length: count - 1 }, (_, i) => [String(Math.floor(i / 3)), String(i + 1)])));
  const sim = forceSimulation<GNode>(m.data.nodes).stop().alphaDecay(0.035).velocityDecay(0.55)
    .force("charge", forceManyBody<GNode>().strength(-180).distanceMax(500))
    .force("link", forceLink<GNode, GLink>(m.data.links).id(n => n.id).distance(154).strength(0.16));
  for (const [name, force] of Object.entries(networkForces())) sim.force(name, force);
  return { m, sim };
}

describe("network physics", () => {
  it.each([2, 3, 10, 30, 40])("reserves label rectangles and settles without jitter for %i nodes", count => {
    const { m, sim } = layout(count);
    let maxStep = 0;
    for (let i = 0; i < 420; i++) {
      const before = m.data.nodes.map(n => [n.x!, n.y!]); sim.tick();
      m.data.nodes.forEach((n, j) => { maxStep = Math.max(maxStep, Math.hypot(n.x! - before[j][0], n.y! - before[j][1])); });
    }
    expect(maxStep).toBeLessThanOrEqual(2.251); // cap 5 × velocity retention .45
    for (const a of m.data.nodes) for (const b of m.data.nodes) {
      if (a.id === b.id) continue;
      expect(Math.abs(a.x! - b.x!) >= 171 || Math.abs(a.y! - b.y!) >= 137).toBe(true);
    }
    const before = m.data.nodes.map(n => [n.x!, n.y!]); sim.tick(60);
    m.data.nodes.forEach((n, j) => expect(Math.hypot(n.x! - before[j][0], n.y! - before[j][1])).toBe(0));
  });

  it("adding a node leaves every settled idle anchor exactly in place", () => {
    const { m, sim } = layout(30);
    sim.tick(420);
    const before = m.data.nodes.map(n => ({ id: n.id, x: n.x, y: n.y }));
    const activity = t3Activity([...before.map(n => sessionNode(n.id, { status: "IDLE" })), sessionNode("new")], [["0", "new"]]);
    m.sync(activity);
    sim.nodes(m.data.nodes);
    (sim.force("link") as ReturnType<typeof forceLink<GNode, GLink>>).links(m.data.links);
    sim.alpha(1);
    let last = { x: m.node.get("new")!.x!, y: m.node.get("new")!.y! };
    for (let i = 0; i < 420; i++) {
      sim.tick();
      for (const n of before) expect({ x: m.node.get(n.id)!.x, y: m.node.get(n.id)!.y }).toEqual({ x: n.x, y: n.y });
      const added = m.node.get("new")!;
      expect(Math.hypot(added.x! - last.x, added.y! - last.y)).toBeLessThanOrEqual(2.251);
      last = { x: added.x!, y: added.y! };
    }
    const added = m.node.get("new")!;
    for (const n of before) expect(Math.hypot(added.x! - n.x!, added.y! - n.y!)).toBeGreaterThan(42);
  });

  it("precomputes reduced-motion layout and leaves no drift or residual velocity", () => {
    const { m, sim } = layout(30);
    settleLayout(m.data.nodes, m.data.links);
    const positions = m.data.nodes.map(n => [n.x, n.y]);
    sim.alpha(1).tick(100);
    expect(m.data.nodes.map(n => [n.x, n.y])).toEqual(positions);
    expect(m.data.nodes.every(n => n.vx === 0 && n.vy === 0 && n.ox === 0 && n.oy === 0)).toBe(true);
    for (const a of m.data.nodes) for (const b of m.data.nodes) {
      if (a !== b) expect(Math.hypot(a.x! - b.x!, a.y! - b.y!)).toBeGreaterThan(42);
    }
  });

  it("does not move pinned nodes", () => {
    const { m, sim } = layout(3);
    const n = m.data.nodes[0]; n.fx = 0; n.fy = 0;
    sim.tick(420);
    expect([n.x, n.y]).toEqual([0, 0]);
  });

  it.each([1, 2, 5, 30])("caps fit and includes label bounds plus padding for %i agents", count => {
    const { m, sim } = layout(count); sim.tick(420);
    const c = fittedCamera(m.data.nodes, 1100, 700)!;
    expect(c.zoom).toBeLessThanOrEqual(1.8);
    for (const n of m.data.nodes) {
      expect((n.x! + NODE_BOUNDS.left - c.x) * c.zoom + 550).toBeGreaterThanOrEqual(69.999);
      expect((n.x! + NODE_BOUNDS.right - c.x) * c.zoom + 550).toBeLessThanOrEqual(1010.001);
      expect((n.y! + NODE_BOUNDS.bottom - c.y) * c.zoom + 350).toBeLessThanOrEqual(550.001);
      expect((n.y! + NODE_BOUNDS.top - c.y) * c.zoom + 350).toBeGreaterThanOrEqual(79.999);
    }
  });
});
