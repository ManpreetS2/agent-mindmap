import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type WheelEvent as ReactWheelEvent,
} from "react";
import type { Activity, Event } from "@shared/types";
import { glyphForEvent } from "../utils/eventGlyph";
import { formatAxisTime, buildTimeScale } from "../utils/timelineScale";
import {
  buildTimelineLanes,
  laneIdForEvent,
  type TimelineLane,
} from "../utils/timelineLanes";
import { isLifecycleTaskId } from "../utils/taskLifecycle";
import { plottableTimelineEvents } from "../utils/eventTime";
import { isHttpSourceUrl } from "../utils/sourceUrl";
import {
  brushDomainFromRatio,
  clampDomain,
  zoomDomain,
  type TimeDomain,
} from "../utils/timelineBrush";
import { UnsourcedTag } from "./UnsourcedTag";

const LABEL_WIDTH = 108;
const LANE_HEIGHT = 40;
const AXIS_HEIGHT = 20;
const BRUSH_HEIGHT = 28;

interface TimelineSwimlanesProps {
  activity: Activity;
  events: Event[];
  highlightedTaskId: string | null;
  highlightedEventIds: ReadonlySet<string>;
  onTaskIdClick: (taskId: string) => void;
  focusedEventId: string | null;
  nowMs?: number;
}

function EventMarker({
  event,
  x,
  y,
  highlighted,
  dimmed,
  onTaskIdClick,
  focused,
}: {
  event: Event;
  x: number;
  y: number;
  highlighted: boolean;
  dimmed: boolean;
  onTaskIdClick: (taskId: string) => void;
  focused: boolean;
}) {
  const glyph = glyphForEvent(event);
  const hasSource = isHttpSourceUrl(event.source_url);
  const hasTaskChip =
    Boolean(event.task_id) && isLifecycleTaskId(event.task_id!);
  const repoLabel =
    typeof event.repo === "string" && event.repo.includes("/")
      ? event.repo
      : null;
  const opacity = dimmed ? 0.25 : 1;
  const stroke = highlighted ? "var(--accent)" : "var(--border-subtle)";
  const titleText = repoLabel ? `${glyph.title} · ${repoLabel}` : glyph.title;

  const markerBody = (
    <g opacity={opacity} transform={`translate(${x - 10}, ${y - 8})`}>
      <rect
        x={0}
        y={0}
        width={20}
        height={16}
        rx={3}
        fill="var(--bg-elevated)"
        stroke={stroke}
        strokeWidth={highlighted ? 2 : 1}
      />
      <text
        x={10}
        y={11}
        textAnchor="middle"
        className="timeline-glyph-label"
        aria-hidden="true"
      >
        {glyph.label}
      </text>
      <title>{titleText}</title>
    </g>
  );

  return (
    <g className="timeline-event-marker">
      <foreignObject x={x - 14} y={y - 14} width={28} height={28}>
        <button
          type="button"
          className="timeline-event-focus-btn"
          data-timeline-focus={event.id}
          tabIndex={focused ? 0 : -1}
          aria-label={titleText}
        >
          <span className="sr-only">{glyph.label}</span>
        </button>
      </foreignObject>
      {hasSource ? (
        <a
          href={event.source_url}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={`${titleText}. Open event source in new tab.`}
        >
          {markerBody}
        </a>
      ) : (
        <g>{markerBody}</g>
      )}
      {hasTaskChip && (
        <foreignObject
          x={x + 12}
          y={y - 10}
          width={72}
          height={20}
          opacity={opacity}
        >
          <button
            type="button"
            className="timeline-task-btn mono"
            data-testid={`timeline-task-${event.task_id}`}
            onClick={() => onTaskIdClick(event.task_id!)}
            title={`Highlight lifecycle for ${event.task_id}`}
          >
            {event.task_id}
          </button>
        </foreignObject>
      )}
      {repoLabel && (
        <foreignObject
          x={hasTaskChip ? x + 88 : x + 14}
          y={y - 10}
          width={120}
          height={20}
          opacity={opacity}
        >
          <span
            className="timeline-repo-tag mono"
            data-testid={`timeline-repo-${event.id}`}
            title={repoLabel}
          >
            {repoLabel.split("/")[1] ?? repoLabel}
          </span>
        </foreignObject>
      )}
      {!hasSource && (
        <foreignObject
          x={
            hasTaskChip && repoLabel
              ? x + 212
              : hasTaskChip || repoLabel
                ? x + 88
                : x + 14
          }
          y={hasTaskChip || repoLabel ? y - 10 : y - 8}
          width={hasTaskChip || repoLabel ? 88 : 100}
          height={20}
          opacity={opacity}
        >
          <UnsourcedTag />
        </foreignObject>
      )}
    </g>
  );
}

