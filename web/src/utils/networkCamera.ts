import type { GNode } from "./networkModel";
import { NODE_BOUNDS } from "./networkPhysics";

export interface Camera { x: number; y: number; zoom: number }
export interface CameraApi {
  centerAt(): { x: number; y: number };
  centerAt(x: number, y: number, duration: number): unknown;
  zoom(): number;
  zoom(k: number, duration: number): unknown;
}
export function readCamera(api: CameraApi): Camera | null {
  const c = api.centerAt(), zoom = api.zoom();
  return c && Number.isFinite(c.x) && Number.isFinite(c.y) && Number.isFinite(zoom) && zoom > 0 ? { ...c, zoom } : null;
}
export function restoreCamera(api: CameraApi, camera: Camera): void {
  api.zoom(camera.zoom, 0);
  api.centerAt(camera.x, camera.y, 0);
}

/** Fit the full label envelope in a safe rectangle clear of controls/legend; cap automatic zoom. */
export function fittedCamera(nodes: GNode[], width: number, height: number): Camera | null {
  if (!nodes.length || width <= 0 || height <= 0) return null;
  const xs = nodes.map(n => n.x ?? 0), ys = nodes.map(n => n.y ?? 0);
  const x0 = Math.min(...xs) + NODE_BOUNDS.left, x1 = Math.max(...xs) + NODE_BOUNDS.right;
  const y0 = Math.min(...ys) + NODE_BOUNDS.top, y1 = Math.max(...ys) + NODE_BOUNDS.bottom;
  const left = Math.min(70, width * 0.12), right = Math.min(90, width * 0.14);
  const top = 80, bottom = Math.min(150, height * 0.25);
  const zoom = Math.max(0.1, Math.min(1.8, (width - left - right) / (x1 - x0), (height - top - bottom) / (y1 - y0)));
  return { zoom, x: (x0 + x1) / 2 + (right - left) / (2 * zoom), y: (y0 + y1) / 2 + (bottom - top) / (2 * zoom) };
}
