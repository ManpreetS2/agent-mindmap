import { useEffect, useMemo, useRef, useState } from "react";
import type { Activity, Event } from "@shared/types";
import { glyphForEvent } from "../utils/eventGlyph";
import { formatAxisTime, buildTimeScale } from "../utils/timelineScale";
import {
  buildTimelineLanes,
  laneIdForEvent,
  type TimelineLane,
} from "../utils/timelineLanes";
import { isLifecycleTaskId } from "../utils/taskLifecycle";
import { UnsourcedTag } from "./UnsourcedTag";

const LABEL_WIDTH = 108;
const LANE_HEIGHT = 18;
const AXIS_HEIGHT = 20;

interface TimelineSwimlanesProps {
  activity: Activity;
  events: Event[];
  highlightedTaskId: string | null;
  highlightedEventIds: ReadonlySet<string>;
  onTaskIdClick: (taskId: string) => void;
}

function EventMarker({
  event,
  x,
  y,
  highlighted,
  dimmed,
  onTaskIdClick,
}: {
  event: Event;
  x: number;
  y: number;
  highlighted: boolean;
  dimmed: boolean;
  onTaskIdClick: (taskId: string) => void;
}) {
  const glyph = glyphForEvent(event);
  const hasSource = Boolean(event.source_url);
  const opacity = dimmed ? 0.25 : 1;
  const stroke = highlighted ? "var(--accent)" : "var(--border-subtle)";

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
      <title>{glyph.title}</title>
    </g>
  );

  return (
    <g className="timeline-event-marker">
      {hasSource ? (
        <a href={event.source_url} target="_blank" rel="noopener noreferrer">
          {markerBody}
        </a>
      ) : (
        <g>{markerBody}</g>
      )}
      {event.task_id && isLifecycleTaskId(event.task_id) && (
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
      {!hasSource && (
        <foreignObject x={x - 8} y={y + 10} width={80} height={18} opacity={opacity}>
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
}: TimelineSwimlanesProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(900);

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

  const scale = useMemo(() => buildTimeScale(events, width), [events, width]);

  const svgHeight = lanes.length * LANE_HEIGHT + AXIS_HEIGHT;

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
    if (events.length === 0) return [];
    const times = events.map((e) => new Date(e.source_time).getTime());
    const min = Math.min(...times);
    const max = Math.max(...times);
    const mid = (min + max) / 2;
    return [
      { ms: min, label: formatAxisTime(new Date(min).toISOString()) },
      { ms: mid, label: formatAxisTime(new Date(mid).toISOString()) },
      { ms: max, label: formatAxisTime(new Date(max).toISOString()) },
    ];
  }, [events]);

  const lifecycleActive = highlightedTaskId !== null;

  return (
    <div
      ref={containerRef}
      className="timeline-swimlanes"
      role="img"
      aria-label="Activity timeline swim lanes"
    >
      <svg
        width={width}
        height={svgHeight}
        className="timeline-svg"
        aria-hidden="false"
      >
        {lanes.map((lane: TimelineLane, index) => {
          const y = index * LANE_HEIGHT + 4;
          return (
            <g key={lane.id}>
              <text
                x={4}
                y={y + 12}
                className="timeline-lane-label"
              >
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
        {events.map((event) => {
          const lane = laneIdForEvent(event, nodeIds);
          const index = laneIndex.get(lane) ?? lanes.length - 1;
          const y = index * LANE_HEIGHT + 12;
          const x = scale.toX(new Date(event.source_time).getTime());
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
            />
          );
        })}
      </svg>
    </div>
  );
}
