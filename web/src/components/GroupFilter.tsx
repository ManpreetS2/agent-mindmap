import { labelForGroup } from "../utils/groupMembership";

export interface GroupFilterProps {
  groupIds: string[];
  selected: ReadonlySet<string>;
  onChange: (next: Set<string>) => void;
}

export function GroupFilter({ groupIds, selected, onChange }: GroupFilterProps) {
  if (groupIds.length === 0) return null;

  const allSelected = groupIds.every((g) => selected.has(g));

  return (
    <div
      className="group-filter"
      role="group"
      aria-label="Filter groups"
      data-testid="group-filter"
    >
      <button
        type="button"
        className={`group-filter__chip${allSelected ? " is-active" : ""}`}
        aria-pressed={allSelected}
        onClick={() => onChange(new Set(groupIds))}
      >
        All groups
      </button>
      {groupIds.map((gid) => {
        const active = selected.has(gid);
        return (
          <button
            key={gid}
            type="button"
            className={`group-filter__chip group-filter__chip--${gid}${active ? " is-active" : ""}`}
            aria-pressed={active}
            data-testid={`group-filter-${gid}`}
            onClick={() => {
              const next = new Set(selected);
              if (active && selected.size > 1) {
                next.delete(gid);
              } else if (!active) {
                next.add(gid);
              } else {
                // Keep at least one group visible.
                return;
              }
              onChange(next);
            }}
          >
            {labelForGroup(gid)}
          </button>
        );
      })}
    </div>
  );
}
