import type { Status } from "@shared/types";
import { nodePosition, type GNode } from "./networkModel";

export const NODE_R = 15;

export const PROVIDER_COLOR = {
  claude: "#f0a070",
  codex: "#4fd1b8",
  other: "#a9b4c8",
  unknown: "#7a8494",
} as const;

export const STATUS_COLOR: Record<Status, string> = {
  IN_PROGRESS: "#5aa2ff",
  IN_REVIEW: "#e0b84a",
  BLOCKED: "#f0a23c",
  FAILED: "#ff5d73",
  DONE: "#4fd27d",
  IDLE: "#7f8a9c",
  UNKNOWN: "#7f8a9c",
  STALE: "#7f8a9c",
};

export interface DrawState {
  /** ms clock for ambient animation; null when motion is off. */
  t: number | null;
  selected: boolean;
  /** 1 = full, lower = dimmed by hover/selection focus. */
  alpha: number;
  hovered: boolean;
  /** Transient caption for an observed status change. */
  flash: { caption: string; age: number; color: string } | null;
  zoom: number;
}

function hexPath(ctx: CanvasRenderingContext2D, x: number, y: number, r: number): void {
  ctx.beginPath();
  for (let i = 0; i < 6; i++) {
    const a = (Math.PI / 3) * i + Math.PI / 6;
    const px = x + r * Math.cos(a);
    const py = y + r * Math.sin(a);
    if (i === 0) ctx.moveTo(px, py);
    else ctx.lineTo(px, py);
  }
  ctx.closePath();
}

/** Body outline: Claude = circle, Codex = hexagon (shape, not just colour, tells them apart). */
export function bodyPath(ctx: CanvasRenderingContext2D, n: GNode, r: number): void {
  const { x, y } = nodePosition(n);
  if (n.provider === "codex") hexPath(ctx, x, y, r * 1.08);
  else {
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
  }
}

export function drawNode(ctx: CanvasRenderingContext2D, n: GNode, s: DrawState): void {
  const { x, y } = nodePosition(n);
  const color = PROVIDER_COLOR[n.provider];
  const sc = STATUS_COLOR[n.status];
  const faded = n.stale || n.status === "UNKNOWN";
  ctx.save();
  ctx.globalAlpha = s.alpha * (faded ? 0.7 : 1);

  // Status halo (ambient only for genuinely active agents).
  if (n.active && s.t !== null) {
    const k = 0.5 + 0.5 * Math.sin(s.t / 650 + n.phase * 6.28);
    ctx.beginPath();
    ctx.arc(x, y, NODE_R + 6 + k * 3, 0, Math.PI * 2);
    ctx.fillStyle = hexA(sc, 0.12 + 0.1 * k);
    ctx.fill();
  }

  // Status ring.
  ctx.lineWidth = 2.6;
  ctx.strokeStyle = sc;
  ctx.setLineDash(faded ? [3, 3] : n.status === "BLOCKED" ? [5, 3] : []);
  ctx.beginPath();
  ctx.arc(x, y, NODE_R + 5, 0, Math.PI * 2);
  ctx.stroke();
  ctx.setLineDash([]);
  if (n.active && s.t !== null) {
    // A short bright arc orbiting the ring: "reported in progress", not data flow.
    const a = s.t / 900 + n.phase * 6.28;
    ctx.beginPath();
    ctx.arc(x, y, NODE_R + 5, a, a + 0.9);
    ctx.lineWidth = 3.6;
    ctx.strokeStyle = "#ffffff";
    ctx.globalAlpha = s.alpha * 0.85;
    ctx.stroke();
    ctx.globalAlpha = s.alpha;
  }

  // Body.
  const g = ctx.createRadialGradient(x - 4, y - 5, 2, x, y, NODE_R + 2);
  g.addColorStop(0, hexA(color, 0.5));
  g.addColorStop(1, "#141923");
  bodyPath(ctx, n, NODE_R);
  ctx.fillStyle = g;
  ctx.fill();
  ctx.lineWidth = 2.4;
  ctx.strokeStyle = color;
  ctx.stroke();

  // Glyph: status mark inside the body.
  ctx.fillStyle = "#f4f7fb";
  ctx.strokeStyle = "#f4f7fb";
  ctx.lineWidth = 2.2;
  ctx.lineCap = "round";
  if (n.status === "FAILED") {
    ctx.beginPath();
    ctx.moveTo(x - 4.5, y - 4.5);
    ctx.lineTo(x + 4.5, y + 4.5);
    ctx.moveTo(x + 4.5, y - 4.5);
    ctx.lineTo(x - 4.5, y + 4.5);
    ctx.stroke();
  } else if (n.status === "DONE") {
    ctx.beginPath();
    ctx.moveTo(x - 5, y + 0.5);
    ctx.lineTo(x - 1.5, y + 4);
    ctx.lineTo(x + 5.5, y - 4);
    ctx.stroke();
  } else if (n.status === "BLOCKED") {
    ctx.fillRect(x - 4.5, y - 4.5, 3, 9);
    ctx.fillRect(x + 1.5, y - 4.5, 3, 9);
  } else if (n.status === "IN_PROGRESS" || n.status === "IN_REVIEW") {
    ctx.beginPath();
    ctx.moveTo(x - 3, y - 5);
    ctx.lineTo(x + 5, y);
    ctx.lineTo(x - 3, y + 5);
    ctx.closePath();
    ctx.fill();
  } else {
    ctx.beginPath();
    ctx.arc(x, y, 2.4, 0, Math.PI * 2);
    ctx.fill();
  }

  // Selection / hover ring.
  if (s.selected || s.hovered) {
    ctx.beginPath();
    ctx.arc(x, y, NODE_R + 10, 0, Math.PI * 2);
    ctx.lineWidth = s.selected ? 2 : 1.2;
    ctx.strokeStyle = s.selected ? "#ffffff" : "rgba(255,255,255,0.55)";
    ctx.stroke();
  }

  // Observed-change pulse + caption (fades over ~2.4 s).
  if (s.flash && s.flash.age < 2400) {
    const k = s.flash.age / 2400;
    if (s.t !== null) {
      ctx.beginPath();
      ctx.arc(x, y, NODE_R + 6 + k * 34, 0, Math.PI * 2);
      ctx.lineWidth = 3 * (1 - k);
      ctx.strokeStyle = hexA(s.flash.color, 0.9 * (1 - k));
      ctx.stroke();
    }
    ctx.globalAlpha = Math.min(1, 2.2 * (1 - k)) * s.alpha;
    drawTag(ctx, s.flash.caption, x, y - NODE_R - 18, s.flash.color);
  }

  // Labels (level of detail by zoom).
  ctx.globalAlpha = s.alpha * (faded ? 0.8 : 1);
  const fs = Math.min(13, 11 / Math.max(0.3, s.zoom));
  const labelY = y + NODE_R + 12 + 4 / Math.max(0.55, s.zoom);
  const show = s.zoom > 0.55 || s.selected || s.hovered;
  if (show) {
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    ctx.font = `700 ${fs}px ui-sans-serif, system-ui, sans-serif`;
    ctx.fillStyle = color;
    ctx.fillText(fitText(ctx, n.providerName, 154), x, labelY);
    ctx.font = `500 ${fs * 0.88}px ui-monospace, Menlo, monospace`;
    ctx.fillStyle = "#c7cfdb";
    ctx.fillText(fitText(ctx, n.model ?? "model not reported", 154), x, labelY + fs * 1.3);
    if ((s.zoom > 1.15 || s.selected || s.hovered) && n.task) {
      ctx.font = `600 ${fs * 0.95}px ui-sans-serif, system-ui, sans-serif`;
      ctx.fillStyle = "#eef2f8";
      ctx.fillText(fitText(ctx, n.task, 154), x, labelY + fs * 2.6);
    }
  }
  ctx.restore();
}

