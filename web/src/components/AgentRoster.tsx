import type { Edge, Node } from "@shared/types";
import { Fragment, useState } from "react";
import { formatRelativeAgo } from "../utils/format";
import { groupRoster, updatedLabel } from "../utils/rosterOrder";
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
  const groups = groupRoster(nodes, query);
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
    <nav className="agent-roster" aria-label="Agents" onKeyDown={move}>
      <h2 className="agent-roster__title">
        Agents <span>{shown === total ? total : `${shown} of ${total}`}</span>
      </h2>
      <input
        type="search"
        className="roster-filter"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Filter agents"
        aria-label="Filter agents by provider, model, task or status"
        data-testid="roster-filter"
      />
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
                      className={`roster-item roster-item--${key}${selectedId === n.id ? " is-selected" : ""}${hoveredId === n.id ? " is-hovered" : ""}`}
                      aria-pressed={selectedId === n.id}
                      aria-label={`${providerLabel(s.provider)}, ${model}, ${n.status}, ${task}`}
                      aria-description={rel ?? undefined}
                      onClick={() => onSelect(n.id)}
                      onMouseEnter={() => onHover(n.id)}
                      onMouseLeave={() => onHover(null)}
                      onFocus={() => onHover(n.id)}
                      onBlur={() => onHover(null)}
                    >
                      <span className={`roster-shape roster-shape--${key}`} aria-hidden="true" />
                      <span className="roster-main">
                        <span className="roster-line">
                          <strong>{providerLabel(s.provider)}</strong>
                          <StatusPill status={n.status} />
                        </span>
                        <span className="roster-model mono">{model}</span>
                        <span className="roster-task">{task}</span>
                        <span className="roster-updated">{updatedLabel(n.last_activity_ts, ago)}</span>
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
