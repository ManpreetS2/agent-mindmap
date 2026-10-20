import { describe, expect, it } from "vitest";
import {
  brushDomainFromRatio,
  clampDomain,
  zoomDomain,
} from "../utils/timelineBrush";

const full = { minMs: 1000, maxMs: 5000 };

describe("timelineBrush", () => {
  it("zooms around center and clamps to full domain", () => {
    const zoomed = zoomDomain({ minMs: 2000, maxMs: 4000 }, full, 0.5);
    expect(zoomed.maxMs - zoomed.minMs).toBe(1000);
    expect(zoomed.minMs).toBeGreaterThanOrEqual(full.minMs);
    expect(zoomed.maxMs).toBeLessThanOrEqual(full.maxMs);
  });

  it("builds brush domain from ratios", () => {
    const d = brushDomainFromRatio(full, 0.25, 0.75);
    expect(d.minMs).toBe(2000);
    expect(d.maxMs).toBe(4000);
  });

  it("clampDomain keeps window inside full", () => {
    const c = clampDomain({ minMs: -100, maxMs: 900 }, full);
    expect(c.minMs).toBe(full.minMs);
  });
});
