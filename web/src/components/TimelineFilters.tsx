import type { Node } from "@shared/types";
import {
  EMPTY_FILTERS,
  type EventTypeGroup,
  type TimelineFilterState,
} from "../utils/timelineFilters";

const TYPE_GROUP_CHIPS: { id: EventTypeGroup; label: string }[] = [
  { id: "handoffs", label: "Handoffs" },
  { id: "verdicts", label: "Verdicts" },
  { id: "prs", label: "PRs" },
  { id: "merged", label: "Merged" },
  { id: "blockers", label: "Blockers" },
  { id: "notes", label: "Notes" },
  { id: "ci", label: "CI" },
  { id: "unparsed", label: "Unparsed" },
];

interface TimelineFiltersProps {
  nodes: Node[];
  taskIds: string[];
  filters: TimelineFilterState;
  onChange: (next: TimelineFilterState) => void;
}

function toggleInSet<T>(set: Set<T>, value: T): Set<T> {
  const next = new Set(set);
  if (next.has(value)) next.delete(value);
  else next.add(value);
  return next;
}

export function TimelineFilters({
  nodes,
  taskIds,
  filters,
  onChange,
}: TimelineFiltersProps) {
  const toggleGroup = (group: EventTypeGroup) => {
    onChange({
      ...filters,
      eventGroups: toggleInSet(filters.eventGroups, group),
    });
  };

  const toggleBot = (botId: string) => {
    onChange({ ...filters, botIds: toggleInSet(filters.botIds, botId) });
  };

  const toggleTask = (taskId: string) => {
    onChange({ ...filters, taskIds: toggleInSet(filters.taskIds, taskId) });
  };

  const clearAll = () => onChange(EMPTY_FILTERS);

  const anyActive =
    filters.eventGroups.size > 0 ||
    filters.botIds.size > 0 ||
    filters.taskIds.size > 0;

  return (
    <div className="timeline-filters" aria-label="Timeline filters">
      <div className="timeline-filters__row">
        <span className="timeline-filters__heading">Type</span>
        <button
          type="button"
          className="filter-chip"
          aria-pressed={!anyActive}
          onClick={clearAll}
        >
          All
        </button>
        {TYPE_GROUP_CHIPS.map((chip) => (
          <button
            key={chip.id}
            type="button"
            className="filter-chip"
            aria-pressed={filters.eventGroups.has(chip.id)}
            onClick={() => toggleGroup(chip.id)}
          >
            {chip.label}
          </button>
        ))}
      </div>
      <div className="timeline-filters__row">
        <span className="timeline-filters__heading">Bot</span>
        {nodes.map((n) => (
          <button
            key={n.id}
            type="button"
            className="filter-chip filter-chip--compact"
            aria-pressed={filters.botIds.has(n.id)}
            onClick={() => toggleBot(n.id)}
          >
            {n.label}
          </button>
        ))}
        <button
          type="button"
          className="filter-chip filter-chip--compact"
          aria-pressed={filters.botIds.has("unknown")}
          onClick={() => toggleBot("unknown")}
        >
          unknown
        </button>
      </div>
      {taskIds.length > 0 && (
        <div className="timeline-filters__row">
          <span className="timeline-filters__heading">Task</span>
          {taskIds.map((id) => (
            <button
              key={id}
              type="button"
              className="filter-chip filter-chip--mono"
              aria-pressed={filters.taskIds.has(id)}
              onClick={() => toggleTask(id)}
            >
              {id}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
