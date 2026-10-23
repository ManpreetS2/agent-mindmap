import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import type { Activity, Node } from "@shared/types";
import { AgentGraph } from "../components/AgentGraph";
import { DetailPanel } from "../components/DetailPanel";
import { EdgeLegend } from "../components/EdgeLegend";
import { HandoffBanner } from "../components/HandoffBanner";
import { ListView } from "../components/ListView";
import { PartialSourceBanner } from "../components/PartialSourceBanner";
import { TimelineFilters } from "../components/TimelineFilters";
import { TimelineSwimlanes } from "../components/TimelineSwimlanes";
import { UnparsedPanel } from "../components/UnparsedPanel";
import { Button } from "../components/ui/button";
import { NumberTicker } from "../components/magic/number-ticker";
import { useResponsiveListDefault } from "../hooks/useResponsiveView";
import { formatSourceTime } from "../utils/format";
import { handoffEdgeCount } from "../utils/nodeFacts";
import {
  EMPTY_FILTERS,
  filterTimelineEvents,
  uniqueTaskIds,
  type TimelineFilterState,
} from "../utils/timelineFilters";
import { allTimelineEvents } from "../utils/timelineLanes";
import {
  edgeIdsForTaskLifecycle,
  eventIdsForTaskLifecycle,
  nodeIdsForTaskLifecycle,
} from "../utils/taskLifecycle";
import {
  focusGraphNodeButton,
  focusGraphNodeIdFromActiveElement,
  hierarchyNodeOrder,
  nearestNodeInDirection,
  type GraphDirection,
} from "../utils/graphKeyboard";
import {
  adjacentTimelineEventId,
  focusTimelineEventControl,
  orderedTimelineFocusItems,
} from "../utils/timelineKeyboard";
import {
  isActivityEmpty,
  isActivityStale,
  partialGithubBanner,
  staleAgeLabel,
  staleReferenceTime,
} from "../utils/viewState";

export interface MindmapViewProps {
  activity: Activity;
  onRefresh?: () => void;
  /** Override for tests (fixed clock). */
  nowMs?: number;
  /** Force list/graph mode (tests). */
  initialListView?: boolean;
  /** Node ids whose status just changed (pulse animation). */
  statusPulseNodeIds?: ReadonlySet<string>;
}

