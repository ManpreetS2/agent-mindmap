import type { Edge, Node } from "@shared/types";
import { Fragment, useState } from "react";
import { formatRelativeAgo } from "../utils/format";
import { groupRoster, rosterGroupOf, updatedLabel, type RosterGroupKey } from "../utils/rosterOrder";
import { providerKey, providerLabel } from "../utils/provider";
import { StatusPill } from "./StatusPill";

interface Props {
  nodes: Node[];
  edges?: Edge[];
  selectedId: string | null;
  hoveredId: string | null;
  onSelect: (id: string) => void;
  onHover: (id: string | null) => void;
  /** Clock override for relative times (tests). */
  now?: Date;
}

/** Keyboard / screen-reader entry point to the canvas network (canvas itself is not focusable). */
export function AgentRoster({ nodes, edges = [], selectedId, hoveredId, onSelect, onHover, now }: Props) {
  const [query, setQuery] = useState("");
  const [only, setOnly] = useState<RosterGroupKey | "all">("all");
  // Saved choice wins; otherwise tablets and phones start as a compact rail so the graph keeps the space.
  const [collapsed, setCollapsed] = useState(() => {
    try {
      const saved = window.localStorage?.getItem("mindmapRosterCollapsed");
      if (saved === "1" || saved === "0") return saved === "1";
      return Boolean(window.matchMedia?.("(max-width: 1099px)").matches);
    } catch { return false; }
  });
  const toggleCollapsed = () => {
    setCollapsed((c) => {
      try { window.localStorage?.setItem("mindmapRosterCollapsed", c ? "0" : "1"); } catch { /* storage unavailable */ }
      return !c;
    });
  };
  const counts = { attention: 0, working: 0, settled: 0 } as Record<RosterGroupKey, number>;
  for (const n of nodes) counts[rosterGroupOf(n.status)]++;
  const groups = groupRoster(nodes, query).filter((g) => only === "all" || g.key === only);
  const shown = groups.reduce((n, g) => n + g.nodes.length, 0);
  const byId = new Map(nodes.map((n) => [n.id, n]));
  // Delegation lineage as text, so keyboard / screen-reader users get the network's structure too.
  const relation = (id: string): string | null => {
    const by = edges.filter((e) => e.target === id && byId.has(e.source)).map((e) => byId.get(e.source)!.label);
    const to = edges.filter((e) => e.source === id && byId.has(e.target)).length;
    const parts = [by.length ? `delegated by ${by.join(", ")}` : "", to ? `delegated ${to} agent${to > 1 ? "s" : ""}` : ""].filter(Boolean);
    return parts.length ? parts.join(" · ") : null;
  };
  const move = (e: React.KeyboardEvent<HTMLElement>) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const items = [...e.currentTarget.querySelectorAll<HTMLButtonElement>("button.roster-item")];
    const i = items.indexOf(document.activeElement as HTMLButtonElement);
    if (i < 0 && e.key === "ArrowUp") return; // from the filter box only Down enters the list
    const next = items[Math.max(0, Math.min(items.length - 1, i + (e.key === "ArrowDown" ? 1 : -1)))];
    if (next) {
      e.preventDefault();
      e.stopPropagation();
      next.focus();
    }
  };
  const ago = (iso: string) => formatRelativeAgo(iso, now);
  const total = nodes.length;
  return (
    <nav className={`agent-roster${collapsed ? " is-collapsed" : ""}${nodes.length > 8 ? " is-dense" : ""}`} aria-label="Agents" onKeyDown={move}>
      <div className="agent-roster__head">
        <h2 className="agent-roster__title">
          Agents <span>{shown === total ? total : `${shown} of ${total}`}</span>
        </h2>
        <button
          type="button"
          className="roster-collapse"
          aria-expanded={!collapsed}
          aria-label={collapsed ? "Expand agents panel" : "Collapse agents panel"}
          title={collapsed ? "Expand agents panel" : "Collapse agents panel"}
          onClick={toggleCollapsed}
        >
          <span aria-hidden="true">{collapsed ? "»" : "«"}</span>
        </button>
      </div>
      <div className="roster-tools">
        <input
          type="search"
          className="roster-filter"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Filter agents"
          aria-label="Filter agents by provider, model, task or status"
          data-testid="roster-filter"
        />
        <div className="roster-chips" role="group" aria-label="Show agents by state">
          {([["all", "All", total], ["attention", "Attention", counts.attention], ["working", "Working", counts.working], ["settled", "Settled", counts.settled]] as const).map(([k, label, n]) => (
            <button
              key={k}
              type="button"
              className={`roster-chip${only === k ? " is-on" : ""}`}
              aria-pressed={only === k}
              disabled={k !== "all" && n === 0}
              onClick={() => setOnly(k)}
            >
              {label}<span>{n}</span>
            </button>
          ))}
        </div>
      </div>
      <p className="sr-only" role="status">
        {shown === 0 ? "No agents match" : `${shown} of ${total} agents shown`}
      </p>
      {shown === 0 ? (
        <p className="roster-empty">No agents match</p>
      ) : (
        <ul>
          {groups.map((g) => (
            <Fragment key={g.key}>
              <li className="roster-group" data-group={g.key}>
                <h3>{g.label} <span>{g.nodes.length}</span></h3>
              </li>
              {g.nodes.map((n) => {
                const s = n.session!;
                const key = providerKey(s.provider);
                const model = s.model ?? "Model not reported";
                const task = n.current_task ?? "No task reported";
                const rel = relation(n.id);
                return (
                  <li key={n.id}>
                    <button
                      type="button"
                      data-testid={`agent-node-${n.id}`}
                      data-status={n.status}
                      className={`roster-item roster-item--${key}${selectedId === n.id ? " is-selected" : ""}${hoveredId === n.id ? " is-hovered" : ""}`}
                      aria-pressed={selectedId === n.id}
                      aria-label={`${providerLabel(s.provider)}, ${model}, ${n.status}, ${task}`}
                      aria-description={rel ?? undefined}
                      title={`${providerLabel(s.provider)} · ${model}\n${task}\n${n.status.replace("_", " ").toLowerCase()}`}
                      onClick={() => onSelect(n.id)}
                      onMouseEnter={() => onHover(n.id)}
                      onMouseLeave={() => onHover(null)}
                      onFocus={() => onHover(n.id)}
                      onBlur={() => onHover(null)}
                    >
                      <span className={`roster-shape roster-shape--${key}`} aria-hidden="true" />
                      <span className="roster-main">
                        <span className="roster-line">
                          <span className="roster-task">{task}</span>
                        </span>
                        <span className="roster-sub">
                          <StatusPill status={n.status} />
                          <strong>{providerLabel(s.provider)}</strong>
                        </span>
                        <span className="roster-meta">
                          <span className="roster-model mono">{model}</span>
                          <span className="roster-updated">{updatedLabel(n.last_activity_ts, ago)}</span>
                        </span>
                        {rel && <span className="roster-rel">{rel}</span>}
                      </span>
                    </button>
                  </li>
                );
              })}
            </Fragment>
          ))}
        </ul>
      )}
    </nav>
  );
}
