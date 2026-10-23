import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D, { type ForceGraphMethods } from "react-force-graph-2d";
import { forceCollide, forceX, forceY } from "d3-force";
import type { Activity } from "@shared/types";
import { useFreshEdges } from "../hooks/useFreshEdges";
import { useReducedMotionPreference } from "../hooks/useReducedMotion";
import { sourceKey } from "../utils/edgeActivity";
import {
  NetworkModel,
  endpointId,
  stepAmbient,
  transitionCaption,
  type GLink,
  type GNode,
} from "../utils/networkModel";
import { NODE_R, STATUS_COLOR, bodyPath, drawNode, hexA } from "../utils/nodeDraw";
import { AgentRoster } from "./AgentRoster";

const FLASH_MS = 2400;
const FRESH_LINK_COLOR = "#8fb4ff";

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
  const flashes = useRef(new Map<string, { caption: string; start: number; color: string }>());
  const fresh = useFreshEdges(activity);
  const emitted = useRef(new Set<string>());
  const center = useRef<{ x: number; y: number } | null>(null);
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
    }
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
      window.setTimeout(() => setTransient(false), FLASH_MS + 100);
    }
    if (r.topologyChanged) setData(model.data);
    setPinCount([...model.node.values()].filter((n) => n.pinned).length);
    setRedraw((v) => v + 1);
  }, [activity, model]);

  // --- forces (registered once; tuned for ~3–40 circular nodes with labels) ---
  useEffect(() => {
    const fg = fgRef.current;
    if (!fg) return;
    fg.d3Force("charge")?.strength(-230).distanceMax(380);
    fg.d3Force("link")?.distance(96).strength(0.55);
    fg.d3Force("center", null as never);
    fg.d3Force("x", forceX(0).strength(0.045) as never);
    fg.d3Force("y", forceY(0).strength(0.045) as never);
    fg.d3Force("collide", forceCollide(NODE_R + 24).strength(0.9).iterations(2) as never);
  }, [model]);

  // Opt-in debug/QA hook (localStorage.mindmapDebug = "1"): node screen positions for browser tests.
  useEffect(() => {
    if (typeof window === "undefined" || window.localStorage?.getItem("mindmapDebug") !== "1") return;
    (window as unknown as Record<string, unknown>).__mindmap = {
      nodes: () =>
        [...model.node.values()].map((n) => {
          const p = fgRef.current?.graph2ScreenCoords(n.x ?? 0, n.y ?? 0);
          return { id: n.id, status: n.status, pinned: n.pinned, x: n.x, y: n.y, sx: p?.x, sy: p?.y };
        }),
      zoom: () => fgRef.current?.zoom(),
    };
  }, [model]);

  const anyActive = useMemo(() => data.nodes.some((n) => n.active), [data, redraw]); // eslint-disable-line react-hooks/exhaustive-deps
  const stepFrame = useCallback(() => {
    if (live.current.motionOn) stepAmbient(model.node.values(), performance.now());
  }, [model]);

  // --- one-shot particle for newly observed, evidence-backed delegations ---
  useEffect(() => {
    const fg = fgRef.current;
    for (const id of [...emitted.current]) if (!fresh.has(id)) emitted.current.delete(id);
    if (!fg) return;
    for (const id of fresh) {
      if (emitted.current.has(id)) continue;
      emitted.current.add(id);
      const link = model.data.links.find((l) => l.id === id);
      if (!link) continue;
      setTransient(true);
      window.setTimeout(() => setTransient(false), 6200);
      if (live.current.motionOn || !reduce) {
        if (!reduce) {
          fg.emitParticle(link);
          window.setTimeout(() => fgRef.current?.emitParticle(link), 420);
        }
      }
    }
  }, [fresh, model, reduce, data]);

  // Opening the inspector resizes the canvas: keep the same world point at the view centre.
  useLayoutEffect(() => {
    if (center.current && fitted.current) fgRef.current?.centerAt(center.current.x, center.current.y, 0);
  }, [w, h]);

  // --- camera: fit once, never on polls; stop auto-fit once the user touches the view ---
  const fit = useCallback(() => fgRef.current?.zoomToFit(450, 70), []);
  useEffect(() => {
    if (fitted.current || data.nodes.length === 0) return;
    const t = window.setTimeout(
      () => {
        if (!touched.current && !fitted.current) {
          fitted.current = true;
          fit();
        }
      },
      reduce ? 80 : 1100,
    );
    return () => window.clearTimeout(t);
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
      });
    },
    // `redraw` forces a new identity => canvas repaint when facts change in place.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [focusId, neighbors, redraw],
  );

  const pointerArea = useCallback((n: GNode, color: string, ctx: CanvasRenderingContext2D) => {
    ctx.fillStyle = color;
    bodyPath(ctx, n, NODE_R + 8);
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
      const mx = ((s.x ?? 0) + (t.x ?? 0)) / 2;
      const my = ((s.y ?? 0) + (t.y ?? 0)) / 2;
      ctx.save();
      ctx.strokeStyle = hexA(FRESH_LINK_COLOR, 0.35);
      ctx.lineWidth = 7;
      ctx.beginPath();
      ctx.moveTo(s.x ?? 0, s.y ?? 0);
      ctx.lineTo(t.x ?? 0, t.y ?? 0);
      ctx.stroke();
      const fs = Math.max(3, 8 / Math.max(scale, 0.6));
      ctx.font = `700 ${fs}px ui-sans-serif, system-ui, sans-serif`;
      const label = "NEW DELEGATION";
      const tw = ctx.measureText(label).width + 8;
      ctx.fillStyle = "rgba(14,18,26,0.92)";
      ctx.fillRect(mx - tw / 2, my - fs * 0.9, tw, fs * 1.8);
      ctx.fillStyle = FRESH_LINK_COLOR;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(label, mx, my);
      ctx.restore();
    },
    [],
  );

  const onDragEnd = useCallback(
    (n: GNode) => {
      n.fx = n.x;
      n.fy = n.y;
      n.pinned = true;
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

  const needsLoop = motionOn && (anyActive || transient);
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
          nodeCanvasObjectMode={() => "replace"}
          nodeCanvasObject={nodeCanvas}
          nodePointerAreaPaint={pointerArea}
          nodeLabel={() => ""}
          linkColor={linkColor}
          linkWidth={linkWidth}
          linkCurvature={0.08}
          linkDirectionalArrowLength={8}
          linkDirectionalArrowRelPos={arrowPos}
          linkDirectionalArrowColor={linkColor}
          linkDirectionalParticleSpeed={0.011}
          linkDirectionalParticleWidth={4.5}
          linkDirectionalParticleColor={() => "#e8f0ff"}
          linkCanvasObjectMode={() => "after"}
          linkCanvasObject={linkCanvas}
          d3AlphaMin={0.004}
          onRenderFramePre={stepFrame}
          d3AlphaDecay={0.026}
          d3VelocityDecay={0.4}
          cooldownTime={Infinity}
          cooldownTicks={reduce ? 0 : Infinity}
          warmupTicks={reduce ? 420 : 0}
          autoPauseRedraw={!needsLoop}
          minZoom={0.3}
          maxZoom={6}
          onZoom={() => {
            const c = fgRef.current?.centerAt();
            if (c && Number.isFinite(c.x) && Number.isFinite(c.y)) center.current = c;
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
            onClick={() => setPaused((p) => !p)}
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
