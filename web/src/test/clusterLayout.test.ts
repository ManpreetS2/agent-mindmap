import { describe, expect, it } from "vitest";
import type { Activity, Edge, Node } from "@shared/types";
import {
  findOverlappingPairs,
  layoutMultiGroupClusters,
  LAYOUT_NODE_HEIGHT,
  LAYOUT_NODE_WIDTH,
  MIN_NODE_GAP,
  nodeRectsFromPositions,
} from "../utils/graphLayout";
import { groupsForNode } from "../utils/groupMembership";

function node(
  id: string,
  group: Node["group"],
  groups: string[],
  x = 0,
  y = 0,
): Node {
  return {
    id,
    label: id,
    group,
    groups,
    status: "IDLE",
    agent_links: [],
    layout: { x, y },
  };
}

const multiNodes: Node[] = [
  node("director", "build", ["build", "qr", "radar"]),
  node("architect", "build", ["build", "qr", "radar"]),
  node("dev-1", "build", ["build"]),
  node("dev-2", "build", ["build"]),
  node("qa-verifier", "qr", ["qr"]),
  node("security-engineer", "qr", ["qr"]),
  node("scout", "radar", ["radar"]),
  node("skeptic", "radar", ["radar"]),
];

const multiEdges: Edge[] = [
  {
    id: "e-handoff",
    source: "architect",
    target: "dev-1",
    type: "handoff",
    count: 1,
    event_ids: ["ev1"],
  },
  {
    id: "e-msg-group",
    source: "director",
    target: "group:build",
    type: "message",
    count: 1,
    event_ids: ["ev2"],
  },
  {
    id: "e-msg-bot",
    source: "architect",
    target: "qa-verifier",
    type: "message",
    count: 1,
    event_ids: ["ev3"],
  },
];

describe("layoutMultiGroupClusters (MM-020f)", () => {
  it("places each agent once (no duplicated identities)", () => {
    const result = layoutMultiGroupClusters(multiNodes, multiEdges);
    expect(result.positions.size).toBe(multiNodes.length);
    for (const n of multiNodes) {
      expect(result.positions.get(n.id)).toBeTruthy();
    }
  });

  it("keeps ≥24px gap between agent bounding boxes", () => {
    const result = layoutMultiGroupClusters(multiNodes, multiEdges);
    const rects = nodeRectsFromPositions(multiNodes, result.positions);
    expect(findOverlappingPairs(rects, MIN_NODE_GAP)).toEqual([]);
  });

  it("creates a cluster per group and membership links for multi-group agents", () => {
    const result = layoutMultiGroupClusters(multiNodes, multiEdges);
    const ids = result.clusters.map((c) => c.id).sort();
    expect(ids).toEqual(["build", "qr", "radar"]);
    expect(result.groupAnchors.has("build")).toBe(true);
    expect(result.groupAnchors.has("qr")).toBe(true);

    const directorLinks = result.membershipLinks.filter(
      (l) => l.botId === "director",
    );
    expect(directorLinks.map((l) => l.groupId).sort()).toEqual(["qr", "radar"]);
    // Single-group agents have no membership links
    expect(
      result.membershipLinks.some((l) => l.botId === "dev-1"),
    ).toBe(false);
  });

  it("lays out home-group members inside distinct cluster regions", () => {
    const result = layoutMultiGroupClusters(multiNodes, multiEdges);
    const build = result.clusters.find((c) => c.id === "build")!;
    const qr = result.clusters.find((c) => c.id === "qr")!;
    const director = result.positions.get("director")!;
    const qa = result.positions.get("qa-verifier")!;

    // Director (home=build) falls in build cluster AABB (with pad).
    expect(director.x).toBeGreaterThanOrEqual(build.x - 2);
    expect(director.y).toBeGreaterThanOrEqual(build.y - 2);
    expect(director.x + LAYOUT_NODE_WIDTH).toBeLessThanOrEqual(
      build.x + build.width + LAYOUT_NODE_WIDTH,
    );

    expect(qa.x).toBeGreaterThanOrEqual(qr.x - 2);
    expect(qa.y).toBeGreaterThanOrEqual(qr.y - 2);

    // Build and Q&R clusters should not be identical origins.
    expect(build.x !== qr.x || build.y !== qr.y).toBe(true);
  });

  it("groupsForNode falls back to primary group when groups[] missing", () => {
    const legacy = node("dev-1", "build", []);
    delete (legacy as { groups?: string[] }).groups;
    expect(groupsForNode(legacy)).toEqual(["build"]);
  });

  it("empty groups[] means standalone (not primary-group frame)", () => {
    const owner = node("manpreet", "owner", []);
    expect(groupsForNode(owner)).toEqual([]);
  });
});

describe("sample activity still layouts without multi-membership", () => {
  it("empty membership links when no groups[] arrays", () => {
    const activity = {
      nodes: [
        node("a", "build", []),
        node("b", "qr", []),
      ],
      edges: [] as Edge[],
    } as Pick<Activity, "nodes" | "edges">;
    // Clear groups to simulate 1.0.0
    for (const n of activity.nodes) {
      delete (n as { groups?: string[] }).groups;
    }
    const result = layoutMultiGroupClusters(activity.nodes, activity.edges);
    expect(result.membershipLinks).toEqual([]);
    expect(result.positions.size).toBe(2);
    void LAYOUT_NODE_HEIGHT;
  });
});
