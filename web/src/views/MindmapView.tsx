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
import { AgentNetwork } from "../components/AgentNetwork";
import { NetworkLegend } from "../components/NetworkLegend";
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
import { agentMetrics, sourceKind } from "../utils/headerMetrics";
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
  // The breakpoint is only known after mount: follow it unless a test forces a view.
  useEffect(() => {
    if (initialListView === undefined) setListView(defaultList);
  }, [defaultList, initialListView]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [focusedNodeId, setFocusedNodeId] = useState<string | null>(null);
  const [filters, setFilters] = useState<TimelineFilterState>(EMPTY_FILTERS);
  const [highlightedTaskId, setHighlightedTaskId] = useState<string | null>(
    null,
  );
  const filterRegionRef = useRef<HTMLDivElement>(null);
  // The legacy timeline is a drawer for T3 sessions (the network is the centrepiece); the ledger
  // view keeps it open as before.
  const [timelineOpen, setTimelineOpen] = useState(() => !activity.meta.t3);
  const [focusedTimelineEventId, setFocusedTimelineEventId] = useState<
    string | null
  >(null);

  const selectedNode: Node | null = useMemo(
    () => activity.nodes.find((n) => n.id === selectedNodeId) ?? null,
    [activity.nodes, selectedNodeId],
  );

  const handoffs = useMemo(() => handoffEdgeCount(activity), [activity]);
  const metrics = useMemo(() => agentMetrics(activity), [activity]);
  const kind = sourceKind(activity);
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
        setTimelineOpen(true);
        window.setTimeout(() => {
          filterRegionRef.current?.querySelector<HTMLButtonElement>(".filter-chip")?.focus();
        }, 0);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [highlightedTaskId, selectedNodeId]);

  return (
    <div className="mindmap-layout">
      {activity.meta.t3?.mode === "demo" && activity.meta.t3.replay && (
        <div
          className="demo-replay-banner"
          role="status"
          aria-live="polite"
          title="Synthetic replay: no agents are connected and no API calls are made. Everything shown is simulated."
        >
          <strong>DEMO REPLAY — SIMULATED ACTIVITY</strong>
          <span>No agents connected · no API calls</span>
          <span>Cycle {activity.meta.t3.replay.cycle + 1} · Stage {activity.meta.t3.replay.stage + 1}/{activity.meta.t3.replay.stage_count}: {activity.meta.t3.replay.label}</span>
        </div>
      )}
      {activity.meta.t3?.mode === "demo" && !activity.meta.t3.replay && (
        <div
          className="demo-replay-banner"
          role="status"
          title="Synthetic fixture: these example agents are not real T3 activity and no API calls are made."
        >
          <strong>DEMO — SYNTHETIC FIXTURE DATA</strong>
          <span>Offline example agents · not real T3 activity · no API calls</span>
        </div>
      )}
      <header className="app-header">
        <div className="app-header__brand">
          <span className="brand-mark" aria-hidden="true"><i /><i /><i /></span>
          <span className="app-header__title">MINDMAP</span>
          <span className="app-header__project" title={`Project: ${activity.project}`}>
            {activity.project}
          </span>
        </div>
        <div className="app-header__center">
          <span className={`source-chip source-chip--${kind}`}>
            <span className="source-chip__dot" aria-hidden="true" />
            {activity.meta.t3 ? `Source: ${activity.meta.t3.replay && activity.meta.t3.mode === "demo" ? "Synthetic replay" : `T3 MCP · ${activity.meta.t3.mode === "demo" ? "DEMO — offline fixtures" : activity.meta.t3.connection}`}` : `Source: ledger + GitHub (${activity.meta.github})`}
          </span>
          {activity.meta.t3 ? (
            <ul className="metric-list" aria-label="Agent summary">
              <li className="metric"><strong>{metrics.total}</strong> agent{metrics.total === 1 ? "" : "s"}</li>
              {metrics.working > 0 && <li className="metric metric--working"><i aria-hidden="true" /><strong>{metrics.working}</strong> working</li>}
              {metrics.blocked > 0 && <li className="metric metric--blocked"><i aria-hidden="true" /><strong>{metrics.blocked}</strong> blocked</li>}
              {metrics.failed > 0 && <li className="metric metric--failed"><i aria-hidden="true" /><strong>{metrics.failed}</strong> failed</li>}
              <li
                className="metric metric--delegations"
                aria-label="Delegation relationship count"
                title="Parent → child delegations reported by T3. Lineage only — not messages. (Legacy ledger 'handoffs' are a different concept.)"
              >
                <strong>{metrics.delegations}</strong> delegation{metrics.delegations === 1 ? "" : "s"}
              </li>
            </ul>
          ) : (
            <span className="app-header__handoffs" aria-label="Handoff edge count">
              Handoffs{" "}
              <NumberTicker value={handoffs} className="text-sm" />
            </span>
          )}
        </div>
        <div className="app-header__meta">
          <span className={stale ? "timestamp-stale" : ""}>
            Updated {formatSourceTime(activity.generated_at)}
            {stale && (
              <span className="timestamp-stale__hint">
                (stale · {staleAgeLabel(staleRef, nowMs)} — refresh)
              </span>
            )}
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
                onSelectNode={onOpenNodeDetail}
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
              {activity.meta.t3 ? (
                <>
                  <AgentNetwork
                    activity={activity}
                    selectedNodeId={selectedNodeId}
                    onOpenNodeDetail={onOpenNodeDetail}
                    onClearNodeDetail={onClearNodeDetail}
                  />
                  <NetworkLegend simulated={activity.meta.t3.mode === "demo"} />
                </>
              ) : (
                <>
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
                  <EdgeLegend />
                </>
              )}
            </section>

            {selectedNode && (
              <DetailPanel
                node={selectedNode}
                activity={activity}
                onClose={onClearNodeDetail}
                onSelectNode={onOpenNodeDetail}
              />
            )}
          </div>
        )}

        <section
          className={`timeline-region focus-region${listView ? " timeline-region--feed" : ""}${activity.meta.t3 ? " timeline-region--overlay" : ""}${timelineOpen ? "" : " is-collapsed"}`}
          aria-label="Activity timeline"
          tabIndex={0}
          onKeyDown={handleTimelineKeyDown}
        >
          <button
            type="button"
            className="timeline-toggle"
            aria-expanded={timelineOpen}
            aria-controls="timeline-drawer"
            onClick={() => setTimelineOpen((o) => !o)}
          >
            <span className="timeline-toggle__chev" aria-hidden="true">{timelineOpen ? "▾" : "▸"}</span>
            <span className="timeline-toggle__title">Activity timeline</span>
            <span className="timeline-toggle__count">{visibleEvents.length} event{visibleEvents.length === 1 ? "" : "s"}</span>
            <span className="timeline-toggle__hint">{timelineOpen ? "Hide filters & history" : "Filters & history"}</span>
          </button>
          <div id="timeline-drawer" className="timeline-drawer" hidden={!timelineOpen}>
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
          </div>
        </section>

        <UnparsedPanel lines={activity.unparsed} />
      </div>
    </div>
  );
}

