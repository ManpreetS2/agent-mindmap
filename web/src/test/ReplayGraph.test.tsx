import { act, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Edge, Node, NodeChange } from "@xyflow/react";
import type { Activity } from "@shared/types";
import fixture from "../../../fixtures/sample-activity.json";
import { AgentGraph } from "../components/AgentGraph";

type GraphProps = { nodes: Node[]; edges: Edge[]; onNodesChange: (changes: NodeChange[]) => void };
const captured = vi.hoisted(() => ({ current: null as GraphProps | null }));
vi.mock("@xyflow/react", async (original) => ({
  ...await original<typeof import("@xyflow/react")>(),
  ReactFlow: (props: GraphProps) => { captured.current = props; return <div />; },
}));

function activity(delegated: boolean): Activity {
  const base = fixture as Activity;
  return { ...base, nodes: base.nodes.slice(0, 2).map(n => ({ ...n, status: delegated ? "IN_PROGRESS" : "IDLE" })),
    edges: delegated ? [{ id: "demo-delegation", source: base.nodes[0].id, target: base.nodes[1].id, type: "delegation", count: 1, event_ids: ["synthetic"] }] : [],
    meta: { ...base.meta, t3: { source: "synthetic", mode: "demo", connection: "connected", server_version: null, stale_after_sec: 300,
      replay: { stage: delegated ? 3 : 0, stage_count: 10, cycle: 0, step_sec: 5, label: "Simulated" } } },
  };
}

describe("replay graph reconciliation", () => {
  it("adds/removes only the scripted edge and preserves dragged positions and selection", () => {
    const first = activity(false);
    const props = { selectedNodeId: first.nodes[0].id, onOpenNodeDetail: vi.fn(), onClearNodeDetail: vi.fn(), lifecycleNodeIds: null, lifecycleEdgeIds: null };
    const view = render(<AgentGraph {...props} activity={first} />);
    const id = first.nodes[0].id;
    expect(captured.current!.edges).toHaveLength(0);
    act(() => captured.current!.onNodesChange([{ type: "position", id, position: { x: 543, y: 321 }, dragging: false }]));
    for (const delegated of [true, false, true]) {
      view.rerender(<AgentGraph {...props} activity={activity(delegated)} />);
      const graph = captured.current!;
      expect(graph.edges).toHaveLength(delegated ? 1 : 0);
      expect(graph.nodes.find(n => n.id === id)!.position).toEqual({ x: 543, y: 321 });
      expect(graph.nodes.find(n => n.id === id)!.data.selected).toBe(true);
      expect(graph.nodes.map(n => n.id)).toEqual(first.nodes.map(n => n.id));
      if (delegated) {
        expect(graph.edges[0].animated).toBe(false);
        expect(graph.edges[0].data?.tooltip).toContain("Simulated delegation");
      }
    }
  });
});
