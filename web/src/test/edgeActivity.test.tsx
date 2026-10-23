import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { isEvidenced, newlyObservedEdgeIds, sourceKey, FRESH_EDGE_MS } from "../utils/edgeActivity";
import { useFreshEdges } from "../hooks/useFreshEdges";
import { delegation, sessionNode, t3Activity } from "./helpers";

const a = sessionNode("a"), b = sessionNode("b"), c = sessionNode("c");

describe("newly observed verified edges", () => {
  it("never treats the baseline load as new", () => {
    expect(newlyObservedEdgeIds(null, t3Activity([a, b], [["a", "b"]])).size).toBe(0);
  });
  it("flags only delegation edges first seen after the baseline", () => {
    const act = t3Activity([a, b, c], [["a", "b"], ["a", "c"]]);
    expect([...newlyObservedEdgeIds(new Set(["delegation-b"]), act)]).toEqual(["delegation-c"]);
  });
  it("requires an evidence event present in the snapshot", () => {
    const act = t3Activity([a, b], [["a", "b"]]);
    act.events = act.events.filter((e) => e.id !== "delegation-b");
    expect(isEvidenced(act.edges[0], act)).toBe(false);
    expect(newlyObservedEdgeIds(new Set(), act).size).toBe(0);
  });
  it("source or mode switches are separate baselines", () => {
    expect(sourceKey(t3Activity([a], [], "live"))).not.toBe(sourceKey(t3Activity([a], [], "demo")));
  });
});

describe("useFreshEdges", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("highlights a new edge once, expires it, and ignores historical edges and mode switches", () => {
    const base = t3Activity([a, b, c], [["a", "b"]]);
    const { result, rerender } = renderHook(({ act }) => useFreshEdges(act), { initialProps: { act: base } });
    expect(result.current.size).toBe(0); // baseline

    rerender({ act: t3Activity([a, b, c], [["a", "b"], ["a", "c"]]) });
    expect([...result.current.keys()]).toEqual(["delegation-c"]);

    // repeated polls must not extend or re-trigger the highlight
    act(() => { vi.advanceTimersByTime(FRESH_EDGE_MS - 100); });
    rerender({ act: t3Activity([a, b, c], [["a", "b"], ["a", "c"]]) });
    expect(result.current.has("delegation-c")).toBe(true);
    act(() => { vi.advanceTimersByTime(200); });
    expect(result.current.size).toBe(0);

    // a different mode is a fresh baseline: nothing animates
    rerender({ act: t3Activity([a, b, c], [["a", "b"], ["a", "c"]], "demo") });
    expect(result.current.size).toBe(0);
    expect(delegation("a", "b").edge.type).toBe("delegation");
  });
});

describe("delegation evidence timing", () => {
  it.each(["continuous", "old", "outage", "stale", "gap", "invalid"] as const)("classifies %s observation without inventing new work", scenario => {
    const base = t3Activity([a, b], []);
    if (scenario === "outage") base.meta.t3!.connection = "unavailable";
    if (scenario === "stale") base.nodes = [sessionNode("a", { status: "STALE" }), b];
    const { result, rerender } = renderHook(({ activity }) => useFreshEdges(activity), { initialProps: { activity: base } });
    const next = t3Activity([a, b], [["a", "b"]]);
    next.events.find(e => e.id === "delegation-b")!.source_time = scenario === "old" ? "2026-10-22T19:59:58Z" : scenario === "invalid" ? "invalid" : base.generated_at;
    if (scenario === "gap") next.generated_at = "2026-10-22T20:10:00Z";
    rerender({ activity: next });
    expect(result.current.get("delegation-b")).toBe(scenario === "continuous" ? "new-delegation" : "newly-observed");
  });

  it("reconnects with identical edges without highlighting them", () => {
    const base = t3Activity([a, b], [["a", "b"]]);
    const { result, rerender } = renderHook(({ activity }) => useFreshEdges(activity), { initialProps: { activity: base } });
    const offline = structuredClone(base); offline.meta.t3!.connection = "unavailable";
    rerender({ activity: offline }); rerender({ activity: structuredClone(base) });
    expect(result.current.size).toBe(0);
  });
});
