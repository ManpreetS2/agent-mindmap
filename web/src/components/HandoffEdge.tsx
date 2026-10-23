/**
 * Custom React Flow edge with optional particle motion for recent handoffs.
 */
import {
  BaseEdge,
  EdgeLabelRenderer,
  getSmoothStepPath,
  type EdgeProps,
} from "@xyflow/react";

export type HandoffEdgeData = {
  labelText?: string;
  tooltip?: string;
  showParticles?: boolean;
  reduceMotion?: boolean;
  glow?: boolean;
};

export function HandoffEdge({
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
  const edgeData = (data ?? {}) as HandoffEdgeData;
  const [edgePath, labelX, labelY] = getSmoothStepPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
  });

  const particles =
    edgeData.showParticles && !edgeData.reduceMotion ? (
      <>
        <circle r={2.5} fill="hsl(var(--neon-cyan))" className="edge-particle">
          <animateMotion dur="2.4s" repeatCount="indefinite" path={edgePath} />
        </circle>
        <circle r={2} fill="hsl(var(--neon-violet))" className="edge-particle">
          <animateMotion
            dur="2.4s"
            begin="0.8s"
            repeatCount="indefinite"
            path={edgePath}
          />
        </circle>
      </>
    ) : null;

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        markerEnd={markerEnd}
        style={{
          ...style,
          filter: edgeData.glow
            ? "drop-shadow(0 0 4px hsl(var(--neon-cyan) / 0.85))"
            : undefined,
        }}
      />
      {particles}
      <EdgeLabelRenderer>
        <div
          className="edge-tooltip-label nodrag nopan"
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