export function MindmapView({
  activity,
  onRefresh,
  nowMs = Date.now(),
  initialListView,
  statusPulseNodeIds,
}: MindmapViewProps) {
  const defaultList = useResponsiveListDefault();
  const [listView, setListView] = useState(initialListView ?? defaultList);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [focusedNodeId, setFocusedNodeId] = useState<string | null>(null);
  const [filters, setFilters] = useState<TimelineFilterState>(EMPTY_FILTERS);
  const [highlightedTaskId, setHighlightedTaskId] = useState<string | null>(
    null,
  );
  const filterRegionRef = useRef<HTMLDivElement>(null);
  const [focusedTimelineEventId, setFocusedTimelineEventId] = useState<
    string | null
  >(null);

  const selectedNode: Node | null = useMemo(
    () => activity.nodes.find((n) => n.id === selectedNodeId) ?? null,
    [activity.nodes, selectedNodeId],
  );

  const handoffs = useMemo(() => handoffEdgeCount(activity), [activity]);
  const nodeIds = useMemo(
    () => new Set(activity.nodes.map((n) => n.id)),
    [activity.nodes],
  );

  const allEvents = useMemo(() => allTimelineEvents(activity), [activity]);
  const visibleEvents = useMemo(
    () => filterTimelineEvents(allEvents, filters, nodeIds),
    [allEvents, filters, nodeIds],
  );
  const taskIdsForFilters = useMemo(
    () => uniqueTaskIds(allEvents),
    [allEvents],
  );

  const timelineFocusOrder = useMemo(
    () => orderedTimelineFocusItems(activity, visibleEvents),
    [activity, visibleEvents],
  );

  const highlightedEventIds = useMemo(() => {
    if (!highlightedTaskId) return new Set<string>();
    return eventIdsForTaskLifecycle(activity, highlightedTaskId);
  }, [activity, highlightedTaskId]);

  const lifecycleNodeIds = useMemo(() => {
    if (!highlightedTaskId) return null;
    return nodeIdsForTaskLifecycle(activity, highlightedTaskId);
  }, [activity, highlightedTaskId]);

  const lifecycleEdgeIds = useMemo(() => {
    if (!highlightedTaskId) return null;
    return edgeIdsForTaskLifecycle(activity, highlightedTaskId);
  }, [activity, highlightedTaskId]);

  const partialBanner = useMemo(
    () => partialGithubBanner(activity.meta),
    [activity.meta],
  );
  const staleRef = useMemo(() => staleReferenceTime(activity), [activity]);
  const stale = useMemo(
    () => isActivityStale(activity, nowMs),
    [activity, nowMs],
  );
  const empty = useMemo(() => isActivityEmpty(activity), [activity]);

  const onOpenNodeDetail = useCallback((id: string) => {
    setSelectedNodeId(id);
    setFocusedNodeId(id);
  }, []);

  const onClearNodeDetail = useCallback(() => {
    setSelectedNodeId(null);
  }, []);

  const onTaskIdClick = useCallback((taskId: string) => {
    setHighlightedTaskId((prev) => (prev === taskId ? null : taskId));
  }, []);

  const handleGraphKeyDown = useCallback(
    (e: ReactKeyboardEvent) => {
      const dirMap: Record<string, GraphDirection> = {
        ArrowUp: "up",
        ArrowDown: "down",
        ArrowLeft: "left",
        ArrowRight: "right",
      };
      const dir = dirMap[e.key];
      if (dir) {
        e.preventDefault();
        const order = hierarchyNodeOrder(activity.nodes);
        const current =
          focusedNodeId ??
          focusGraphNodeIdFromActiveElement() ??
          order[0]?.id ??
          null;
        if (!current) return;
        const next = nearestNodeInDirection(activity.nodes, current, dir);
        if (next) {
          setFocusedNodeId(next);
          focusGraphNodeButton(next);
        }
        return;
      }
      if (e.key === "Enter") {
        const fromDom = focusGraphNodeIdFromActiveElement();
        const id = fromDom ?? focusedNodeId;
        if (id) {
          e.preventDefault();
          setSelectedNodeId(id);
        }
      }
    },
    [activity.nodes, focusedNodeId],
  );

  const handleTimelineKeyDown = useCallback(
    (e: ReactKeyboardEvent) => {
      if (
        e.key !== "ArrowLeft" &&
        e.key !== "ArrowRight" &&
        e.key !== "ArrowUp" &&
        e.key !== "ArrowDown"
      ) {
        return;
      }
      e.preventDefault();
      const direction =
        e.key === "ArrowLeft" || e.key === "ArrowUp" ? "prev" : "next";
      const nextId = adjacentTimelineEventId(
        timelineFocusOrder,
        focusedTimelineEventId,
        direction,
      );
      if (nextId) {
        setFocusedTimelineEventId(nextId);
        focusTimelineEventControl(nextId);
      }
    },
    [focusedTimelineEventId, timelineFocusOrder],
  );

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (selectedNodeId) {
          setSelectedNodeId(null);
          return;
        }
        if (highlightedTaskId) {
          setHighlightedTaskId(null);
          return;
        }
        setFocusedTimelineEventId(null);
      }
      if (e.key === "/" && !e.ctrlKey && !e.metaKey && !e.altKey) {
        const target = e.target as HTMLElement;
        if (target.tagName === "INPUT" || target.tagName === "TEXTAREA") return;
        e.preventDefault();
        const firstChip = filterRegionRef.current?.querySelector<HTMLButtonElement>(
          ".filter-chip",
        );
        firstChip?.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [highlightedTaskId, selectedNodeId]);

  return (
    <div className="mindmap-layout">
      <header className="app-header">
        <div className="app-header__brand">
          <span className="app-header__title">MINDMAP</span>
          <span className="app-header__project">
            Project: {activity.project}
          </span>
        </div>
        <div className="app-header__actions">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="view-toggle"
            aria-pressed={listView}
            onClick={() => setListView((v) => !v)}
          >
            {listView ? "Graph view" : "List view"}
          </Button>
        </div>
        <div className="app-header__meta">
          <span className="app-header__handoffs" aria-label="Handoff edge count">
            Handoffs{" "}
            <NumberTicker value={handoffs} className="text-sm" />
          </span>
          <span className={stale ? "timestamp-stale" : ""}>
            Updated {formatSourceTime(activity.generated_at)}
            {stale && (
              <span className="timestamp-stale__hint">
                (stale · {staleAgeLabel(staleRef, nowMs)} — refresh)
              </span>
            )}
          </span>
          <span className="app-header__sources">
            {activity.meta.t3 ? `Source: T3 MCP · ${activity.meta.t3.mode === "demo" ? "DEMO — offline fixtures" : activity.meta.t3.connection}` : `Source: ledger + GitHub (${activity.meta.github})`}
          </span>
        </div>
      </header>

      {partialBanner && (
        <PartialSourceBanner message={partialBanner} onRetry={onRefresh} />
      )}

      {!activity.meta.t3 && <HandoffBanner handoffCount={handoffs} threshold={3} />}

      {empty && (
        <p className="empty-activity-banner" role="status">
          No activity recorded yet.
        </p>
      )}

      {highlightedTaskId && (
        <div className="lifecycle-banner" role="status">
          Lifecycle highlight:{" "}
          <span className="mono">{highlightedTaskId}</span>
          <span className="lifecycle-banner__note">
            — lifecycle may be incomplete (renamed or reused task IDs).
          </span>
        </div>
      )}

      <div id="main-content" className="mindmap-body" tabIndex={-1}>
        {listView ? (
          <div className="mindmap-main mindmap-main--list">
            <ListView
              activity={activity}
              selectedNodeId={selectedNodeId}
              onSelectNode={(id) => {
                if (id) onOpenNodeDetail(id);
                else onClearNodeDetail();
              }}
            />
            {selectedNode && (
              <DetailPanel
                node={selectedNode}
                activity={activity}
                onClose={onClearNodeDetail}
              />
            )}
          </div>
        ) : (
          <div className="mindmap-main">
            <section
              className="graph-region focus-region"
              aria-label="Agent graph"
              tabIndex={0}
              onKeyDown={handleGraphKeyDown}
            >
              <AgentGraph
                activity={activity}
                selectedNodeId={selectedNodeId}
                onOpenNodeDetail={onOpenNodeDetail}
                onClearNodeDetail={onClearNodeDetail}
                lifecycleNodeIds={lifecycleNodeIds}
                lifecycleEdgeIds={lifecycleEdgeIds}
                statusPulseNodeIds={statusPulseNodeIds}
                nowMs={nowMs}
              />
              <EdgeLegend t3={Boolean(activity.meta.t3)} />
            </section>

            {selectedNode && (
              <DetailPanel
                node={selectedNode}
                activity={activity}
                onClose={onClearNodeDetail}
              />
            )}
          </div>
        )}

        <section
          className={`timeline-region focus-region${listView ? " timeline-region--feed" : ""}`}
          aria-label="Activity timeline"
          tabIndex={0}
          onKeyDown={handleTimelineKeyDown}
        >
          <div ref={filterRegionRef}>
            <TimelineFilters
              nodes={activity.nodes}
              taskIds={taskIdsForFilters}
              filters={filters}
              onChange={setFilters}
            />
          </div>
          <TimelineSwimlanes
            activity={activity}
            events={visibleEvents}
            highlightedTaskId={highlightedTaskId}
            highlightedEventIds={highlightedEventIds}
            onTaskIdClick={onTaskIdClick}
            focusedEventId={focusedTimelineEventId}
            nowMs={nowMs}
          />
        </section>

        <UnparsedPanel lines={activity.unparsed} />
      </div>
    </div>
  );
}

