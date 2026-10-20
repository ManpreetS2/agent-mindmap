import { useCallback, useEffect, useMemo, useState } from "react";
import type { Activity, Node } from "@shared/types";
import { AgentGraph } from "../components/AgentGraph";
import { DetailPanel } from "../components/DetailPanel";
import { EdgeLegend } from "../components/EdgeLegend";
import { HandoffBanner } from "../components/HandoffBanner";
import { TimelineFilters } from "../components/TimelineFilters";
import { TimelineSwimlanes } from "../components/TimelineSwimlanes";
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

export interface MindmapViewProps {
  activity: Activity;
}

export function MindmapView({ activity }: MindmapViewProps) {
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [filters, setFilters] = useState<TimelineFilterState>(EMPTY_FILTERS);
  const [highlightedTaskId, setHighlightedTaskId] = useState<string | null>(
    null,
  );

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

  const onSelectNode = useCallback((id: string | null) => {
    setSelectedNodeId(id);
  }, []);

  const onTaskIdClick = useCallback((taskId: string) => {
    setHighlightedTaskId((prev) => (prev === taskId ? null : taskId));
  }, []);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setSelectedNodeId(null);
        setHighlightedTaskId(null);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <div className="mindmap-layout">
      <header className="app-header">
        <div className="app-header__brand">
          <span className="app-header__title">MINDMAP</span>
          <span className="app-header__project">
            Project: {activity.project}
          </span>
        </div>
        <div className="app-header__meta">
          <span>Updated {formatSourceTime(activity.generated_at)}</span>
          <span className="app-header__sources">
            Source: ledger + GitHub ({activity.meta.github})
          </span>
        </div>
      </header>

      <HandoffBanner handoffCount={handoffs} threshold={3} />

      {highlightedTaskId && (
        <div className="lifecycle-banner" role="status">
          Lifecycle highlight:{" "}
          <span className="mono">{highlightedTaskId}</span>
          <span className="lifecycle-banner__note">
            — lifecycle may be incomplete (renamed or reused task IDs).
          </span>
        </div>
      )}

      <div className="mindmap-body">
        <div className="mindmap-main">
          <section className="graph-region" aria-label="Agent graph">
            <AgentGraph
              activity={activity}
              selectedNodeId={selectedNodeId}
              onSelectNode={onSelectNode}
              lifecycleNodeIds={lifecycleNodeIds}
              lifecycleEdgeIds={lifecycleEdgeIds}
            />
            <EdgeLegend />
          </section>

          {selectedNode && (
            <DetailPanel
              node={selectedNode}
              activity={activity}
              onClose={() => setSelectedNodeId(null)}
            />
          )}
        </div>

        <section className="timeline-region" aria-label="Activity timeline">
          <TimelineFilters
            nodes={activity.nodes}
            taskIds={taskIdsForFilters}
            filters={filters}
            onChange={setFilters}
          />
          <TimelineSwimlanes
            activity={activity}
            events={visibleEvents}
            highlightedTaskId={highlightedTaskId}
            highlightedEventIds={highlightedEventIds}
            onTaskIdClick={onTaskIdClick}
          />
        </section>
      </div>
    </div>
  );
}
