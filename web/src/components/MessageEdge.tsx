/**
 * MM-020f: message edges (bot↔bot or sender→group:{id}).
 * Distinct from handoff — no particles; cyan dashed stroke + provenance tooltip.
 */
import {
  BaseEdge,
  EdgeLabelRenderer,
  getBezierPath,
  type EdgeProps,
} from "@xyflow/react";

export type MessageEdgeData = {
  labelText?: string;
  tooltip?: string;
  reduceMotion?: boolean;
  glow?: boolean;
};

export function MessageEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  style,
  markerEnd,
  data,
}: EdgeProps) {
  const edgeData = (data ?? {}) as MessageEdgeData;
  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
  });

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        markerEnd={markerEnd}
        style={{
          ...style,
          filter: edgeData.glow
            ? "drop-shadow(0 0 4px hsl(187 92% 55% / 0.85))"
            : undefined,
        }}
      />
      <EdgeLabelRenderer>
        <div
          className="edge-tooltip-label edge-tooltip-label--message nodrag nopan"
          data-testid={`message-edge-label-${id}`}
          style={{
            transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
          }}
          title={edgeData.tooltip}
        >
          {edgeData.labelText}
        </div>
      </EdgeLabelRenderer>
    </>
  );
}
