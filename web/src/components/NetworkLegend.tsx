import { useState } from "react";
import { PROVIDER_COLOR, STATUS_COLOR } from "../utils/nodeDraw";

const STATUSES = [
  ["IN_PROGRESS", "Working"],
  ["BLOCKED", "Blocked"],
  ["FAILED", "Failed"],
  ["DONE", "Done"],
  ["STALE", "Stale / unknown"],
] as const;

const NARROW = "(max-width: 767px)";

export function NetworkLegend({ simulated = false }: { simulated?: boolean }) {
  // Compact by default on narrow screens, expanded elsewhere; the user's toggle always wins.
  const [open, setOpen] = useState(() => !(typeof window !== "undefined" && window.matchMedia?.(NARROW).matches));
  return (
    <div className={`network-legend${open ? "" : " is-collapsed"}`} role="group" aria-label="Legend">
      <button
        type="button"
        className="network-legend__toggle"
        aria-expanded={open}
        aria-controls="network-legend-body"
        onClick={() => setOpen((o) => !o)}
      >
        Legend <span aria-hidden="true">{open ? "▾" : "▸"}</span>
      </button>
      <div id="network-legend-body" className="network-legend__body" hidden={!open}>
      <div className="network-legend__row">
        <span className="legend-shape legend-shape--claude" style={{ borderColor: PROVIDER_COLOR.claude }} aria-hidden="true" /> Claude
        <span className="legend-shape legend-shape--codex" style={{ background: PROVIDER_COLOR.codex }} aria-hidden="true" /> Codex
        <span className="legend-arrow" aria-hidden="true">→</span>
        {simulated ? "Simulated delegation (parent → child)" : "Verified delegation (parent → child)"}
      </div>
      <div className="network-legend__row">
        {STATUSES.map(([k, label]) => (
          <span key={k} className="legend-status">
            <span className="legend-dot" style={{ background: STATUS_COLOR[k] }} aria-hidden="true" />
            {label}
          </span>
        ))}
      </div>
      <div className="network-legend__note">
        Arrows show lineage only. A pulse appears once when a new delegation is observed — never as proof of ongoing messages.
      </div>
      </div>
    </div>
  );
}
