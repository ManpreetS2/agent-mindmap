import { useCallback, useEffect, useMemo, useState } from "react";
import type { Activity, Node } from "@shared/types";
import { AgentGraph } from "../components/AgentGraph";
import { DetailPanel } from "../components/DetailPanel";
import { EdgeLegend } from "../components/EdgeLegend";
import { HandoffBanner } from "../components/HandoffBanner";
import { formatSourceTime } from "../utils/format";
import { handoffEdgeCount } from "../utils/nodeFacts";

export interface MindmapViewProps {
  activity: Activity;
}

export function MindmapView({ activity }: MindmapViewProps) {
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  const selectedNode: Node | null = useMemo(
    () => activity.nodes.find((n) => n.id === selectedNodeId) ?? null,
    [activity.nodes, selectedNodeId],
  );

  const handoffs = useMemo(() => handoffEdgeCount(activity), [activity]);

  const onSelectNode = useCallback((id: string | null) => {
    setSelectedNodeId(id);
  }, []);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setSelectedNodeId(null);
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
          <span>
            Updated {formatSourceTime(activity.generated_at)}
          </span>
          <span className="app-header__sources">
            Source: ledger + GitHub ({activity.meta.github})
          </span>
        </div>
      </header>

      <HandoffBanner handoffCount={handoffs} threshold={3} />

      <div className="mindmap-main">
        <section className="graph-region" aria-label="Agent graph">
          <AgentGraph
            activity={activity}
            selectedNodeId={selectedNodeId}
            onSelectNode={onSelectNode}
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
    </div>
  );
}
