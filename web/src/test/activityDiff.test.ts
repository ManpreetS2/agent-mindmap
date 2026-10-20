import { describe, expect, it } from "vitest";
import type { Activity, Node } from "@shared/types";
import { patchActivity, statusChangedNodeIds } from "../utils/activityDiff";

const baseNode = (overrides: Partial<Node>): Node => ({
  id: "n1",
  label: "N1",
  group: "build",
  status: "IDLE",
  agent_links: [],
  layout: { x: 0, y: 0 },
  ...overrides,
});

const baseActivity = (overrides: Partial<Activity> = {}): Activity => ({
  schema_version: "1.0.0",
  generated_at: "2026-10-20T04:58:00-07:00",
  project: "fencepost",
  meta: { github: "ok" },
  nodes: [baseNode({})],
  tasks: [],
  events: [
    {
      id: "e1",
      type: "handoff",
      actor: "n1",
      target: "n2",
      task_id: "RP-001",
      attribution: { method: "ledger_owner" },
      source_url: "https://example.com/1",
      source_time: "2026-10-19T21:00:00-07:00",
      raw: "h",
    },
  ],
  edges: [
    {
      id: "edge-1",
      source: "n1",
      target: "n2",
      type: "handoff",
      count: 1,
      event_ids: ["e1"],
    },
  ],
  unparsed: [],
  ...overrides,
});

describe("activityDiff patchActivity (MM-012)", () => {
  it("marks all ids changed on first snapshot", () => {
    const next = baseActivity();
    const patch = patchActivity(null, next);
    expect(patch.changedNodeIds.has("n1")).toBe(true);
    expect(patch.changedEventIds.has("e1")).toBe(true);
    expect(patch.changedEdgeIds.has("edge-1")).toBe(true);
  });

  it("diff-patches by id and only flags changed entities", () => {
    const prev = baseActivity();
    const next = baseActivity({
      generated_at: "2026-10-20T05:10:00-07:00",
      nodes: [baseNode({ status: "IN_PROGRESS", current_task: "RP-001" })],
      events: [
        ...prev.events,
        {
          id: "e2",
          type: "note",
          actor: null,
          target: null,
          task_id: null,
          attribution: { method: "unknown" },
          source_url: "https://example.com/2",
          source_time: "2026-10-19T22:00:00-07:00",
          raw: "n",
        },
      ],
    });
    const patch = patchActivity(prev, next);
    expect(patch.changedNodeIds.has("n1")).toBe(true);
    expect(patch.changedEventIds.has("e2")).toBe(true);
    expect(patch.changedEventIds.has("e1")).toBe(false);
    expect(patch.changedEdgeIds.has("edge-1")).toBe(false);
    expect(patch.generatedAtChanged).toBe(true);
    expect(patch.activity.events).toHaveLength(2);
  });

  it("statusChangedNodeIds only includes status transitions", () => {
    const prev = baseActivity();
    const next = baseActivity({
      nodes: [
        baseNode({ status: "DONE" }),
        baseNode({ id: "n2", label: "N2", status: "IDLE" }),
      ],
    });
    const ids = statusChangedNodeIds(prev, next);
    expect(ids.has("n1")).toBe(true);
    expect(ids.has("n2")).toBe(true);
  });

  it("unchanged snapshot yields empty change sets", () => {
    const prev = baseActivity();
    const next = structuredClone(prev);
    const patch = patchActivity(prev, next);
    expect(patch.changedNodeIds.size).toBe(0);
    expect(patch.changedEventIds.size).toBe(0);
    expect(patch.changedEdgeIds.size).toBe(0);
    expect(patch.generatedAtChanged).toBe(false);
  });
});
