import type { Status } from "@shared/types";
import { nodePosition, type GNode } from "./networkModel";

/** Body radius in world units (the library multiplies by zoom). Fit zoom is >1 for small graphs. */
export const NODE_R = 26;
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
  // A quiet track remains visible behind each state, including dashed stale/blocked rings.
  ctx.lineWidth = 1;
  ctx.strokeStyle = hexA(sc, 0.18);
  ctx.beginPath();
  ctx.arc(x, y, NODE_R + 7, 0, Math.PI * 2);
  ctx.stroke();
  ctx.lineWidth = n.active || n.status === "BLOCKED" || n.status === "FAILED" ? 2.5 : 1.6;
  ctx.strokeStyle = hexA(sc, faded ? 0.65 : n.status === "IDLE" ? 0.55 : 0.95);
  ctx.setLineDash(faded ? [3, 3] : n.status === "BLOCKED" ? [6, 3.5] : []);
  ctx.beginPath();
  ctx.arc(x, y, NODE_R + 7, 0, Math.PI * 2);
  ctx.stroke();
  ctx.setLineDash([]);
  if (n.active && s.t !== null) {
    // A short bright arc orbiting the ring: "reported in progress", not data flow.
    const a = s.t / 900 + n.phase * 6.28;
    ctx.beginPath();
    ctx.arc(x, y, NODE_R + 7, a, a + 0.55);
    ctx.lineWidth = 3;
    ctx.strokeStyle = "#c9dcff";
    ctx.globalAlpha = s.alpha * 0.85;
    ctx.stroke();
    ctx.globalAlpha = s.alpha;
  }

  // Body: lit from the upper left, rim-light on the edge.
  const g = ctx.createRadialGradient(x - NODE_R * 0.35, y - NODE_R * 0.45, 2, x, y, NODE_R * 1.15);
  g.addColorStop(0, hexA(color, lit ? 0.44 : 0.28));
  g.addColorStop(0.55, hexA(color, 0.09));
  g.addColorStop(1, "#0d121b");
  bodyPath(ctx, n, NODE_R);
  ctx.fillStyle = "#111a29";
  ctx.fill();
  ctx.fillStyle = g;
  ctx.fill();
  ctx.lineWidth = lit ? 2 : 1.5;
  ctx.strokeStyle = hexA(color, lit ? 1 : 0.85);
  ctx.stroke();
  bodyPath(ctx, n, NODE_R - 3);
  ctx.lineWidth = 1;
  ctx.strokeStyle = "rgba(255,255,255,0.06)";
  ctx.stroke();

  // Glyph: status mark inside the body (never colour alone).
  ctx.fillStyle = "#f4f7fb";
  ctx.strokeStyle = "#f4f7fb";
  ctx.lineWidth = 2.2;
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

  // A small pin mark remains visible without competing with the status glyph.
  if (n.pinned) {
    const px = x + NODE_R * 0.86, py = y - NODE_R * 0.86;
    ctx.beginPath(); ctx.arc(px, py, 6, 0, Math.PI * 2);
    ctx.fillStyle = "#18283c"; ctx.fill();
    ctx.strokeStyle = "#b9d3f5"; ctx.lineWidth = 1; ctx.stroke();
    ctx.beginPath(); ctx.moveTo(px - 2, py - 2); ctx.lineTo(px + 2, py - 2);
    ctx.moveTo(px, py - 2); ctx.lineTo(px, py + 3); ctx.stroke();
  }

  // Labels stay still while the body sways. Real measured text determines the occupied rectangle.
  ctx.globalAlpha = s.alpha * (faded ? 0.8 : 1);
  const label = s.label === undefined ? layoutLabels([n], s.zoom, lit ? n.id : null, ctx).get(n.id) : s.label;
  if (label) {
    if (label.y < y || Math.abs(label.x - x) > 2) {
      // A quiet tether keeps a displaced label associated with its own agent.
      const above = label.y < y;
      const edgeY = above ? label.y + label.height : label.y;
      ctx.beginPath(); ctx.moveTo(x, y + (above ? -1 : 1) * (NODE_R + 10));
      ctx.lineTo(label.x, edgeY); ctx.lineWidth = 0.7 * label.unit;
      ctx.strokeStyle = hexA(color, 0.25); ctx.stroke();
    }
    drawNodeLabel(ctx, label, color, lit);
  }

  ctx.restore();
}

