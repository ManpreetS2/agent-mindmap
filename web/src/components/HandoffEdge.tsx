/**
 * Custom React Flow edge. Legacy handoffs may loop particles; T3 delegation edges only play a
 * single one-shot pulse when the relationship was newly observed (never for historical ones).
 */
import {
  BaseEdge,
  EdgeLabelRenderer,
  getSmoothStepPath,
  getStraightPath,
  useInternalNode,
  type EdgeProps,
} from "@xyflow/react";

export type HandoffEdgeData = {
  labelText?: string;
  tooltip?: string;
  showParticles?: boolean;
  reduceMotion?: boolean;
  glow?: boolean;
  /** Smooth bezier routing for network (T3) edges. */
  curved?: boolean;
  /** Newly observed verified relationship: one-shot pulse (or a static "new" tag). */
  fresh?: boolean;
  /** Show the label (focus / fresh) instead of keeping edges quiet. */
  showLabel?: boolean;
};

interface Box { cx: number; cy: number; w: number; h: number }

/** Point where the centre-to-centre line leaves `from`'s rectangle. */
function borderPoint(from: Box, to: Box): { x: number; y: number } {
  const dx = to.cx - from.cx;
  const dy = to.cy - from.cy;
  if (dx === 0 && dy === 0) return { x: from.cx, y: from.cy };
  const sx = from.w / 2 / Math.abs(dx || 1e-9);
  const sy = from.h / 2 / Math.abs(dy || 1e-9);
  const t = Math.min(sx, sy);
  return { x: from.cx + dx * t, y: from.cy + dy * t };
}

function boxOf(n: ReturnType<typeof useInternalNode>): Box | null {
  if (!n) return null;
  const w = n.measured?.width || n.initialWidth || 0;
  const h = n.measured?.height || n.initialHeight || 0;
  if (!w || !h) return null;
  const p = n.internals.positionAbsolute;
  return { cx: p.x + w / 2, cy: p.y + h / 2, w, h };
}

export function HandoffEdge({
  id,
  source,
  target,
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
  const args = {
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
  };
  // Network edges float: they leave each card's border along the line between the two cards,
  // so the arrow stays correct wherever physics or the user places the nodes.
  const sNode = useInternalNode(source);
  const tNode = useInternalNode(target);
  const sBox = edgeData.curved ? boxOf(sNode) : null;
  const tBox = edgeData.curved ? boxOf(tNode) : null;
  const [edgePath, labelX, labelY] =
    sBox && tBox
      ? (() => {
          const a = borderPoint(sBox, tBox);
          const b = borderPoint(tBox, sBox);
          return getStraightPath({ sourceX: a.x, sourceY: a.y, targetX: b.x, targetY: b.y });
        })()
      : getSmoothStepPath(args);

  const loop =
    edgeData.showParticles && !edgeData.reduceMotion ? (
      <>
        <circle r={2.5} fill="hsl(var(--neon-cyan))" className="edge-particle">
          <animateMotion dur="2.4s" repeatCount="indefinite" path={edgePath} />
        </circle>
        <circle r={2} fill="hsl(var(--neon-violet))" className="edge-particle">
          <animateMotion dur="2.4s" begin="0.8s" repeatCount="indefinite" path={edgePath} />
        </circle>
      </>
    ) : null;

  const pulse =
    edgeData.fresh && !edgeData.reduceMotion ? (
      <circle r={4} className="edge-fresh-dot" data-testid={`edge-pulse-${id}`}>
        <animateMotion dur="1.4s" repeatCount="1" fill="freeze" path={edgePath} />
      </circle>
    ) : null;

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        markerEnd={markerEnd}
        className={edgeData.fresh ? "edge-is-fresh" : undefined}
        style={{
          ...style,
          filter: edgeData.glow
            ? "drop-shadow(0 0 4px hsl(var(--neon-cyan) / 0.85))"
            : undefined,
        }}
      />
      {loop}
      {pulse}
      <EdgeLabelRenderer>
        {(edgeData.labelText || edgeData.fresh) && (edgeData.showLabel ?? true) && (
          <div
            className="edge-tooltip-label nodrag nopan"
            style={{
              transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
            }}
            title={edgeData.tooltip}
          >
            {edgeData.fresh ? `New · ${edgeData.labelText ?? ""}` : edgeData.labelText}
          </div>
        )}
      </EdgeLabelRenderer>
    </>
  );
}