export function TimelineSwimlanes({
  activity,
  events,
  highlightedTaskId,
  highlightedEventIds,
  onTaskIdClick,
  focusedEventId,
  nowMs = Date.now(),
}: TimelineSwimlanesProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(900);
  const plottable = useMemo(() => plottableTimelineEvents(events), [events]);

  const fullDomain = useMemo((): TimeDomain => {
    const scale = buildTimeScale(plottable, width);
    return { minMs: scale.minMs, maxMs: scale.maxMs };
  }, [plottable, width]);

  const [viewDomain, setViewDomain] = useState<TimeDomain | null>(null);
  const domain = viewDomain
    ? clampDomain(viewDomain, fullDomain)
    : fullDomain;

  useEffect(() => {
    setViewDomain(null);
  }, [fullDomain.minMs, fullDomain.maxMs]);

  const nodeIds = useMemo(
    () => new Set(activity.nodes.map((n) => n.id)),
    [activity.nodes],
  );
  const lanes = useMemo(() => buildTimelineLanes(activity.nodes), [activity.nodes]);
  const laneIndex = useMemo(() => {
    const map = new Map<string, number>();
    lanes.forEach((lane, i) => map.set(lane.id, i));
    return map;
  }, [lanes]);

  const scale = useMemo(() => {
    const paddingPx = 24;
    const inner = Math.max(1, width - paddingPx * 2);
    const span = Math.max(1, domain.maxMs - domain.minMs);
    return {
      minMs: domain.minMs,
      maxMs: domain.maxMs,
      toX: (ms: number) => paddingPx + ((ms - domain.minMs) / span) * inner,
    };
  }, [domain, width]);

  const brushScale = useMemo(() => {
    const paddingPx = LABEL_WIDTH;
    const inner = Math.max(1, width - paddingPx - 16);
    const span = Math.max(1, fullDomain.maxMs - fullDomain.minMs);
    return {
      toX: (ms: number) =>
        paddingPx + ((ms - fullDomain.minMs) / span) * inner,
      fromClientX: (clientX: number, rectLeft: number) => {
        const x = clientX - rectLeft;
        const ratio = Math.min(1, Math.max(0, (x - paddingPx) / inner));
        return ratio;
      },
    };
  }, [fullDomain, width]);

  const svgHeight = lanes.length * LANE_HEIGHT + AXIS_HEIGHT;
  const brushDragging = useRef<{ start: number } | null>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w && w > 0) setWidth(w);
    });
    ro.observe(el);
    setWidth(el.clientWidth || 900);
    return () => ro.disconnect();
  }, []);

  const axisTicks = useMemo(() => {
    if (plottable.length === 0) return [];
    const mid = (domain.minMs + domain.maxMs) / 2;
    return [
      { ms: domain.minMs, label: formatAxisTime(new Date(domain.minMs).toISOString()) },
      { ms: mid, label: formatAxisTime(new Date(mid).toISOString()) },
      { ms: domain.maxMs, label: formatAxisTime(new Date(domain.maxMs).toISOString()) },
    ];
  }, [plottable.length, domain]);

  const lifecycleActive = highlightedTaskId !== null;
  const nowX = scale.toX(nowMs);
  const showNow =
    nowMs >= domain.minMs - 60_000 && nowMs <= domain.maxMs + 60_000;

  const onWheel = useCallback(
    (e: ReactWheelEvent) => {
      if (!e.ctrlKey && Math.abs(e.deltaY) < 2) return;
      e.preventDefault();
      const factor = e.deltaY > 0 ? 1.15 : 0.85;
      setViewDomain((prev) =>
        zoomDomain(prev ?? fullDomain, fullDomain, factor),
      );
    },
    [fullDomain],
  );

  const onBrushPointerDown = useCallback(
    (e: ReactPointerEvent<SVGRectElement>) => {
      const svg = e.currentTarget.ownerSVGElement;
      if (!svg) return;
      const rect = svg.getBoundingClientRect();
      const ratio = brushScale.fromClientX(e.clientX, rect.left);
      brushDragging.current = { start: ratio };
      e.currentTarget.setPointerCapture(e.pointerId);
    },
    [brushScale],
  );

  const onBrushPointerMove = useCallback(
    (e: ReactPointerEvent<SVGRectElement>) => {
      if (!brushDragging.current) return;
      const svg = e.currentTarget.ownerSVGElement;
      if (!svg) return;
      const rect = svg.getBoundingClientRect();
      const end = brushScale.fromClientX(e.clientX, rect.left);
      setViewDomain(
        brushDomainFromRatio(fullDomain, brushDragging.current.start, end),
      );
    },
    [brushScale, fullDomain],
  );

  const onBrushPointerUp = useCallback(() => {
    brushDragging.current = null;
  }, []);

  const brushStartRatio =
    (domain.minMs - fullDomain.minMs) /
    Math.max(1, fullDomain.maxMs - fullDomain.minMs);
  const brushEndRatio =
    (domain.maxMs - fullDomain.minMs) /
    Math.max(1, fullDomain.maxMs - fullDomain.minMs);
  const brushPad = LABEL_WIDTH;
  const brushInner = Math.max(1, width - brushPad - 16);
  const brushX = brushPad + brushStartRatio * brushInner;
  const brushW = Math.max(8, (brushEndRatio - brushStartRatio) * brushInner);

  return (
    <div
      ref={containerRef}
      className="timeline-swimlanes"
      role="group"
      aria-label="Activity timeline swim lanes"
      onWheel={onWheel}
    >
      <div className="timeline-zoom-controls" role="toolbar" aria-label="Timeline zoom">
        <button
          type="button"
          className="timeline-zoom-btn"
          onClick={() =>
            setViewDomain((prev) =>
              zoomDomain(prev ?? fullDomain, fullDomain, 0.75),
            )
          }
        >
          Zoom in
        </button>
        <button
          type="button"
          className="timeline-zoom-btn"
          onClick={() =>
            setViewDomain((prev) =>
              zoomDomain(prev ?? fullDomain, fullDomain, 1.35),
            )
          }
        >
          Zoom out
        </button>
        <button
          type="button"
          className="timeline-zoom-btn"
          onClick={() => setViewDomain(null)}
        >
          Reset
        </button>
      </div>
      <svg
        width={width}
        height={svgHeight}
        className="timeline-svg"
      >
        {lanes.map((lane: TimelineLane, index) => {
          const y = index * LANE_HEIGHT + 4;
          return (
            <g key={lane.id}>
              <text x={4} y={y + 12} className="timeline-lane-label">
                <title>{lane.label}</title>
                {lane.label.length > 14
                  ? `${lane.label.slice(0, 13)}…`
                  : lane.label}
              </text>
              <line
                x1={LABEL_WIDTH}
                y1={y + 14}
                x2={width}
                y2={y + 14}
                className="timeline-lane-line"
              />
            </g>
          );
        })}
        {showNow && (
          <g className="timeline-now-line" aria-hidden="true">
            <line
              x1={nowX}
              y1={0}
              x2={nowX}
              y2={svgHeight - AXIS_HEIGHT}
              className="timeline-now-stroke"
            />
            <text
              x={nowX + 4}
              y={12}
              className="timeline-now-label"
            >
              now
            </text>
          </g>
        )}
        {axisTicks.map((tick, i) => (
          <text
            key={`${tick.ms}-${i}`}
            x={scale.toX(tick.ms)}
            y={svgHeight - 4}
            textAnchor="middle"
            className="timeline-axis-label"
          >
            {tick.label}
          </text>
        ))}
        {plottable.map((event) => {
          const lane = laneIdForEvent(event, nodeIds);
          const index = laneIndex.get(lane) ?? lanes.length - 1;
          const y = index * LANE_HEIGHT + 12;
          const t = new Date(event.source_time).getTime();
          if (t < domain.minMs || t > domain.maxMs) return null;
          const x = scale.toX(t);
          const highlighted = highlightedEventIds.has(event.id);
          const dimmed =
            lifecycleActive && event.task_id !== highlightedTaskId;
          return (
            <EventMarker
              key={event.id}
              event={event}
              x={x}
              y={y}
              highlighted={highlighted}
              dimmed={dimmed}
              onTaskIdClick={onTaskIdClick}
              focused={focusedEventId === event.id}
            />
          );
        })}
      </svg>
      <svg
        width={width}
        height={BRUSH_HEIGHT}
        className="timeline-brush"
        aria-label="Timeline brush"
        role="slider"
        aria-valuemin={fullDomain.minMs}
        aria-valuemax={fullDomain.maxMs}
        aria-valuenow={domain.minMs}
      >
        <rect
          x={brushPad}
          y={6}
          width={brushInner}
          height={16}
          className="timeline-brush-track"
          onPointerDown={onBrushPointerDown}
          onPointerMove={onBrushPointerMove}
          onPointerUp={onBrushPointerUp}
        />
        <rect
          x={brushX}
          y={4}
          width={brushW}
          height={20}
          rx={3}
          className="timeline-brush-window"
          onPointerDown={onBrushPointerDown}
          onPointerMove={onBrushPointerMove}
          onPointerUp={onBrushPointerUp}
        />
      </svg>
    </div>
  );
}