// Bounded caches avoid shaping/measuring the same text on every animation frame.
const textCache = new Map<string, string>();
const widthCache = new Map<string, number>();
export function textWidth(ctx: CanvasRenderingContext2D, text: string): number {
  const key = `${ctx.font}|${text}`;
  const cached = widthCache.get(key);
  if (cached !== undefined) return cached;
  const width = ctx.measureText(text).width;
  if (widthCache.size >= 2048) widthCache.clear();
  widthCache.set(key, width);
  return width;
}
export function fitText(ctx: CanvasRenderingContext2D, text: string, width: number): string {
  const key = `${ctx.font}|${width}|${text}`;
  const cached = textCache.get(key);
  if (cached !== undefined) return cached;
  let result = text;
  if (textWidth(ctx, text) > width) {
    // Slice code points, never split a surrogate pair in a task title.
    const chars = Array.from(text);
    let lo = 0, hi = chars.length;
    while (lo < hi) {
      const mid = Math.ceil((lo + hi) / 2);
      if (textWidth(ctx, chars.slice(0, mid).join("") + "…") <= width) lo = mid;
      else hi = mid - 1;
    }
    result = chars.slice(0, lo).join("") + "…";
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
  ctx.font = `700 ${11 * unit}px ui-sans-serif, system-ui, sans-serif`;
  const w = textWidth(ctx, text) + 16 * unit;
  ctx.fillStyle = "rgba(14,18,26,0.92)";
  roundRect(ctx, x - w / 2, y - 11 * unit, w, 22 * unit, 7 * unit);
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

export interface LabelPlacement {
  x: number; y: number; width: number; height: number; lines: number;
  title: string[]; subtitle: string; font: number; unit: number;
}
export interface LabelViewport { left: number; right: number; top: number; bottom: number }
const SANS = "ui-sans-serif, system-ui, -apple-system, sans-serif";

/** World size of a readable screen-space title. Zooming out simplifies detail before hiding it. */
export function labelFont(zoom: number): number {
  return (zoom >= 0.8 ? 14 : zoom >= 0.5 ? 12.5 : 11.5) / Math.max(0.2, zoom);
}
const BODY_CLEAR = NODE_R + 14;

function labelContent(n: GNode, zoom: number, focus: boolean, count: number, detail: boolean, ctx?: CanvasRenderingContext2D) {
  const unit = 1 / Math.max(0.2, zoom), font = labelFont(zoom);
  const maxWidth = (focus ? 224 : count <= 5 ? 204 : 168) * unit;
  const raw = n.task ?? n.label ?? n.providerName;
  if (ctx) ctx.font = `600 ${font}px ${SANS}`;
  const measure = (text: string) => ctx ? textWidth(ctx, text) : Array.from(text).length * font * 0.58;
  const fit = (text: string) => ctx ? fitText(ctx, text, maxWidth) : text.length * font * 0.58 <= maxWidth ? text : text.slice(0, Math.max(1, Math.floor(maxWidth / (font * 0.58)) - 1)) + "…";
  const title: string[] = [];
  // Two title lines give small networks useful task names, without crowding dense overviews.
  if (detail && (focus || count <= 5) && measure(raw) > maxWidth) {
    let split = raw.lastIndexOf(" ", fit(raw).length - 1);
    if (split < 1) split = Math.max(1, fit(raw).length - 1);
    title.push(fit(raw.slice(0, split)), fit(raw.slice(split).trim()));
  } else title.push(fit(raw));
  let width = Math.max(...title.map(measure));
  let subtitle = "";
  if (detail) {
    if (ctx) ctx.font = `500 ${10.5 * unit}px ${SANS}`;
    const rawSub = `${n.providerName} · ${n.model ?? "model not reported"}`;
    subtitle = ctx ? fitText(ctx, rawSub, maxWidth) : rawSub.slice(0, Math.floor(maxWidth / (6 * unit)));
    width = Math.max(width, ctx ? textWidth(ctx, subtitle) : subtitle.length * 6 * unit);
  }
  return { title, subtitle, font, unit, width: Math.min(maxWidth, width) + 16 * unit,
    height: title.length * font * 1.25 + (subtitle ? 16 * unit : 0) + 8 * unit,
    lines: title.length + Number(Boolean(subtitle)) };
}

function drawNodeLabel(ctx: CanvasRenderingContext2D, l: LabelPlacement, color: string, lit: boolean): void {
  const { x, y, width, height, font, unit, title, subtitle } = l;
  ctx.fillStyle = lit ? "rgba(12,20,33,0.96)" : "rgba(8,13,22,0.72)";
  roundRect(ctx, x - width / 2, y, width, height, 6 * unit); ctx.fill();
  if (lit) { ctx.strokeStyle = hexA(color, 0.32); ctx.lineWidth = unit; ctx.stroke(); }
  ctx.textAlign = "center"; ctx.textBaseline = "top";
  ctx.font = `600 ${font}px ${SANS}`; ctx.fillStyle = "#edf2fa";
  title.forEach((text, i) => ctx.fillText(text, x, y + 4 * unit + i * font * 1.25));
  if (subtitle) {
    ctx.font = `500 ${10.5 * unit}px ${SANS}`; ctx.fillStyle = color;
    ctx.fillText(subtitle, x, y + 6 * unit + title.length * font * 1.25);
  }
}

/** Attention and focus get first choice. Try below/above, simplify, then cull.
 * Layout uses simulation anchors: ambient sway must never jiggle text or change its placement. */
export function layoutLabels(nodes: GNode[], zoom: number, focus: string | null = null, ctx?: CanvasRenderingContext2D, viewport?: LabelViewport): Map<string, LabelPlacement> {
  const placed = new Map<string, LabelPlacement>();
  const priority = (n: GNode) => n.id === focus ? 4 : n.status === "FAILED" || n.status === "BLOCKED" ? 3 : n.active ? 2 : 1;
  const ordered = [...nodes].sort((a, b) => priority(b) - priority(a) || a.id.localeCompare(b.id));
  const bodies = nodes.map(n => ({ id: n.id, x: n.x ?? 0, y: n.y ?? 0 }));
  const gap = NODE_R + 14 + 5 / Math.max(0.2, zoom);
  for (const n of ordered) {
    if (zoom <= 0.3 && n.id !== focus) continue;
    const x = n.x ?? 0, ny = n.y ?? 0;
    if (viewport && (x + BODY_CLEAR < viewport.left || x - BODY_CLEAR > viewport.right || ny + BODY_CLEAR < viewport.top || ny - BODY_CLEAR > viewport.bottom)) continue;
    const details = zoom > 0.7 || n.id === focus ? [true, false] : [false];
    let found = false;
    for (const detail of details) {
      const content = labelContent(n, zoom, n.id === focus, nodes.length, detail, ctx);
      const { width, height } = content;
      const candidates = [0, -0.35, 0.35].flatMap(shift => [
        { x: x + width * shift, y: ny + gap },
        { x: x + width * shift, y: ny - gap - height },
      ]);
      for (const candidate of candidates) {
        const p = viewport ? { x: Math.max(viewport.left + width / 2, Math.min(viewport.right - width / 2, candidate.x)), y: candidate.y } : candidate;
        if (viewport && (width > viewport.right - viewport.left || p.y < viewport.top || p.y + height > viewport.bottom)) continue;
        if (bodies.some(b => b.id !== n.id && Math.abs(b.x - p.x) < width / 2 + BODY_CLEAR && b.y + BODY_CLEAR > p.y - 3 && b.y - BODY_CLEAR < p.y + height)) continue;
        if ([...placed.values()].some(q => Math.abs(q.x - p.x) < (q.width + width) / 2 + 4 / zoom && q.y + q.height + 3 > p.y - 3 && p.y + height + 3 > q.y - 3)) continue;
        placed.set(n.id, { ...p, ...content }); found = true; break;
      }
      if (found) break;
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