// Bounded shared cache: no measureText calls per animated frame for unchanged labels.
const textCache = new Map<string, string>();
export function fitText(ctx: CanvasRenderingContext2D, text: string, width: number): string {
  const key = `${ctx.font}|${width}|${text}`;
  const cached = textCache.get(key);
  if (cached !== undefined) return cached;
  let result = text;
  if (ctx.measureText(text).width > width) {
    let lo = 0, hi = text.length;
    while (lo < hi) {
      const mid = Math.ceil((lo + hi) / 2);
      if (ctx.measureText(text.slice(0, mid) + "…").width <= width) lo = mid;
      else hi = mid - 1;
    }
    result = text.slice(0, lo) + "…";
  }
  if (textCache.size >= 2048) textCache.clear();
  textCache.set(key, result);
  return result;
}

/** Analytic hit testing uses the current visible position, not the library's 800 ms shadow cache. */
export function containsNode(n: GNode, x: number, y: number): boolean {
  const p = nodePosition(n), dx = Math.abs(x - p.x), dy = Math.abs(y - p.y);
  const r = NODE_R + 6; // ring plus a one-unit pointer gutter
  if (n.provider !== "codex") return dx * dx + dy * dy <= r * r;
  const hr = r * 1.08;
  return dx <= hr * Math.sqrt(3) / 2 && dy <= hr - dx / Math.sqrt(3);
}

function drawTag(ctx: CanvasRenderingContext2D, text: string, x: number, y: number, color: string): void {
  ctx.font = "700 8px ui-sans-serif, system-ui, sans-serif";
  const w = ctx.measureText(text).width + 10;
  ctx.fillStyle = "rgba(14,18,26,0.92)";
  roundRect(ctx, x - w / 2, y - 7, w, 14, 7);
  ctx.fill();
  ctx.lineWidth = 1;
  ctx.strokeStyle = color;
  ctx.stroke();
  ctx.fillStyle = color;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(text, x, y + 0.5);
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number): void {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

export function hexA(hex: string, a: number): string {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}
