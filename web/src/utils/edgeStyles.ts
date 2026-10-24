import type { EdgeType } from "@shared/types";

export interface EdgeVisual {
  stroke: string;
  strokeDasharray?: string;
  label: string;
}

export const EDGE_VISUALS: Record<EdgeType, EdgeVisual> = {
  delegation: { stroke: "var(--edge-delegation)", label: "Verified T3 delegation (parent → child)" },
  handoff: { stroke: "var(--edge-handoff)", label: "Handoff / assignment" },
  verdict: {
    stroke: "var(--edge-verdict)",
    strokeDasharray: "8 4",
    label: "Review verdict",
  },
  pr: {
    stroke: "var(--edge-pr)",
    strokeDasharray: "2 4",
    label: "PR link",
  },
  merge: { stroke: "var(--edge-merge)", label: "Merge" },
};

export function strokeWidthForCount(count: number): number {
  return Math.min(3, Math.max(1, count));
}

