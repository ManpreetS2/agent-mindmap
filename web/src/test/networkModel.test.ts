import { describe, expect, it } from "vitest";
import { NetworkModel, AmbientClock, AMBIENT_MAX_STEP, AMBIENT_PX, stepAmbient, nodePosition, transitionCaption, endpointId } from "../utils/networkModel";
import { sessionNode, t3Activity } from "./helpers";

const ids = ["a", "b", "c", "d"];
const nodes = ids.map((i) => sessionNode(i));

describe("NetworkModel", () => {
  it("keeps node objects and graphData identity across status-only polls", () => {
    const m = new NetworkModel();
    m.sync(t3Activity(nodes, [["a", "b"]]));
    const data = m.data;
    const a = m.node.get("a")!;
    a.x = 123; a.y = 45;
    const r = m.sync(t3Activity(nodes.map((n) => ({ ...n, status: "FAILED" as const })), [["a", "b"]]));
    expect(r.topologyChanged).toBe(false);
    expect(m.data).toBe(data);
    expect(m.node.get("a")).toBe(a);
    expect(a.status).toBe("FAILED");
    expect([a.x, a.y]).toEqual([123, 45]);
  });

  it("replaces graphData on topology change and keeps surviving positions", () => {
    const m = new NetworkModel();
    m.sync(t3Activity(nodes.slice(0, 3), [["a", "b"]]));
    const before = m.data;
    m.node.get("b")!.x = 77;
    const r = m.sync(t3Activity(nodes, [["a", "b"], ["b", "d"]]));
    expect(r.topologyChanged).toBe(true);
    expect(m.data).not.toBe(before);
    expect(m.node.get("b")!.x).toBe(77);
    expect(m.data.nodes.map((n) => n.id)).toEqual(ids);
    expect(m.data.links).toHaveLength(2);
    // departed agents and their links disappear
    m.sync(t3Activity(nodes.slice(0, 2), [["a", "b"]]));
    expect(m.data.nodes.map((n) => n.id)).toEqual(["a", "b"]);
    expect(m.data.links).toHaveLength(1);
  });

  it("seeds deterministically and spawns delegates beside their parent", () => {
    const one = new NetworkModel(); one.sync(t3Activity(nodes.slice(0, 3), []));
    const two = new NetworkModel(); two.sync(t3Activity([...nodes.slice(0, 3)].reverse(), []));
    expect(one.data.nodes.map((n) => [n.id, n.x, n.y])).toEqual(two.data.nodes.map((n) => [n.id, n.x, n.y]));
    const m = new NetworkModel(); m.sync(t3Activity(nodes.slice(0, 3), []));
    const p = m.node.get("a")!; p.x = 500; p.y = 500;
    m.sync(t3Activity(nodes, [["a", "d"]]));
    const d = m.node.get("d")!;
    expect(Math.hypot(d.x! - 500, d.y! - 500)).toBeLessThan(220);
    expect(Math.abs(d.x! - 500) >= 172 || Math.abs(d.y! - 500) >= 116).toBe(true);
  });

  it("detects changed endpoints on an existing link ID and visual revisions", () => {
    const m = new NetworkModel();
    const a = t3Activity(nodes, [["a", "b"]]); m.sync(a);
    const rev = m.revision;
    expect(m.sync(structuredClone(a)).visualChanged).toBe(false);
    expect(m.revision).toBe(rev);
    const b = structuredClone(a); b.edges[0].source = "c";
    expect(m.sync(b).topologyChanged).toBe(true);
    expect(endpointId(m.data.links[0].source)).toBe("c");
    const c = structuredClone(b); c.nodes[0].session!.model = "new-model";
    expect(m.sync(c)).toMatchObject({ topologyChanged: false, visualChanged: true });
  });

  it("reports observed status transitions but never on the baseline", () => {
    const m = new NetworkModel();
    const first = m.sync(t3Activity(nodes, []));
    expect(first.baseline).toBe(true);
    expect(first.transitions).toEqual([]);
    const next = m.sync(t3Activity(nodes.map((n) => n.id === "b" ? { ...n, status: "FAILED" as const } : n), []));
    expect(next.transitions).toEqual([{ id: "b", from: "IN_PROGRESS", to: "FAILED" }]);
    const retry = m.sync(t3Activity(nodes, []));
    expect(retry.transitions.map(transitionCaption)).toEqual(["RESUMED"]);
    expect(transitionCaption({ id: "x", from: "IN_PROGRESS", to: "DONE" })).toBe("COMPLETED");
    expect(transitionCaption({ id: "x", from: "IDLE", to: "BLOCKED" })).toBe("BLOCKED");
    expect(transitionCaption({ id: "x", from: "IDLE", to: "IN_PROGRESS" })).toBe("STARTED");
  });

  it("reset starts a new baseline with no synthetic carry-over", () => {
    const m = new NetworkModel();
    m.sync(t3Activity(nodes, [["a", "b"]], "demo"));
    m.reset();
    expect(m.data.nodes).toEqual([]);
    const r = m.sync(t3Activity([sessionNode("z")], [], "live"));
    expect(r.baseline).toBe(true);
    expect(m.data.nodes.map((n) => n.id)).toEqual(["z"]);
  });

  it("marks only genuinely active agents as active", () => {
    const m = new NetworkModel();
    m.sync(t3Activity([
      sessionNode("run"), sessionNode("stale", { status: "STALE" }, { stale: true }),
      sessionNode("done", { status: "DONE" }), sessionNode("rev", { status: "IN_REVIEW" }),
    ], []));
    expect(Object.fromEntries(m.data.nodes.map((n) => [n.id, n.active]))).toEqual({ run: true, stale: false, done: false, rev: true });
  });

  it("ignores edges whose endpoints are missing", () => {
    const m = new NetworkModel();
    m.sync(t3Activity([sessionNode("a")], [["a", "ghost"]]));
    expect(m.data.links).toEqual([]);
    expect(endpointId("x")).toBe("x");
  });
});

