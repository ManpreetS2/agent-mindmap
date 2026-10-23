import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D, { type ForceGraphMethods } from "react-force-graph-2d";
import { networkForces } from "../utils/networkPhysics";
import { fittedCamera, readCamera, restoreCamera, type Camera } from "../utils/networkCamera";
import { useNetworkPointer } from "../hooks/useNetworkPointer";
import type { Activity } from "@shared/types";
import { useFreshEdges } from "../hooks/useFreshEdges";
import { useReducedMotionPreference } from "../hooks/useReducedMotion";
import { sourceKey } from "../utils/edgeActivity";
import {
  NetworkModel,
  endpointId,
  stepAmbient,
  nodePosition,
  transitionCaption,
  type GLink,
  type GNode,
} from "../utils/networkModel";
import { NODE_R, STATUS_COLOR, bodyPath, drawNode, hexA, linkCaptionPosition, layoutLabels, type LabelPlacement } from "../utils/nodeDraw";
import { AgentRoster } from "./AgentRoster";

const FLASH_MS = 2400;
const FRESH_LINK_COLOR = "#8fb4ff";
const replaceCanvas = () => "replace" as const;
const afterCanvas = () => "after" as const;
const noLabel = () => "";
const particleColor = () => "#e8f0ff";

export interface AgentNetworkProps {
  activity: Activity;
  selectedNodeId: string | null;
  onOpenNodeDetail: (id: string) => void;
  onClearNodeDetail: () => void;
}

type FG = ForceGraphMethods<GNode, GLink>;

function useSize(ref: React.RefObject<HTMLElement>): { w: number; h: number } {
  const [size, setSize] = useState({ w: 800, h: 520 });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => {
      const r = el.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) setSize({ w: Math.round(r.width), h: Math.round(r.height) });
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return size;
}

