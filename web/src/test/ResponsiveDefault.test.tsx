import { renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useResponsiveListDefault } from "../hooks/useResponsiveView";

function mockMedia(matches: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches, media: query, addEventListener: vi.fn(), removeEventListener: vi.fn(),
    addListener: vi.fn(), removeListener: vi.fn(), onchange: null, dispatchEvent: vi.fn(),
  }));
}
afterEach(() => vi.unstubAllGlobals());

describe("useResponsiveListDefault", () => {
  it("is true on the very first render at a phone width (no graph-view flash)", () => {
    mockMedia(true);
    const seen: boolean[] = [];
    renderHook(() => { const v = useResponsiveListDefault(); seen.push(v); return v; });
    expect(seen[0]).toBe(true);
  });
  it("is false on the first render at desktop widths", () => {
    mockMedia(false);
    const seen: boolean[] = [];
    renderHook(() => { const v = useResponsiveListDefault(); seen.push(v); return v; });
    expect(seen[0]).toBe(false);
  });
});
