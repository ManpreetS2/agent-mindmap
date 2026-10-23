import type { Edge, Node } from "@shared/types";
import { providerKey, providerLabel } from "../utils/provider";
import { StatusPill } from "./StatusPill";

interface Props {
  nodes: Node[];
  edges?: Edge[];
  selectedId: string | null;
  hoveredId: string | null;
  onSelect: (id: string) => void;
  onHover: (id: string | null) => void;
}

/** Keyboard / screen-reader entry point to the canvas network (canvas itself is not focusable). */
export function AgentRoster({ nodes, edges = [], selectedId, hoveredId, onSelect, onHover }: Props) {
  const sorted = [...nodes].sort((a, b) => a.id.localeCompare(b.id));
  const byId = new Map(nodes.map((n) => [n.id, n]));
  // Delegation lineage as text, so keyboard / screen-reader users get the network's structure too.
  const relation = (id: string): string | null => {
    const by = edges.filter((e) => e.target === id && byId.has(e.source)).map((e) => byId.get(e.source)!.label);
    const to = edges.filter((e) => e.source === id && byId.has(e.target)).length;
    const parts = [by.length ? `delegated by ${by.join(", ")}` : "", to ? `delegated ${to} agent${to > 1 ? "s" : ""}` : ""].filter(Boolean);
    return parts.length ? parts.join(" · ") : null;
  };
  const move = (e: React.KeyboardEvent<HTMLUListElement>) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const items = [...e.currentTarget.querySelectorAll<HTMLButtonElement>("button")];
    const i = items.indexOf(document.activeElement as HTMLButtonElement);
    const next = items[Math.max(0, Math.min(items.length - 1, i + (e.key === "ArrowDown" ? 1 : -1)))];
    if (next) {
      e.preventDefault();
      e.stopPropagation();
      next.focus();
    }
  };
  return (
    <nav className="agent-roster" aria-label="Agents">
      <h2 className="agent-roster__title">Agents <span>{sorted.length}</span></h2>
      <ul onKeyDown={move}>
        {sorted.map((n) => {
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
                  {rel && <span className="roster-rel">{rel}</span>}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
