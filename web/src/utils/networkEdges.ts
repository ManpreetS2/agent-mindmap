import { nodePosition, type GLink, type GNode } from "./networkModel";
import { NODE_R, drawTag, linkCaptionPosition, textWidth } from "./nodeDraw";
import type { EdgeObservation } from "./edgeActivity";

/** Visible endpoints follow the bounded sway, with arrows outside the status/selection rings. */
export function linkGeometry(source: GNode, target: GNode, zoom: number) {
  const s = nodePosition(source), t = nodePosition(target);
  const dx = t.x - s.x, dy = t.y - s.y, distance = Math.hypot(dx, dy);
  const unit = 1 / Math.max(0.1, zoom);
  const clearance = NODE_R + 14;
  if (distance <= clearance * 2 + 10 * unit) return null;
  const ux = dx / distance, uy = dy / distance;
  return {
    start: { x: s.x + ux * clearance, y: s.y + uy * clearance },
    end: { x: t.x - ux * clearance, y: t.y - uy * clearance },
    ux, uy, unit,
  };
}

export function drawNetworkLink(ctx: CanvasRenderingContext2D, link: GLink, zoom: number, state: {
  focused: boolean; dimmed: boolean; observation?: EdgeObservation; simulated: boolean;
}): void {
  if (typeof link.source !== "object" || typeof link.target !== "object") return;
  const g = linkGeometry(link.source, link.target, zoom);
  if (!g) return;
  const { start, end, ux, uy, unit } = g;
  const fresh = Boolean(state.observation);
  ctx.save();
  ctx.globalAlpha = state.dimmed ? 0.16 : 1;
  ctx.lineCap = "round";
  const line = () => { ctx.beginPath(); ctx.moveTo(start.x, start.y); ctx.lineTo(end.x, end.y); };
  if (fresh || state.focused) {
    line(); ctx.strokeStyle = fresh ? "rgba(137,178,255,0.12)" : "rgba(137,178,255,0.06)";
    ctx.lineWidth = (fresh ? 7 : 5) * unit; ctx.stroke();
  }
  line();
  ctx.strokeStyle = fresh ? "#8fb4ff" : state.focused ? "#b2c9ef" : "rgba(139,167,207,0.45)";
  ctx.lineWidth = (fresh ? 1.8 : state.focused ? 1.5 : 1) * unit;
  if (link.type !== "delegation") ctx.setLineDash([4 * unit, 4 * unit]);
  ctx.stroke(); ctx.setLineDash([]);

  // Nine CSS pixels at every zoom. A solid chevron is easier to read than the library's thin dart.
  const length = 9 * unit, half = 3.8 * unit;
  const tx = end.x - ux * length, ty = end.y - uy * length;
  ctx.beginPath(); ctx.moveTo(end.x, end.y);
  ctx.lineTo(tx - uy * half, ty + ux * half);
  ctx.lineTo(tx + ux * length * 0.18, ty + uy * length * 0.18);
  ctx.lineTo(tx + uy * half, ty - ux * half); ctx.closePath();
  ctx.fillStyle = fresh || state.focused ? "#c5d9ff" : "#819bbf"; ctx.fill();

  if (state.observation) {
    const label = state.observation === "new-delegation" ? "NEW DELEGATION" : "Newly observed";
    const text = state.simulated ? `DEMO · ${label}` : label;
    ctx.font = `700 ${11 * unit}px ui-sans-serif, system-ui, sans-serif`;
    const width = textWidth(ctx, text) + 16 * unit;
    const p = linkCaptionPosition(link.source, link.target, width, 22 * unit, zoom);
    drawTag(ctx, text, p.x, p.y, "#a8c6ff", zoom);
  }
  ctx.restore();
}
