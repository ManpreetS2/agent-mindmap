import { useRef, type MouseEvent, type PointerEvent } from "react";
import type { ForceGraphMethods } from "react-force-graph-2d";
import { nodePosition, type GNode, type GLink } from "../utils/networkModel";
import { containsNode } from "../utils/nodeDraw";

type FG = ForceGraphMethods<GNode, GLink>;
/** Geometry hit tests avoid stale shadow-canvas targets while nodes move, at every DPR. */
export function useNetworkPointer({ fg, nodes, onHover, onSelect, onDragEnd, onDragging, onUnpin }: {
  fg: React.MutableRefObject<FG | undefined>;
  nodes: GNode[];
  onHover: (id: string | null) => void;
  onSelect: (id: string) => void;
  onDragEnd: (node: GNode) => void;
  onDragging: (on: boolean) => void;
  onUnpin?: (node: GNode) => void;
}) {
  const drag = useRef<{ n: GNode; px: number; py: number; x: number; y: number; moved: boolean; pointerId: number; original: Pick<GNode, "x" | "y" | "ox" | "oy">; fx?: number; fy?: number }>();
  const point = (e: PointerEvent<HTMLDivElement> | MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    return fg.current?.screen2GraphCoords(e.clientX - rect.left, e.clientY - rect.top);
  };
  const hit = (e: PointerEvent<HTMLDivElement> | MouseEvent<HTMLDivElement>) => {
    if (!(e.target instanceof HTMLCanvasElement)) return;
    const p = point(e);
    return p && [...nodes].reverse().find(n => containsNode(n, p.x, p.y));
  };
  const finish = (e: PointerEvent<HTMLDivElement>, cancelled = false) => {
    const d = drag.current;
    if (!d || e.pointerId !== d.pointerId) return;
    e.stopPropagation();
    drag.current = undefined;
    d.n.dragging = false;
    if (d.moved) onDragEnd(d.n);
    else { Object.assign(d.n, d.original); d.n.fx = d.fx; d.n.fy = d.fy; if (!cancelled) onSelect(d.n.id); }
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);
    onDragging(false);
  };
  return {
    onPointerDownCapture(e: PointerEvent<HTMLDivElement>) {
      if (e.button !== 0) return;
      if (drag.current) { e.preventDefault(); e.stopPropagation(); return; }
      const n = hit(e), p = point(e);
      if (!n || !p) return;
      e.stopPropagation();
      e.preventDefault(); // suppress the compatibility mousedown that would start d3 pan
      const pos = nodePosition(n);
      drag.current = { n, px: e.clientX, py: e.clientY, x: p.x - pos.x, y: p.y - pos.y, moved: false, pointerId: e.pointerId, original: { x: n.x, y: n.y, ox: n.ox, oy: n.oy }, fx: n.fx, fy: n.fy };
      // Freeze exactly where drawn, including an active agent's ambient displacement.
      n.x = pos.x; n.y = pos.y; n.fx = pos.x; n.fy = pos.y; n.ox = 0; n.oy = 0; n.dragging = true;
      e.currentTarget.setPointerCapture(e.pointerId);
      onDragging(true);
    },
    onPointerMoveCapture(e: PointerEvent<HTMLDivElement>) {
      const d = drag.current;
      if (d) {
        e.stopPropagation();
        if (e.pointerId !== d.pointerId) return;
        const p = point(e);
        if (Math.hypot(e.clientX - d.px, e.clientY - d.py) > 5) d.moved = true;
        if (p && d.moved) { d.n.x = d.n.fx = p.x - d.x; d.n.y = d.n.fy = p.y - d.y; d.n.vx = 0; d.n.vy = 0; }
      } else onHover(hit(e)?.id ?? null);
    },
    onDoubleClickCapture(e: MouseEvent<HTMLDivElement>) {
      const n = hit(e);
      if (!n) return;
      e.preventDefault(); e.stopPropagation(); // do not let d3 double-click zoom run
      if (n.pinned) {
        n.pinned = false; n.fx = undefined; n.fy = undefined;
        onUnpin?.(n);
      }
    },
    onPointerUpCapture: (e: PointerEvent<HTMLDivElement>) => finish(e),
    onPointerCancelCapture: (e: PointerEvent<HTMLDivElement>) => finish(e, true),
    onLostPointerCapture: (e: PointerEvent<HTMLDivElement>) => finish(e, true),
    onPointerLeave: () => { if (!drag.current) onHover(null); },
  };
}
