import { describe, expect, it } from "vitest";
import { agentMetrics, sourceKind } from "../utils/headerMetrics";
import { sessionNode, t3Activity } from "./helpers";

describe("agentMetrics", () => {
  it("counts agents by status and delegation relationships (not handoffs)", () => {
    const act = t3Activity(
      [sessionNode("a", { status: "IN_PROGRESS" }), sessionNode("b", { status: "BLOCKED" }),
        sessionNode("c", { status: "FAILED" }), sessionNode("d", { status: "DONE" }), sessionNode("e", { status: "STALE" })],
      [["a", "b"], ["a", "c"]],
    );
    expect(agentMetrics(act)).toEqual({ total: 5, working: 1, blocked: 1, failed: 1, done: 1, other: 1, delegations: 2 });
  });
  it("is honest for an empty network", () => {
    expect(agentMetrics(t3Activity([], []))).toMatchObject({ total: 0, delegations: 0 });
  });
});

describe("sourceKind", () => {
  it("never calls demo or replay data live", () => {
    expect(sourceKind(t3Activity([], [], "demo"))).toBe("demo");
    expect(sourceKind(t3Activity([], [], "demo", { stage: 0, stage_count: 10, cycle: 0, step_sec: 5, label: "x" }))).toBe("replay");
    expect(sourceKind(t3Activity([], [], "live"))).toBe("live");
    expect(sourceKind(t3Activity([], [], "live", undefined, "unavailable"))).toBe("unavailable");
  });
});
