import { describe, expect, it } from "vitest";
import type { Activity } from "@shared/types";
import fixture from "../../../fixtures/sample-activity.json";
import {
  findOverlappingPairs,
  layoutNodesWithDagre,
  MIN_NODE_GAP,
  nodeRectsFromPositions,
} from "../utils/graphLayout";

const activity = fixture as Activity;

describe("graphLayout (MM-012 polish)", () => {
  it("layout produces no overlapping node bounding boxes (gap >= 24px)", () => {
    const positions = layoutNodesWithDagre(activity.nodes, activity.edges);
    const rects = nodeRectsFromPositions(activity.nodes, positions);
    const overlaps = findOverlappingPairs(rects, MIN_NODE_GAP);
    expect(overlaps).toEqual([]);
    // Every node has a finite position
    for (const n of activity.nodes) {
      expect(positions.get(n.id)).toBeTruthy();
    }
  });

  it("raw fixture layout still overlaps (documents why layout pass exists)", () => {
    const raw = new Map(
      activity.nodes.map((n) => [n.id, { x: n.layout.x, y: n.layout.y }]),
    );
    const rects = nodeRectsFromPositions(activity.nodes, raw);
    const overlaps = findOverlappingPairs(rects, MIN_NODE_GAP);
    expect(overlaps.length).toBeGreaterThan(0);
  });
});
