import type { Node } from "@shared/types";
import { providerKey, providerLabel } from "../utils/provider";
import { StatusPill } from "./StatusPill";

interface Props {
  nodes: Node[];
  selectedId: string | null;
  hoveredId: string | null;
  onSelect: (id: string) => void;
  onHover: (id: string | null) => void;
}

/** Keyboard / screen-reader entry point to the canvas network (canvas itself is not focusable). */
export function AgentRoster({ nodes, selectedId, hoveredId, onSelect, onHover }: Props) {
  const sorted = [...nodes].sort((a, b) => a.id.localeCompare(b.id));
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
          return (
            <li key={n.id}>
              <button
                type="button"
                data-testid={`agent-node-${n.id}`}
                className={`roster-item roster-item--${key}${selectedId === n.id ? " is-selected" : ""}${hoveredId === n.id ? " is-hovered" : ""}`}
                aria-pressed={selectedId === n.id}
                aria-label={`${providerLabel(s.provider)}, ${model}, ${n.status}, ${task}`}
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
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
