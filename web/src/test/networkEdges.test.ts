import { describe, expect, it, vi } from "vitest";
import { drawNetworkLink, linkGeometry } from "../utils/networkEdges";
import { NetworkModel, nodePosition } from "../utils/networkModel";
import { NODE_R } from "../utils/nodeDraw";
import { sessionNode, t3Activity } from "./helpers";

function nodes() {
  const m = new NetworkModel(); m.sync(t3Activity([sessionNode("a"), sessionNode("b")], []));
  const [a, b] = m.data.nodes;
  Object.assign(a, { x: 0, y: 0, ox: 1, oy: 2 });
  Object.assign(b, { x: 200, y: 100, ox: -2, oy: 1 });
  return [a, b];
}

describe("network edge rendering", () => {
  it.each([0.35, 1, 2.4, 6])("keeps a nine-pixel arrow outside both moving rings at zoom %s", zoom => {
    const [a, b] = nodes();
    const g = linkGeometry(a, b, zoom)!;
    const source = nodePosition(a), target = nodePosition(b);
    expect(Math.hypot(g.start.x - source.x, g.start.y - source.y)).toBeCloseTo(NODE_R + 14);
    expect(Math.hypot(g.end.x - target.x, g.end.y - target.y)).toBeCloseTo(NODE_R + 14);
    const moveTo = vi.fn(), lineTo = vi.fn();
    const ctx = new Proxy({ moveTo, lineTo }, { get: (o, k) => o[k as keyof typeof o] ?? (() => {}) }) as unknown as CanvasRenderingContext2D;
    drawNetworkLink(ctx, { id: "ab", source: a, target: b, type: "delegation" }, zoom, { focused: false, dimmed: false, simulated: false });
    const tip = moveTo.mock.calls.at(-1)!, wing = lineTo.mock.calls[1];
    // Project arrow length onto the parent → child direction; screen size does not shrink at overview zoom.
    expect(((tip[0] - wing[0]) * g.ux + (tip[1] - wing[1]) * g.uy) * zoom).toBeCloseTo(9);
  });

  it("does not paint inverted arrows when users pin nodes on top of each other", () => {
    const [a, b] = nodes(); Object.assign(b, { x: 20, y: 20 });
    expect(linkGeometry(a, b, 1)).toBeNull();
  });

  it.each(["new-delegation", "newly-observed"] as const)("labels %s as synthetic only in demo mode", observation => {
    const [a, b] = nodes(); const fillText = vi.fn();
    const ctx = new Proxy({ fillText, measureText: () => ({ width: 100 }) }, { get: (o, k) => o[k as keyof typeof o] ?? (() => {}) }) as unknown as CanvasRenderingContext2D;
    for (const simulated of [false, true]) {
      fillText.mockClear();
      drawNetworkLink(ctx, { id: "ab", source: a, target: b, type: "delegation" }, 1, { focused: false, dimmed: false, observation, simulated });
      expect(fillText.mock.calls[0][0]).toBe(`${simulated ? "DEMO · " : ""}${observation === "new-delegation" ? "NEW DELEGATION" : "Newly observed"}`);
    }
  });
});
