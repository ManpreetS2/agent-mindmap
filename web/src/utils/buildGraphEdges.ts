import { MarkerType, type Edge as FlowEdge } from "@xyflow/react";
import type { Activity, Edge } from "@shared/types";
import {
  EDGE_VISUALS,
  MEMBERSHIP_EDGE_VISUAL,
  strokeWidthForCount,
} from "./edgeStyles";
import { edgeTouchesVisibleAgents, tooltipForEdge } from "./edgeTooltip";
import type { MembershipLink } from "./graphLayout";
import { groupTargetId, labelForGroup } from "./groupMembership";

const RECENT_HANDOFF_MS = 36 * 60 * 60 * 1000;

function isRecentHandoff(
  edge: Edge,
  events: Activity["events"],
  nowMs: number,
): boolean {
  if (edge.type !== "handoff") return false;
  const byId = new Map(events.map((e) => [e.id, e]));
  return edge.event_ids.some((id) => {
    const ev = byId.get(id);
    if (!ev) return false;
    const t = new Date(ev.source_time).getTime();
    return !Number.isNaN(t) && nowMs - t <= RECENT_HANDOFF_MS;
  });
}

export interface BuildGraphEdgesOptions {
  activity: Activity;
  visibleAgentIds: ReadonlySet<string>;
  selectedGroups: ReadonlySet<string>;
  membershipLinks: MembershipLink[];
  lifecycleActive: boolean;
  lifecycleEdgeIds: ReadonlySet<string> | null;
  reduceMotion: boolean;
  nowMs: number;
}

/** Pure builder for React Flow edges (activity + membership). */
export function buildGraphEdges(opts: BuildGraphEdgesOptions): FlowEdge[] {
  const {
    activity,
    visibleAgentIds,
    selectedGroups,
    membershipLinks,
    lifecycleActive,
    lifecycleEdgeIds,
    reduceMotion,
    nowMs,
  } = opts;

  const activityEdges: FlowEdge[] = activity.edges
    .filter((e) =>
      edgeTouchesVisibleAgents(e, visibleAgentIds, selectedGroups),
    )
    .map((e) => {
      const visual = EDGE_VISUALS[e.type];
      const dimmed =
        lifecycleActive && lifecycleEdgeIds !== null && !lifecycleEdgeIds.has(e.id);
      const highlighted =
        lifecycleActive &&
        lifecycleEdgeIds !== null &&
        lifecycleEdgeIds.has(e.id);
      const tooltip = tooltipForEdge(e, activity.events);
      const recent = isRecentHandoff(e, activity.events, nowMs);
      const isMessage = e.type === "message";
      return {
        id: e.id,
        source: e.source,
        target: e.target,
        type: isMessage ? "messageEdge" : "handoffEdge",
        data: {
          labelText: String(e.count),
          tooltip,
          showParticles: !isMessage && recent && !reduceMotion,
          reduceMotion,
          glow: highlighted && !reduceMotion,
        },
        animated: !isMessage && recent && !reduceMotion,
        style: {
          stroke: visual.stroke,
          strokeWidth:
            strokeWidthForCount(e.count) + (highlighted ? 1.5 : 0),
          strokeDasharray: visual.strokeDasharray,
          opacity: dimmed ? 0.2 : 1,
        },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: visual.stroke,
        },
      };
    });

  const membership: FlowEdge[] = [];
  for (const link of membershipLinks) {
    if (!visibleAgentIds.has(link.botId)) continue;
    if (!selectedGroups.has(link.groupId)) continue;
    const id = `membership:${link.botId}:${link.groupId}`;
    membership.push({
      id,
      source: link.botId,
      target: groupTargetId(link.groupId),
      type: "membershipEdge",
      data: {
        tooltip: `${link.botId} also in ${labelForGroup(link.groupId)}`,
      },
      style: {
        stroke: MEMBERSHIP_EDGE_VISUAL.stroke,
        strokeWidth: 1.25,
        strokeDasharray: MEMBERSHIP_EDGE_VISUAL.strokeDasharray,
        opacity: 0.7,
      },
    });
  }

  return [...membership, ...activityEdges];
}
