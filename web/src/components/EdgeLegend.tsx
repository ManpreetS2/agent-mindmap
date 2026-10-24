import { EDGE_VISUALS } from "../utils/edgeStyles";
import type { EdgeType } from "@shared/types";

const ORDER: EdgeType[] = ["handoff", "verdict", "pr", "merge"];

export function EdgeLegend({ t3 = false, simulated = false }: { t3?: boolean; simulated?: boolean }) {
  return (
    <div className="edge-legend" role="list" aria-label="Edge types legend">
      {(t3 ? ["delegation" as EdgeType] : ORDER).map((type) => {
        const v = EDGE_VISUALS[type];
        return (
          <div key={type} className="edge-legend__item" role="listitem">
            <svg width="32" height="12" aria-hidden="true">
              <line
                x1="0"
                y1="6"
                x2="32"
                y2="6"
                style={{ stroke: v.stroke }}
                strokeWidth={2}
                strokeDasharray={v.strokeDasharray}
              />
            </svg>
            <span>{simulated && type === "delegation" ? "Simulated delegation" : v.label}</span>
          </div>
        );
      })}
    </div>
  );
}