describe("ambient motion", () => {
  it("bounds each active frame, keeps idle/done/stale nodes exact, and freezes the pause clock", () => {
    const m = new NetworkModel();
    m.sync(t3Activity([sessionNode("active"), ...(["IDLE", "DONE", "STALE"] as const).map(status => sessionNode(status, { status }))], []));
    const clock = new AmbientClock();
    let last = m.data.nodes.map(nodePosition);
    for (let frame = 0; frame < 1200; frame++) {
      stepAmbient(m.data.nodes, clock.step(frame * 16, true));
      m.data.nodes.forEach((n, i) => {
        const p = nodePosition(n), distance = Math.hypot(p.x - last[i].x, p.y - last[i].y);
        expect(distance).toBeLessThanOrEqual(n.active ? AMBIENT_MAX_STEP + 1e-10 : 0);
      });
      last = m.data.nodes.map(nodePosition);
    }
    const stopped = clock.step(20000, false);
    expect(clock.step(60000, false)).toBe(stopped);
    expect(m.data.nodes.map(nodePosition)).toEqual(last);
    expect(clock.step(100000, true)).toBe(stopped);
    expect(clock.step(100016, true)).toBe(stopped + 16);
  });

  it("is bounded, zero-mean, skips pinned/inactive agents", () => {
    const m = new NetworkModel();
    m.sync(t3Activity([sessionNode("a"), sessionNode("b"), sessionNode("c", { status: "DONE" })], []));
    const [a, b, c] = ["a", "b", "c"].map((i) => m.node.get(i)!);
    for (const n of [a, b, c]) { n.x = 100; n.y = 100; }
    b.fx = 100; b.fy = 100;
    let max = 0, sum = 0, count = 0;
    for (let t = 0; t < 60000; t += 16) {
      stepAmbient(m.node.values(), t);
      max = Math.max(max, Math.abs(nodePosition(a).x - 100), Math.abs(nodePosition(a).y - 100));
      sum += nodePosition(a).x - 100; count++;
    }
    expect([a.x, a.y]).toEqual([100, 100]);
    expect(max).toBeGreaterThan(3);
    a.active = false;
    expect(nodePosition(a)).toEqual({ x: 100, y: 100 });
    expect(max).toBeLessThanOrEqual(AMBIENT_PX * 1.01);
    expect(Math.abs(sum / count)).toBeLessThan(AMBIENT_PX / 2);
    expect([b.x, b.y, c.x, c.y]).toEqual([100, 100, 100, 100]);
  });
});
