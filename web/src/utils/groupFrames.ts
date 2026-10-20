import type { Node as ActivityNode } from "@shared/types";

export const NODE_WIDTH = 180;
export const NODE_HEIGHT = 64;
const FRAME_PADDING = 24;
const FRAME_LABEL_HEIGHT = 20;

export interface GroupFrameRect {
  id: string;
  label: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

function boundsForNodes(nodes: ActivityNode[]): {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
} | null {
  if (nodes.length === 0) return null;
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const n of nodes) {
    minX = Math.min(minX, n.layout.x);
    minY = Math.min(minY, n.layout.y);
    maxX = Math.max(maxX, n.layout.x + NODE_WIDTH);
    maxY = Math.max(maxY, n.layout.y + NODE_HEIGHT);
  }
  return { minX, minY, maxX, maxY };
}

export function buildGroupFrames(nodes: ActivityNode[]): GroupFrameRect[] {
  const frames: GroupFrameRect[] = [];

  const buildNodes = nodes.filter((n) => n.group === "build");
  const buildBounds = boundsForNodes(buildNodes);
  if (buildBounds) {
    frames.push({
      id: "frame-build",
      label: "Build",
      x: buildBounds.minX - FRAME_PADDING,
      y: buildBounds.minY - FRAME_PADDING - FRAME_LABEL_HEIGHT,
      width: buildBounds.maxX - buildBounds.minX + FRAME_PADDING * 2,
      height:
        buildBounds.maxY -
        buildBounds.minY +
        FRAME_PADDING * 2 +
        FRAME_LABEL_HEIGHT,
    });
  }

  const qrNodes = nodes.filter((n) => n.group === "qr");
  const qrBounds = boundsForNodes(qrNodes);
  if (qrBounds) {
    frames.push({
      id: "frame-qr",
      label: "Q&R",
      x: qrBounds.minX - FRAME_PADDING,
      y: qrBounds.minY - FRAME_PADDING - FRAME_LABEL_HEIGHT,
      width: qrBounds.maxX - qrBounds.minX + FRAME_PADDING * 2,
      height:
        qrBounds.maxY - qrBounds.minY + FRAME_PADDING * 2 + FRAME_LABEL_HEIGHT,
    });
  }

  return frames;
}
