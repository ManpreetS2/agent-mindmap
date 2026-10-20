import { describe, expect, it } from "vitest";
import type { Node as FlowNode } from "@xyflow/react";
import {
  agentStructureKey,
  collectDraggedIds,
  mergeFlowNodes,
} from "../utils/mergeFlowNodes";

function agent(
  id: string,
  x: number,
  y: number,
  group = "build",
  groups: string[] = [group],
): FlowNode {
  return {
    id,
    type: "agent",
    position: { x, y },
    data: { node: { id, group, groups } },
  };
}

function anchor(id: string, x: number, y: number): FlowNode {
  return {
    id,
    type: "groupAnchor",
    position: { x, y },
    data: { groupId: id.replace("group:", ""), label: id },
  };
}

describe("mergeFlowNodes (QA-MM020f-1)", () => {
  it("preserves user-dragged agent positions across layout rebuilds", () => {
    const prev = [agent("director", 188, 313), agent("architect", 40, 100)];
    const built = [agent("director", 40, 216), agent("architect", 40, 100)];
    const dragged = new Set(["director"]);

    const merged = mergeFlowNodes(prev, built, dragged);
    expect(merged.find((n) => n.id === "director")?.position).toEqual({
      x: 188,
      y: 313,
    });
    expect(merged.find((n) => n.id === "architect")?.position).toEqual({
      x: 40,
      y: 100,
    });
  });

  it("does not treat a drag delta as a full layout reset", () => {
    // Same bug pattern as AgentGraph: prev has dragged coords, built has layout.
    const prev = [agent("director", 188, 313)];
    const built = [agent("director", 40, 216)];
    const merged = mergeFlowNodes(prev, built, new Set(["director"]));
    expect(merged).toHaveLength(1);
    expect(merged[0].position).toEqual({ x: 188, y: 313 });
    // Data still refreshed from built
    expect(merged[0].data).toBe(built[0].data);
  });

  it("places brand-new agents at layout positions", () => {
    const prev = [agent("director", 10, 10)];
    const built = [agent("director", 10, 10), agent("dev-1", 200, 200)];
    const merged = mergeFlowNodes(prev, built, new Set());
    expect(merged.find((n) => n.id === "dev-1")?.position).toEqual({
      x: 200,
      y: 200,
    });
  });

  it("re-layouts structurally changed agents that were not dragged", () => {
    const prev = [agent("director", 10, 10, "build", ["build"])];
    const built = [agent("director", 400, 80, "qr", ["qr", "build"])];
    const merged = mergeFlowNodes(prev, built, new Set());
    expect(merged[0].position).toEqual({ x: 400, y: 80 });
    expect(agentStructureKey(prev[0])).not.toBe(agentStructureKey(built[0]));
  });

  it("keeps dragged position even when structure changes", () => {
    const prev = [agent("director", 188, 313, "build", ["build"])];
    const built = [agent("director", 400, 80, "qr", ["qr"])];
    const merged = mergeFlowNodes(prev, built, new Set(["director"]));
    expect(merged[0].position).toEqual({ x: 188, y: 313 });
  });

  it("always applies layout positions for group anchors", () => {
    const prev = [anchor("group:build", 0, 0), agent("dev-1", 50, 50)];
    const built = [anchor("group:build", 120, 40), agent("dev-1", 50, 50)];
    const merged = mergeFlowNodes(prev, built, new Set(["dev-1"]));
    expect(merged.find((n) => n.id === "group:build")?.position).toEqual({
      x: 120,
      y: 40,
    });
  });

  it("collectDraggedIds records position changes while dragging", () => {
    const ids = collectDraggedIds(
      [
        { type: "position", id: "director", dragging: true },
        { type: "position", id: "director", dragging: false },
      ],
      new Set(),
    );
    expect(ids.has("director")).toBe(true);
  });
});
