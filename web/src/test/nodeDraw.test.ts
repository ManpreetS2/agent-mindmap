import { describe, expect, it, vi } from "vitest";
import type { Status } from "@shared/types";
import { drawNode, bodyPath, drawTag, linkCaptionPosition, hexA, NODE_R, STATUS_COLOR, containsNode, fitText, layoutLabels } from "../utils/nodeDraw";
import type { GNode } from "../utils/networkModel";

function ctx() {
  const calls: string[] = [];
  const proxy = new Proxy({} as Record<string, unknown>, {
    get: (_, k: string) => {
      if (k === "createRadialGradient") return () => ({ addColorStop: vi.fn() });
      if (k === "measureText") return () => ({ width: 40 });
      return (...a: unknown[]) => { calls.push(`${k}`); return a; };
    },
    set: (_, k: string, v) => { calls.push(`set:${k}=${String(v)}`); return true; },
  });
  return { c: proxy as unknown as CanvasRenderingContext2D, calls };
}
const node = (over: Partial<GNode> = {}): GNode => ({
  id: "a", label: "A", provider: "claude", providerName: "Claude", model: "m", status: "IN_PROGRESS", reported: "running",
  task: "Do the thing", active: true, stale: false, phase: 0.3, pinned: false, x: 10, y: 20, ...over,
});
const st = { t: 1000, selected: false, alpha: 1, hovered: false, flash: null, zoom: 1 };

