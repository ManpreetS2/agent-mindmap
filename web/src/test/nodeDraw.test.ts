import { describe, expect, it, vi } from "vitest";
import type { Status } from "@shared/types";
import { drawNode, hexA, NODE_R, STATUS_COLOR } from "../utils/nodeDraw";
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

  it("helpers", () => {
    expect(hexA("#ff0000", 0.5)).toBe("rgba(255,0,0,0.5)");
    expect(NODE_R).toBeGreaterThan(8);
  });
});
