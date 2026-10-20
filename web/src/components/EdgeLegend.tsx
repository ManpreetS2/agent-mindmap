import { EDGE_VISUALS } from "../utils/edgeStyles";
import type { EdgeType } from "@shared/types";

const ORDER: EdgeType[] = ["handoff", "verdict", "pr", "merge"];

export function EdgeLegend() {
  return (
    <div className="edge-legend" role="list" aria-label="Edge types legend">
      {ORDER.map((type) => {
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
            <span>{v.label}</span>
          </div>
        );
      })}
    </div>
  );
}