describe("drawNode", () => {
  it.each([0.1, 0.6, 1, 1.8, 6])("keeps captions at nine screen pixels at zoom %s", zoom => {
    const { c, calls } = ctx();
    drawTag(c, "RESUMED", 0, 0, "#fff", zoom);
    const font = calls.find(v => v.startsWith("set:font="))!;
    expect(Number(font.match(/700 ([\d.]+)px/)![1]) * zoom).toBeCloseTo(9);
    for (const [x, y] of [[150, 0], [0, 150], [100, 100], [-100, 100]]) {
      const s = node({ x: 0, y: 0 }), t = node({ x, y });
      const w = 100 / zoom, h = 16 / zoom;
      const pos = linkCaptionPosition(s, t, w, h, zoom);
      // All four corners lie on the same side of the arrow line, with 12px clearance.
      const distances = [-1, 1].flatMap(sx => [-1, 1].map(sy =>
        ((pos.x + sx * w / 2) * y - (pos.y + sy * h / 2) * x) / Math.hypot(x, y)));
      expect(Math.min(...distances.map(Math.abs)) * zoom).toBeCloseTo(12);
      expect(distances.every(d => Math.sign(d) === Math.sign(distances[0]))).toBe(true);
    }
  });
  it("culls crowded labels at 85px spacing and never masks neighbouring bodies", () => {
    const nodes = Array.from({ length: 30 }, (_, i) => node({ id: String(i), x: (i % 5) * 85, y: Math.floor(i / 5) * 85 }));
    const labels = layoutLabels(nodes, 1.5, "12");
    expect(labels.size).toBeGreaterThan(0);
    expect(labels.size).toBeLessThan(30);
    expect(labels.has("12")).toBe(true);
    for (const [id, l] of labels) for (const n of nodes) {
      if (id === n.id) continue;
      expect(Math.abs(n.x! - l.x) >= 110 || n.y! + 28 <= l.y - 2 || n.y! - 28 >= l.y - 2 + l.height).toBe(true);
    }
    expect(layoutLabels(nodes, 0.4).size).toBe(0);
    expect([...layoutLabels(nodes, 0.7).values()].every(l => l.lines === 1)).toBe(true);
  });
  it("uses a circle for Claude and a six-sided polygon for Codex", () => {
    const arc = vi.fn(), lineTo = vi.fn(), moveTo = vi.fn();
    const c = { arc, lineTo, moveTo, beginPath() {}, closePath() {} } as unknown as CanvasRenderingContext2D;
    bodyPath(c, node({ provider: "claude" }), NODE_R);
    expect(arc).toHaveBeenCalledTimes(1);
    expect(lineTo).not.toHaveBeenCalled();
    arc.mockClear();
    bodyPath(c, node({ provider: "codex" }), NODE_R);
    expect(arc).not.toHaveBeenCalled();
    expect(moveTo).toHaveBeenCalledTimes(1);
    expect(lineTo).toHaveBeenCalledTimes(5);
  });

  it("status is encoded by distinct glyphs even with the same body/provider", () => {
    const paths = ["FAILED", "DONE", "BLOCKED", "IN_PROGRESS", "IDLE"].map(status => {
      const { c, calls } = ctx();
      drawNode(c, node({ status: status as Status, active: false }), { ...st, t: null, label: null });
      return calls.filter(v => ["beginPath", "moveTo", "lineTo", "fillRect", "arc", "closePath", "fill", "stroke"].includes(v)).join("|");
    });
    expect(new Set(paths).size).toBe(5);
  });

  it("reduced-motion reactions keep a static ring and caption with no pulse or fade", () => {
    const early = ctx(), later = ctx();
    drawNode(early.c, node(), { ...st, t: null, flash: { caption: "STARTED", age: 100, color: "#ffffff" } });
    drawNode(later.c, node(), { ...st, t: null, flash: { caption: "STARTED", age: 1800, color: "#ffffff" } });
    expect(later.calls).toEqual(early.calls);
    expect(early.calls).toContain("set:lineWidth=2");
    expect(early.calls).toContain("fillText");
  });

  it("draws every status and provider without throwing and balances save/restore", () => {
    for (const status of Object.keys(STATUS_COLOR) as Status[]) {
      for (const provider of ["claude", "codex", "other", "unknown"] as const) {
        const { c, calls } = ctx();
        drawNode(c, node({ status, provider, active: status === "IN_PROGRESS" }), st);
        expect(calls.filter((x) => x === "save")).toHaveLength(calls.filter((x) => x === "restore").length);
      }
    }
  });

  it("only animates (halo/orbit) when motion is on and the agent is active", () => {
    const moving = ctx(); drawNode(moving.c, node(), st);
    const still = ctx(); drawNode(still.c, node(), { ...st, t: null });
    const idle = ctx(); drawNode(idle.c, node({ active: false, status: "DONE" }), st);
    expect(moving.calls.filter((x) => x === "arc").length).toBeGreaterThan(still.calls.filter((x) => x === "arc").length);
    expect(idle.calls.filter((x) => x === "arc").length).toBeLessThanOrEqual(still.calls.filter((x) => x === "arc").length);
  });

  it("draws the observed-change caption only while it is fresh and uses text for unknown models", () => {
    const fresh = ctx();
    drawNode(fresh.c, node({ model: null }), { ...st, flash: { caption: "FAILED", age: 200, color: "#f00" } });
    expect(fresh.calls).toContain("fillText");
    const old = ctx();
    drawNode(old.c, node(), { ...st, zoom: 0.3, flash: { caption: "X", age: 5000, color: "#f00" } });
    expect(old.calls).not.toContain("fillText"); // zoomed-out labels hidden, stale flash ignored
  });

  it("hit tests the moving circle/hexagon and excludes hex corners", () => {
    const circle = node({ x: 0, y: 0, ox: 3, oy: -2 });
    expect(containsNode(circle, 3, -2)).toBe(true);
    expect(containsNode(circle, -3 - (NODE_R + 8), -2)).toBe(false); // just outside ring + gutter
    const hex = node({ provider: "codex", x: 0, y: 0, active: false });
    expect(containsNode(hex, 0, 21)).toBe(true);
    expect(containsNode(hex, 19, 19)).toBe(false);
    hex.x = 100;
    expect(containsNode(hex, 0, 0)).toBe(false);
    expect(containsNode(hex, 100, 0)).toBe(true);
  });

  it("bounds long text and caches measurements", () => {
    const measureText = vi.fn((text: string) => ({ width: text.length * 7 }));
    const c = { font: "unique-test-font", measureText } as unknown as CanvasRenderingContext2D;
    const text = "A very long model or task that should never overlap its neighbour";
    const clipped = fitText(c, text, 154);
    expect(clipped.endsWith("…")).toBe(true);
    expect(clipped.length * 7).toBeLessThanOrEqual(154);
    const calls = measureText.mock.calls.length;
    expect(fitText(c, text, 154)).toBe(clipped);
    expect(measureText).toHaveBeenCalledTimes(calls);
  });

  it("helpers", () => {
    expect(hexA("#ff0000", 0.5)).toBe("rgba(255,0,0,0.5)");
    expect(NODE_R).toBeGreaterThan(8);
  });
});
