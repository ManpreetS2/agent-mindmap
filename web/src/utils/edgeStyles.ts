import type { EdgeType } from "@shared/types";

export interface EdgeVisual {
  stroke: string;
  strokeDasharray?: string;
  label: string;
}

export const EDGE_VISUALS: Record<EdgeType, EdgeVisual> = {
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
  message: {
    stroke: "var(--edge-message)",
    strokeDasharray: "5 4",
    label: "Message",
  },
};

/** Membership links (UI-only, not an Activity EdgeType). */
export const MEMBERSHIP_EDGE_VISUAL: EdgeVisual = {
  stroke: "var(--edge-membership)",
  strokeDasharray: "3 5",
  label: "Multi-group membership",
};

export function strokeWidthForCount(count: number): number {
  return Math.min(3, Math.max(1, count));
}
