import type { Node as ActivityNode } from "@shared/types";
import type { ClusterBounds } from "./graphLayout";
import { labelForGroup } from "./groupMembership";

export const NODE_WIDTH = 180;
/** Minimum card height; layout uses LAYOUT_NODE_HEIGHT from graphLayout. */
export const NODE_HEIGHT = 88;

export interface GroupFrameRect {
  id: string;
  groupId: string;
  label: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

/** Build glass cluster frames from multi-group layout clusters. */
export function buildGroupFramesFromClusters(
  clusters: ClusterBounds[],
  visibleGroupIds: ReadonlySet<string> | null = null,
): GroupFrameRect[] {
  return clusters
    .filter((c) => !visibleGroupIds || visibleGroupIds.has(c.id))
    .map((c) => ({
      id: `frame-${c.id}`,
      groupId: c.id,
      label: labelForGroup(c.id),
      x: c.x,
      y: c.y,
      width: c.width,
      height: c.height,
    }));
}

/**
 * Legacy frames from primary `group` only (1.0.0 fixtures without clusters).
 * Kept for callers that still pass laid-out nodes without cluster metadata.
 */
export function buildGroupFrames(nodes: ActivityNode[]): GroupFrameRect[] {
  const frames: GroupFrameRect[] = [];
  const pad = 24;
  const labelH = 20;

  for (const [groupId, label] of [
    ["build", "Build"],
    ["qr", "Q&R"],
  ] as const) {
    const members = nodes.filter((n) => n.group === groupId);
    if (members.length === 0) continue;
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    for (const n of members) {
      minX = Math.min(minX, n.layout.x);
      minY = Math.min(minY, n.layout.y);
      maxX = Math.max(maxX, n.layout.x + NODE_WIDTH);
      maxY = Math.max(maxY, n.layout.y + NODE_HEIGHT);
    }
    frames.push({
      id: `frame-${groupId}`,
      groupId,
      label,
      x: minX - pad,
      y: minY - pad - labelH,
      width: maxX - minX + pad * 2,
      height: maxY - minY + pad * 2 + labelH,
    });
  }
  return frames;
}
