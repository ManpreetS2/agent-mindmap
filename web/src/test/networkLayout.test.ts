import { describe, expect, it } from "vitest";
import {
  NETWORK_NODE_HEIGHT, NETWORK_NODE_WIDTH, computeNetworkLayout, overlappingNetworkNodes, topologyKey,
} from "../utils/networkLayout";
import { delegation, sessionNode } from "./helpers";

const ids = ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"];
const nodes = ids.map((id, i) => sessionNode(id, {}, { project: i < 5 ? "Alpha" : "Beta" }));
const edges = [delegation("a", "b"), delegation("a", "c"), delegation("c", "d"), delegation("e", "f")].map((x) => x.edge);

describe("seed network layout (Dagre)", () => {
  it("is deterministic regardless of input order", () => {
    const one = computeNetworkLayout(nodes, edges);
    const two = computeNetworkLayout([...nodes].reverse(), [...edges].reverse());
    expect([...one].sort()).toEqual([...two].sort());
  });

  it("places every node without overlap", () => {
    const pos = computeNetworkLayout(nodes, edges);
    expect(pos.size).toBe(nodes.length);
    expect(overlappingNetworkNodes(pos)).toEqual([]);
  });

  it("lays delegates to the right of parents and keeps trees compact", () => {
    const pos = computeNetworkLayout(nodes, edges);
    for (const e of edges) expect(pos.get(e.target)!.x).toBeGreaterThan(pos.get(e.source)!.x + NETWORK_NODE_WIDTH - 1);
    const a = pos.get("a")!, b = pos.get("b")!, g = pos.get("g")!;
    expect(Math.hypot(a.x - b.x, a.y - b.y)).toBeLessThan(Math.hypot(a.x - g.x, a.y - g.y));
  });

  it("does not form one extremely wide strip for many unrelated agents", () => {
    const many = Array.from({ length: 30 }, (_, i) => sessionNode(`n${i}`));
    const pos = computeNetworkLayout(many, []);
    const xs = [...pos.values()].map((p) => p.x);
    expect(Math.max(...xs) - Math.min(...xs)).toBeLessThan(5 * (NETWORK_NODE_WIDTH + 24));
    expect(overlappingNetworkNodes(pos)).toEqual([]);
    expect(NETWORK_NODE_HEIGHT).toBeGreaterThan(0);
  });

  it("topology key ignores status changes but reflects node and edge changes", () => {
    const k = topologyKey(nodes, edges);
    expect(topologyKey(nodes.map((n) => ({ ...n, status: "DONE" as const })), edges)).toBe(k);
    expect(topologyKey(nodes.slice(1), edges)).not.toBe(k);
    expect(topologyKey(nodes, edges.slice(1))).not.toBe(k);
  });
});
