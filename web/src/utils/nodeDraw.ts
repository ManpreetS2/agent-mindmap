import type { Status } from "@shared/types";
import { nodePosition, type GNode } from "./networkModel";

/** Body radius in world units (the library multiplies by zoom). Fit zoom is >1 for small graphs. */
export const NODE_R = 19;
/** Scale for hand-tuned glyph geometry that was drawn for the original 15-unit radius. */
const K = NODE_R / 15;

export const PROVIDER_COLOR = {
  claude: "#f4a373",
  codex: "#3ad0b8",
  other: "#a9b4c8",
  unknown: "#7a8494",
} as const;

export const STATUS_COLOR: Record<Status, string> = {
  IN_PROGRESS: "#5b8cff",
  IN_REVIEW: "#8b7cff",
  BLOCKED: "#f5b942",
  FAILED: "#f0596b",
  DONE: "#46c98a",
  IDLE: "#7b8499",
  UNKNOWN: "#7b8499",
  STALE: "#7b8499",
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
  label?: LabelPlacement | null;
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

  const lit = s.selected || s.hovered;
  // Soft status glow (radial, cheap): active agents breathe only while motion is on; selection adds light.
  if ((n.active || s.selected) && !faded) {
    const k = n.active && s.t !== null ? 0.5 + 0.5 * Math.sin(s.t / 650 + n.phase * 6.28) : 0.5;
    const glowR = NODE_R + 20 + k * 5;
    const glow = ctx.createRadialGradient(x, y, NODE_R * 0.8, x, y, glowR);
    glow.addColorStop(0, hexA(sc, (s.selected ? 0.34 : 0.22) + 0.1 * k));
    glow.addColorStop(1, hexA(sc, 0));
    ctx.beginPath();
    ctx.arc(x, y, glowR, 0, Math.PI * 2);
    ctx.fillStyle = glow;
    ctx.fill();
  }

  // Contact shadow gives the body depth against the canvas.
  ctx.beginPath();
  ctx.ellipse(x, y + NODE_R * 0.95, NODE_R * 0.95, NODE_R * 0.32, 0, 0, Math.PI * 2);
  ctx.fillStyle = "rgba(0,0,0,0.32)";
  ctx.fill();

  // Status ring.
  ctx.lineWidth = 3;
  ctx.strokeStyle = sc;
  ctx.setLineDash(faded ? [3, 3] : n.status === "BLOCKED" ? [6, 3.5] : []);
  ctx.beginPath();
  ctx.arc(x, y, NODE_R + 6, 0, Math.PI * 2);
  ctx.stroke();
  ctx.setLineDash([]);
  if (n.active && s.t !== null) {
    // A short bright arc orbiting the ring: "reported in progress", not data flow.
    const a = s.t / 900 + n.phase * 6.28;
    ctx.beginPath();
    ctx.arc(x, y, NODE_R + 6, a, a + 0.9);
    ctx.lineWidth = 3.8;
    ctx.strokeStyle = "#ffffff";
    ctx.globalAlpha = s.alpha * 0.85;
    ctx.stroke();
    ctx.globalAlpha = s.alpha;
  }

  // Body: lit from the upper left, rim-light on the edge.
  const g = ctx.createRadialGradient(x - NODE_R * 0.35, y - NODE_R * 0.45, 2, x, y, NODE_R * 1.15);
  g.addColorStop(0, hexA(color, lit ? 0.7 : 0.58));
  g.addColorStop(0.55, hexA(color, 0.2));
  g.addColorStop(1, "#0d121b");
  bodyPath(ctx, n, NODE_R);
  ctx.fillStyle = g;
  ctx.fill();
  ctx.lineWidth = 2.4;
  ctx.strokeStyle = color;
  ctx.stroke();
  bodyPath(ctx, n, NODE_R - 3);
  ctx.lineWidth = 1;
  ctx.strokeStyle = "rgba(255,255,255,0.14)";
  ctx.stroke();

  // Glyph: status mark inside the body (never colour alone).
  ctx.fillStyle = "#f4f7fb";
  ctx.strokeStyle = "#f4f7fb";
  ctx.lineWidth = 2.4;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  if (n.status === "FAILED") {
    const d = 4.8 * K;
    ctx.beginPath();
    ctx.moveTo(x - d, y - d);
    ctx.lineTo(x + d, y + d);
    ctx.moveTo(x + d, y - d);
    ctx.lineTo(x - d, y + d);
    ctx.stroke();
  } else if (n.status === "DONE") {
    ctx.beginPath();
    ctx.moveTo(x - 5.2 * K, y + 0.5 * K);
    ctx.lineTo(x - 1.5 * K, y + 4.2 * K);
    ctx.lineTo(x + 5.6 * K, y - 4.2 * K);
    ctx.stroke();
  } else if (n.status === "BLOCKED") {
    ctx.fillRect(x - 4.6 * K, y - 4.8 * K, 3.1 * K, 9.6 * K);
    ctx.fillRect(x + 1.5 * K, y - 4.8 * K, 3.1 * K, 9.6 * K);
  } else if (n.status === "IN_PROGRESS" || n.status === "IN_REVIEW") {
    ctx.beginPath();
    ctx.moveTo(x - 3.2 * K, y - 5.4 * K);
    ctx.lineTo(x + 5.4 * K, y);
    ctx.lineTo(x - 3.2 * K, y + 5.4 * K);
    ctx.closePath();
    ctx.fill();
  } else {
    ctx.beginPath();
    ctx.arc(x, y, 2.6 * K, 0, Math.PI * 2);
    ctx.fill();
  }

  // Selection / hover ring.
  if (s.selected || s.hovered) {
    ctx.beginPath();
    ctx.arc(x, y, NODE_R + 12, 0, Math.PI * 2);
    ctx.lineWidth = s.selected ? 2.2 : 1.3;
    ctx.strokeStyle = s.selected ? "#ffffff" : "rgba(255,255,255,0.55)";
    ctx.stroke();
  }

  // Observed-change pulse + caption (fades over ~2.4 s).
  if (s.flash && s.flash.age < 2400) {
    const k = s.flash.age / 2400;
    ctx.beginPath();
    ctx.arc(x, y, NODE_R + 8 + (s.t === null ? 2 : k * 22), 0, Math.PI * 2);
    ctx.lineWidth = s.t === null ? 2 : 3.2 * (1 - k);
    ctx.strokeStyle = hexA(s.flash.color, s.t === null ? 0.65 : 0.75 * (1 - k));
    ctx.stroke();
    ctx.globalAlpha = (s.t === null ? 1 : Math.min(1, 2.2 * (1 - k))) * s.alpha;
    drawTag(ctx, s.flash.caption, x, y - NODE_R - 22 / s.zoom, s.flash.color, s.zoom);
  }

  // Labels (level of detail by zoom): task title first, then "Provider · model".
  ctx.globalAlpha = s.alpha * (faded ? 0.8 : 1);
  const fs = labelFont(s.zoom);
  const label = s.label === undefined ? layoutLabels([n], s.zoom, s.selected || s.hovered ? n.id : null).get(n.id) : s.label;
  if (label) {
    const { x: lx, y: ly, lines } = label;
    const maxW = 168;
    ctx.font = `600 ${fs}px ui-sans-serif, system-ui, -apple-system, sans-serif`;
    const title = fitText(ctx, n.task ?? n.providerName, maxW);
    const w1 = ctx.measureText(title).width;
    const subFont = fs * 0.85;
    let provider = "", model = "", wProvider = 0, wModel = 0, gap = 0;
    if (lines >= 2) {
      ctx.font = `700 ${subFont}px ui-sans-serif, system-ui, -apple-system, sans-serif`;
      provider = n.providerName;
      wProvider = ctx.measureText(provider).width;
      gap = subFont * 0.6;
      ctx.font = `500 ${subFont}px ui-monospace, Menlo, monospace`;
      model = fitText(ctx, n.model ?? "model not reported", Math.max(40, maxW - wProvider - gap));
      wModel = ctx.measureText(model).width;
    }
    const pillW = Math.max(w1, wProvider + gap + wModel) + fs * 1.1;
    ctx.fillStyle = "rgba(8,11,18,0.74)";
    roundRect(ctx, lx - pillW / 2, ly - 3, pillW, label.height + 2, fs * 0.55);
    ctx.fill();
    ctx.textBaseline = "top";
    ctx.textAlign = "center";
    ctx.font = `600 ${fs}px ui-sans-serif, system-ui, -apple-system, sans-serif`;
    ctx.fillStyle = "#eef2f9";
    ctx.fillText(title, lx, ly);
    if (lines >= 2) {
      const startX = lx - (wProvider + gap + wModel) / 2;
      ctx.textAlign = "left";
      ctx.font = `700 ${subFont}px ui-sans-serif, system-ui, -apple-system, sans-serif`;
      ctx.fillStyle = color;
      ctx.fillText(provider, startX, ly + fs * 1.4);
      ctx.font = `500 ${subFont}px ui-monospace, Menlo, monospace`;
      ctx.fillStyle = "#aab4c8";
      ctx.fillText(model, startX + wProvider + gap, ly + fs * 1.4);
      ctx.textAlign = "center";
    }
    void w1;
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

export function drawTag(ctx: CanvasRenderingContext2D, text: string, x: number, y: number, color: string, zoom: number): void {
  const unit = 1 / Math.max(0.1, Math.min(6, zoom));
  ctx.font = `700 ${9 * unit}px ui-sans-serif, system-ui, sans-serif`;
  const w = ctx.measureText(text).width + 10 * unit;
  ctx.fillStyle = "rgba(14,18,26,0.92)";
  roundRect(ctx, x - w / 2, y - 8 * unit, w, 16 * unit, 7 * unit);
  ctx.fill();
  ctx.lineWidth = unit;
  ctx.strokeStyle = color;
  ctx.stroke();
  ctx.fillStyle = color;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(text, x, y + 0.5 * unit);
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

export interface LabelPlacement { x: number; y: number; height: number; lines: number }

/** Primary label size in WORLD units so it lands at a readable SCREEN size (13px, easing down when zoomed out). */
export function labelFont(zoom: number): number {
  const z = Math.max(0.2, zoom);
  const px = z >= 0.8 ? 13 : z >= 0.55 ? 11.5 : 10;
  return px / z;
}
const LABEL_GAP = NODE_R + 17;     // body centre -> label top (clears the status/selection ring)
const BODY_CLEAR = NODE_R + 14;    // other bodies must stay this far from a label rectangle

/** Prefer below, then above; reduce detail before omitting a crowded label. Body clearance
 * applies even to selected labels and pinned nodes, which collision forces cannot separate. */
export function layoutLabels(nodes: GNode[], zoom: number, focus: string | null = null): Map<string, LabelPlacement> {
  const placed = new Map<string, LabelPlacement>();
  const fs = labelFont(zoom);
  const ordered = [...nodes].sort((a, b) => Number(b.id === focus) - Number(a.id === focus) || a.id.localeCompare(b.id));
  const bodies = nodes.map(n => ({ id: n.id, ...nodePosition(n) }));
  for (const n of ordered) {
    if (zoom <= 0.4 && n.id !== focus) continue;
    const p = nodePosition(n);
    // Two lines (title + provider/model) when there is room; title only when zoomed out or crowded.
    const maxLines = zoom > 0.7 || n.id === focus ? 2 : 1;
    let found = false;
    for (let lines = maxLines; lines >= 1 && !found; lines--) {
      const height = fs * (lines === 2 ? 2.5 : 1.3) + 4;
      for (const y of [p.y + LABEL_GAP, p.y - LABEL_GAP - height]) {
        const rect = { x: p.x, y, height, lines };
        if (bodies.some(b => b.id !== n.id && Math.abs(b.x - rect.x) < 112 && b.y + BODY_CLEAR > y - 2 && b.y - BODY_CLEAR < y - 2 + height)) continue;
        if ([...placed.values()].some(q => Math.abs(q.x - rect.x) < 172 && q.y + q.height + 2 > y && y + height + 2 > q.y)) continue;
        placed.set(n.id, rect); found = true; break;
      }
    }
  }
  return placed;
}

/** The entire horizontal tag clears the link/arrow line, including diagonal edges. */
export function linkCaptionPosition(s: GNode, t: GNode, width: number, height: number, zoom: number) {
  const dx = (t.x ?? 0) - (s.x ?? 0), dy = (t.y ?? 0) - (s.y ?? 0);
  const length = Math.hypot(dx, dy) || 1;
  const sign = dx < 0 ? -1 : 1;
  const offset = Math.abs(dy / length) * width / 2 + Math.abs(dx / length) * height / 2 + 12 / zoom;
  return { x: ((s.x ?? 0) + (t.x ?? 0)) / 2 + dy / length * offset * sign,
    y: ((s.y ?? 0) + (t.y ?? 0)) / 2 - dx / length * offset * sign };
}
