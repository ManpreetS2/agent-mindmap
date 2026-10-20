/**
 * Visual-only link: multi-group agent → secondary group anchor.
 */
import { BaseEdge, getStraightPath, type EdgeProps } from "@xyflow/react";

export type MembershipEdgeData = {
  tooltip?: string;
};

export function MembershipEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  style,
  data,
}: EdgeProps) {
  const edgeData = (data ?? {}) as MembershipEdgeData;
  const [edgePath] = getStraightPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
  });

  return (
    <>
      <title>{edgeData.tooltip ?? "Multi-group membership"}</title>
      <BaseEdge
        id={id}
        path={edgePath}
        style={style}
        interactionWidth={12}
        className="membership-edge"
      />
      {/* Stable test hook — BaseEdge path is the interactive stroke */}
      <path
        d={edgePath}
        fill="none"
        stroke="transparent"
        strokeWidth={8}
        data-testid={`membership-edge-${id}`}
      />
    </>
  );
}