export function AgentNetwork({
  activity,
  selectedNodeId,
  onOpenNodeDetail,
  onClearNodeDetail,
}: AgentNetworkProps) {
  const reduce = useReducedMotionPreference();
  const [paused, setPaused] = useState(false);
  const motionOn = !reduce && !paused;
  const hostRef = useRef<HTMLDivElement>(null);
  const { w, h } = useSize(hostRef);
  const fgRef = useRef<FG>();
  const model = useRef(new NetworkModel()).current;
  const modelKey = useRef("");
  const [data, setData] = useState(() => model.data);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [pinCount, setPinCount] = useState(0);
  const [redraw, setRedraw] = useState(0);
  const [transient, setTransient] = useState(false);
  const [dragging, setDragging] = useState(false);
  const flashTimer = useRef<number>();
  const flashes = useRef(new Map<string, { caption: string; start: number; color: string }>());
  const fresh = useFreshEdges(activity);
  const emitted = useRef(new Set<string>());
  const camera = useRef<Camera | null>(null);
  const pendingCamera = useRef<Camera | null>(null);
  const queuedParticles = useRef(new Set<string>());
  const forces = useMemo(networkForces, []);
  // A changed zero accessor clears in-flight photons on pause/reduced-motion without reheating.
  const noContinuousParticles = useMemo(() => () => 0, [motionOn]);
  const fitted = useRef(false);
  const touched = useRef(false);
  const live = useRef({ selected: selectedNodeId, hovered: hoveredId, motionOn, fresh });
  live.current = { selected: selectedNodeId, hovered: hoveredId, motionOn, fresh };

  // --- sync model with each snapshot (layout effect: before paint, runs once per snapshot) ---
  useLayoutEffect(() => {
    const k = sourceKey(activity);
    if (modelKey.current !== k) {
      modelKey.current = k;
      model.reset();
      flashes.current.clear();
      emitted.current.clear();
      fitted.current = false;
      touched.current = false;
      camera.current = null;
      pendingCamera.current = null;
      queuedParticles.current.clear();
    }
    const saved = fgRef.current && (fitted.current || touched.current) ? readCamera(fgRef.current) : null;
    const r = model.sync(activity);
    const now = performance.now();
    for (const t of r.transitions) {
      flashes.current.set(t.id, {
        caption: transitionCaption(t),
        start: now,
        color: STATUS_COLOR[t.to],
      });
    }
    if (r.transitions.length) {
      setTransient(true);
      window.clearTimeout(flashTimer.current);
      flashTimer.current = window.setTimeout(() => {
        flashes.current.clear();
        setTransient(false);
        setRedraw(v => v + 1);
      }, FLASH_MS + 100);
    }
    if (r.topologyChanged) {
      pendingCamera.current = saved;
      setData(model.data);
    }
    setPinCount([...model.node.values()].filter((n) => n.pinned).length);
    if (r.visualChanged) setRedraw((v) => v + 1);
  }, [activity, model]);

  useEffect(() => () => window.clearTimeout(flashTimer.current), []);

  // Stable, named forces replace themselves on StrictMode setup; never accumulate.
  useEffect(() => {
    const fg = fgRef.current;
    if (!fg) return;
    fg.d3Force("charge")?.strength(-180).distanceMax(500);
    fg.d3Force("link")?.distance(154).strength(0.16);
    fg.d3Force("center", null as never);
    for (const [name, force] of Object.entries(forces)) fg.d3Force(name, force as never);
  }, [forces]);

  // Opt-in debug/QA hook (localStorage.mindmapDebug = "1"): node screen positions for browser tests.
  useEffect(() => {
    if (typeof window === "undefined" || window.localStorage?.getItem("mindmapDebug") !== "1") return;
    (window as unknown as Record<string, unknown>).__mindmap = {
      nodes: () =>
        [...model.node.values()].map((n) => {
          const v = nodePosition(n);
          const p = fgRef.current?.graph2ScreenCoords(v.x, v.y);
          return { id: n.id, status: n.status, provider: n.provider, pinned: n.pinned, x: v.x, y: v.y, layoutX: n.x, layoutY: n.y, sx: p?.x, sy: p?.y };
        }),
      zoom: () => fgRef.current?.zoom(),
      camera: () => fgRef.current && readCamera(fgRef.current),
      revision: () => model.revision,
    };
    return () => { delete (window as unknown as Record<string, unknown>).__mindmap; };
  }, [model]);

  const labelLayout = useRef<Map<string, LabelPlacement> | null>(null);
  const anyActive = useMemo(() => data.nodes.some((n) => n.active), [data, redraw]); // eslint-disable-line react-hooks/exhaustive-deps
  const stepFrame = useCallback(() => {
    labelLayout.current = null;
    const fg = fgRef.current;
    // The library may have auto-scaled while applying graphData. Restore before painting.
    const initialized = fg?.d3Force("link")?.links() === model.data.links;
    if (fg && pendingCamera.current && initialized) {
      const saved = pendingCamera.current;
      pendingCamera.current = null;
      restoreCamera(fg, saved);
      camera.current = saved;
    }
    if (fg && !fitted.current && !touched.current && fg.zoom() > 1.8) fg.zoom(1.8, 0);
    if (live.current.motionOn) stepAmbient(model.node.values(), performance.now());
    for (const id of queuedParticles.current) {
      const link = model.data.links.find(l => l.id === id);
      if (!link || !live.current.motionOn || !live.current.fresh.has(id)) {
        queuedParticles.current.delete(id);
      } else if (fg && initialized && typeof link.source === "object" && typeof link.target === "object") {
        // Object endpoints prove the library has initialized the link (which clears photons).
        fg.emitParticle(link);
        queuedParticles.current.delete(id);
      }
    }
  }, [model]);

  useEffect(() => {
    for (const id of fresh) {
      if (emitted.current.has(id)) continue;
      emitted.current.add(id);
      if (motionOn) queuedParticles.current.add(id);
    }
  }, [fresh, motionOn, data]);

  // Remember centre AND zoom before the child processes a resized canvas.
  useLayoutEffect(() => {
    if (camera.current && (fitted.current || touched.current)) pendingCamera.current = camera.current;
  }, [w, h]);

  const fit = useCallback(() => {
    const fg = fgRef.current, next = fittedCamera(model.data.nodes, w, h);
    if (!fg || !next) return;
    fitted.current = true;
    pendingCamera.current = null;
    // No camera tween: it cannot fight a user pan or animate under reduced motion.
    restoreCamera(fg, next);
    camera.current = next;
  }, [model, w, h]);
  useEffect(() => {
    if (fitted.current || !data.nodes.length) return;
    const timer = window.setTimeout(() => {
      if (!touched.current && !fitted.current) fit();
    }, reduce ? 80 : 1100);
    return () => window.clearTimeout(timer);
  }, [data, reduce, fit]);

  // --- drawing ---
  const focusId = hoveredId ?? selectedNodeId;
  const neighbors = useMemo(() => {
    const s = new Set<string>();
    if (!focusId) return s;
    for (const l of data.links) {
      const a = endpointId(l.source);
      const b = endpointId(l.target);
      if (a === focusId) s.add(b);
      if (b === focusId) s.add(a);
    }
    return s;
  }, [data, focusId]);

  const nodeCanvas = useCallback(
    (n: GNode, ctx: CanvasRenderingContext2D, scale: number) => {
      const now = performance.now();
      const f = flashes.current.get(n.id);
      if (f && now - f.start > FLASH_MS) flashes.current.delete(n.id);
      drawNode(ctx, n, {
        t: live.current.motionOn ? now : null,
        selected: live.current.selected === n.id,
        hovered: live.current.hovered === n.id,
        alpha: !focusId || n.id === focusId || neighbors.has(n.id) ? 1 : 0.22,
        flash: f && now - f.start <= FLASH_MS ? { caption: f.caption, age: now - f.start, color: f.color } : null,
        zoom: scale,
        label: (labelLayout.current ??= layoutLabels(model.data.nodes, scale, live.current.hovered ?? live.current.selected)).get(n.id) ?? null,
      });
    },
    // `redraw` forces a new identity => canvas repaint when facts change in place.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [focusId, neighbors, redraw, motionOn, transient, selectedNodeId, hoveredId],
  );

  const pointerArea = useCallback((n: GNode, color: string, ctx: CanvasRenderingContext2D) => {
    ctx.fillStyle = color;
    bodyPath(ctx, n, NODE_R + 6);
    ctx.fill();
  }, []);

  const linkIncident = (l: GLink) =>
    focusId !== null && (endpointId(l.source) === focusId || endpointId(l.target) === focusId);
  const linkColor = useCallback(
    (l: GLink) =>
      focusId === null
        ? "rgba(143,180,255,0.62)"
        : linkIncident(l)
          ? "rgba(190,214,255,0.98)"
          : "rgba(143,180,255,0.12)",
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [focusId],
  );
  const linkWidth = useCallback(
    (l: GLink) => (live.current.fresh.has(l.id) ? 3.2 : linkIncident(l) ? 2.4 : 1.5),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [focusId, fresh],
  );
  const arrowPos = useCallback((l: GLink) => {
    const s = l.source as GNode;
    const t = l.target as GNode;
    if (typeof s !== "object" || typeof t !== "object") return 0.8;
    const d = Math.hypot((t.x ?? 0) - (s.x ?? 0), (t.y ?? 0) - (s.y ?? 0)) || 1;
    return Math.max(0.5, 1 - (NODE_R + 9) / d);
  }, []);

  // Fresh-link emphasis: glow + "NEW" tag while the highlight lasts (also the reduced-motion cue).
  const linkCanvas = useCallback(
    (l: GLink, ctx: CanvasRenderingContext2D, scale: number) => {
      if (!live.current.fresh.has(l.id)) return;
      const s = l.source as GNode;
      const t = l.target as GNode;
      if (typeof s !== "object" || typeof t !== "object") return;
      ctx.save();
      ctx.strokeStyle = hexA(FRESH_LINK_COLOR, 0.35);
      ctx.lineWidth = 5 / scale;
      ctx.beginPath();
      ctx.moveTo(s.x ?? 0, s.y ?? 0);
      ctx.lineTo(t.x ?? 0, t.y ?? 0);
      ctx.stroke();
      const fs = 9 / scale;
      ctx.font = `700 ${fs}px ui-sans-serif, system-ui, sans-serif`;
      const label = "NEW DELEGATION";
      const tw = ctx.measureText(label).width + 8 / scale;
      const { x: mx, y: my } = linkCaptionPosition(s, t, tw, fs * 1.8, scale);
      ctx.fillStyle = "rgba(14,18,26,0.92)";
      ctx.fillRect(mx - tw / 2, my - fs * 0.9, tw, fs * 1.8);
      ctx.fillStyle = FRESH_LINK_COLOR;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(label, mx, my);
      ctx.restore();
    },
    [fresh],
  );

  const onDragEnd = useCallback(
    (n: GNode) => {
      n.fx = n.x;
      n.fy = n.y;
      n.pinned = true;
      n.ox = 0; n.oy = 0; n.vx = 0; n.vy = 0;
      setPinCount([...model.node.values()].filter((q) => q.pinned).length);
    },
    [model],
  );

  const releasePins = useCallback(() => {
    for (const n of model.node.values()) {
      if (n.pinned) {
        n.fx = undefined;
        n.fy = undefined;
        n.pinned = false;
      }
    }
    setPinCount(0);
    fgRef.current?.d3ReheatSimulation();
  }, [model]);

  const pointer = useNetworkPointer({ fg: fgRef, nodes: data.nodes, onHover: setHoveredId, onSelect: onOpenNodeDetail, onDragEnd, onDragging: (on) => { if (on) touched.current = true; setDragging(on); } });
  const needsLoop = dragging || (motionOn && (anyActive || transient || fresh.size > 0));
  const hasNodes = data.nodes.length > 0;

  return (
    <div className="network-view">
      <AgentRoster
        nodes={activity.nodes.filter((n) => n.session)}
        edges={activity.edges}
        selectedId={selectedNodeId}
        hoveredId={hoveredId}
        onSelect={onOpenNodeDetail}
        onHover={setHoveredId}
      />
      <div
        className="network-canvas"
        ref={hostRef}
        {...pointer}
        style={{ cursor: hoveredId ? "pointer" : undefined }}
        onPointerDown={() => (touched.current = true)}
        onWheel={() => (touched.current = true)}
      >
        <ForceGraph2D<GNode, GLink>
          ref={fgRef as never}
          width={w}
          height={h}
          graphData={data}
          backgroundColor="rgba(0,0,0,0)"
          nodeId="id"
          nodeRelSize={NODE_R}
          nodeCanvasObjectMode={replaceCanvas}
          nodeCanvasObject={nodeCanvas}
          nodePointerAreaPaint={pointerArea}
          nodeLabel={noLabel}
          linkColor={linkColor}
          linkWidth={linkWidth}
          linkCurvature={0}
          linkDirectionalArrowLength={8}
          linkDirectionalArrowRelPos={arrowPos}
          linkDirectionalArrowColor={linkColor}
          linkDirectionalParticles={noContinuousParticles}
          linkDirectionalParticleSpeed={0.011}
          linkDirectionalParticleWidth={4.5}
          linkDirectionalParticleColor={particleColor}
          linkCanvasObjectMode={afterCanvas}
          linkCanvasObject={linkCanvas}
          d3AlphaMin={0.0002}
          onRenderFramePre={stepFrame}
          d3AlphaDecay={0.035}
          d3VelocityDecay={0.55}
          cooldownTime={Infinity}
          cooldownTicks={!motionOn ? 0 : Infinity}
          warmupTicks={reduce ? 420 : 0}
          autoPauseRedraw={!needsLoop}
          minZoom={0.1}
          enablePointerInteraction={false}
          enableNodeDrag={false}
          maxZoom={6}
          onZoom={() => {
            if (!pendingCamera.current && fgRef.current) camera.current = readCamera(fgRef.current);
          }}
          onNodeClick={(n) => onOpenNodeDetail(n.id)}
          onBackgroundClick={onClearNodeDetail}
          onNodeHover={(n) => setHoveredId(n ? n.id : null)}
          onNodeDragEnd={onDragEnd}
          onEngineStop={() => {
            if (!fitted.current && !touched.current && model.data.nodes.length) {
              fitted.current = true;
              fit();
            }
          }}
        />
        <div className="graph-controls network-controls">
          <button
            type="button"
            className="relayout-btn"
            aria-pressed={paused}
            disabled={reduce}
            title={reduce ? "Motion is off (reduced-motion preference)" : undefined}
            onClick={() => {
              if (paused) fgRef.current?.d3ReheatSimulation();
              setPaused((p) => !p);
            }}
          >
            {reduce || paused ? "Resume motion" : "Pause motion"}
          </button>
          <button type="button" className="relayout-btn" onClick={fit}>
            Fit view
          </button>
          {pinCount > 0 && (
            <button type="button" className="relayout-btn" onClick={releasePins}>
              Release {pinCount} pinned
            </button>
          )}
        </div>
        {!hasNodes && <p className="network-empty">No agent sessions observed yet.</p>}
      </div>
    </div>
  );
}
