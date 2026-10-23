import { act, render, screen, fireEvent } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useEffect } from "react";
import type { Edge, Node, NodeChange } from "@xyflow/react";
import { AgentGraph } from "../components/AgentGraph";
import { MindmapView } from "../views/MindmapView";
import { overlappingNetworkNodes } from "../utils/networkLayout";
import { renderMindmap } from "./renderMindmap";
import { sessionNode, t3Activity } from "./helpers";

type Props = {
  nodes: Node[]; edges: Edge[]; fitView?: boolean;
  onNodesChange: (c: NodeChange[]) => void; onNodeMouseEnter: (e: unknown, n: Node) => void; onNodeMouseLeave: () => void;
  children?: React.ReactNode;
};
const cap = vi.hoisted(() => ({ props: null as Props | null, mounts: 0, reduce: false }));

vi.mock("motion/react", async (orig) => ({ ...(await orig<typeof import("motion/react")>()), useReducedMotion: () => cap.reduce }));
vi.mock("@xyflow/react", async (orig) => ({
  ...(await orig<typeof import("@xyflow/react")>()),
  ReactFlow: (props: Props) => {
    cap.props = props;
    useEffect(() => { cap.mounts++; }, []);
    return <div data-testid="rf">{props.children}</div>;
  },
  Panel: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  ViewportPortal: () => null,
  Background: () => null,
  Controls: () => null,
  MiniMap: () => null,
}));

const base = { selectedNodeId: null as string | null, onOpenNodeDetail: vi.fn(), onClearNodeDetail: vi.fn(), lifecycleNodeIds: null, lifecycleEdgeIds: null };
const names = ["a", "b", "c", "d", "e"].map((id) => sessionNode(id));
const rects = () => new Map(cap.props!.nodes.map((n) => [n.id, n.position]));

beforeEach(() => { cap.props = null; cap.mounts = 0; cap.reduce = false; });

describe("network graph (physics)", () => {
  it("positions are non-overlapping and identical across mounts", () => {
    const act = t3Activity(names, [["a", "b"], ["a", "c"]]);
    render(<AgentGraph {...base} activity={act} />);
    const first = [...rects()];
    expect(overlappingNetworkNodes(rects(), 8)).toEqual([]);
    cleanupRender();
    render(<AgentGraph {...base} activity={act} />);
    expect([...rects()]).toEqual(first);
  });

  it("keeps positions, mount and fit-view untouched across polls and status changes", () => {
    const view = render(<AgentGraph {...base} activity={t3Activity(names, [["a", "b"]])} />);
    const before = [...rects()];
    const fit = cap.props!.fitView;
    for (const status of ["DONE", "FAILED", "BLOCKED", "IN_PROGRESS"] as const) {
      view.rerender(<AgentGraph {...base} activity={t3Activity(names.map((n) => ({ ...n, status })), [["a", "b"]])} />);
      expect([...rects()]).toEqual(before);
    }
    expect(cap.mounts).toBe(1); // never remounted => viewport state is preserved
    expect(cap.props!.fitView).toBe(fit);
  });

  it("topology changes move the layout but keep dragged nodes pinned exactly and selection intact", () => {
    const props = { ...base, selectedNodeId: "a" };
    const view = render(<AgentGraph {...props} activity={t3Activity(names.slice(0, 3), [["a", "b"]])} />);
    act(() => cap.props!.onNodesChange([{ type: "position", id: "c", position: { x: 700, y: 310 }, dragging: false }]));
    const lone = rects().get("e");
    view.rerender(<AgentGraph {...props} activity={t3Activity(names, [["a", "b"], ["b", "d"], ["d", "e"]])} />);
    expect(rects().get("c")).toEqual({ x: 700, y: 310 });
    expect(rects().size).toBe(5);
    expect(lone).toBeUndefined();
    expect(overlappingNetworkNodes(rects(), 8)).toEqual([]);
    expect(cap.props!.nodes.find((n) => n.id === "a")!.data.selected).toBe(true);
    // release pins -> node returns to the physics layout
    fireEvent.click(screen.getByText(/Release 1 pinned/));
    expect(rects().get("c")).not.toEqual({ x: 700, y: 310 });
  });

  it("removes departed agents (no ghost nodes) and their pins", () => {
    const view = render(<AgentGraph {...base} activity={t3Activity(names, [])} />);
    act(() => cap.props!.onNodesChange([{ type: "position", id: "e", position: { x: 1, y: 2 }, dragging: false }]));
    view.rerender(<AgentGraph {...base} activity={t3Activity(names.slice(0, 4), [])} />);
    expect(cap.props!.nodes.map((n) => n.id)).toEqual(["a", "b", "c", "d"]);
    expect(screen.queryByText(/pinned/)).toBeNull();
  });

  it("highlights the neighbourhood on hover and dims the rest", () => {
    render(<AgentGraph {...base} activity={t3Activity(names, [["a", "b"]])} />);
    act(() => cap.props!.onNodeMouseEnter({}, cap.props!.nodes.find((n) => n.id === "a")!));
    const rel = Object.fromEntries(cap.props!.nodes.map((n) => [n.id, n.data.relation]));
    expect(rel).toMatchObject({ a: "focus", b: "neighbor", c: "dim", d: "dim", e: "dim" });
    const edge = cap.props!.edges[0];
    expect((edge.style as { opacity: number }).opacity).toBe(1);
    expect(edge.data?.showLabel).toBe(true);
    act(() => cap.props!.onNodeMouseLeave());
    expect(cap.props!.nodes.every((n) => n.data.relation === null)).toBe(true);
    expect(cap.props!.edges[0].data?.showLabel).toBe(false);
  });

  it("directional arrow, evidence-based styling, and no permanent animation", () => {
    render(<AgentGraph {...base} activity={t3Activity(names, [["a", "b"]])} />);
    const e = cap.props!.edges[0];
    expect(e.source).toBe("a");
    expect(e.target).toBe("b");
    expect(e.markerEnd).toMatchObject({ type: "arrowclosed" });
    expect(e.animated).toBe(false);
    expect(e.data?.fresh).toBe(false); // historical relationship at baseline
    expect(e.data?.showParticles).toBe(false);
    expect(e.ariaLabel).toContain("Task a to Task b");
  });

  it("a newly observed verified delegation pulses once; reduced motion keeps only the static tag", () => {
    const view = render(<AgentGraph {...base} activity={t3Activity(names, [])} />);
    view.rerender(<AgentGraph {...base} activity={t3Activity(names, [["a", "b"]])} />);
    expect(cap.props!.edges[0].data?.fresh).toBe(true);
    expect(cap.props!.edges[0].data?.reduceMotion).toBe(false);
    cap.reduce = true;
    view.rerender(<AgentGraph {...base} activity={t3Activity(names, [["a", "b"]])} />);
    expect(cap.props!.edges[0].data?.reduceMotion).toBe(true); // HandoffEdge renders no moving dot
    expect(cap.props!.edges[0].data?.fresh).toBe(true); // but still shows the "New" tag
  });

  it("reduced motion disables the pause control (motion is already off)", () => {
    cap.reduce = true;
    render(<AgentGraph {...base} activity={t3Activity(names, [])} />);
    const btn = screen.getByRole("button", { name: /Resume motion/ });
    expect(btn).toBeDisabled();
  });

  it("pause toggles without moving nodes", () => {
    render(<AgentGraph {...base} activity={t3Activity(names, [["a", "b"]])} />);
    const before = [...rects()];
    fireEvent.click(screen.getByRole("button", { name: "Pause motion" }));
    expect(screen.getByRole("button", { name: "Resume motion" })).toHaveAttribute("aria-pressed", "true");
    expect([...rects()]).toEqual(before);
  });
});

function cleanupRender() { document.body.innerHTML = ""; }

describe("real vs replay separation", () => {
  it("real mode shows no synthetic labels or replay banner", () => {
    renderMindmap(<MindmapView activity={t3Activity([sessionNode("a"), sessionNode("b")], [["a", "b"]], "live")} initialListView />);
    expect(screen.queryByText(/SIMULATED|DEMO/i)).toBeNull();
    expect(screen.getByText(/Source: T3 MCP · connected/)).toBeInTheDocument();
  });

  it("replay is unmistakably labelled and edges are called simulated", () => {
    const replay = { stage: 4, stage_count: 10, cycle: 0, step_sec: 5, label: "Delegation begins" };
    renderMindmap(<MindmapView activity={t3Activity([sessionNode("a"), sessionNode("b")], [["a", "b"]], "demo", replay)} initialListView />);
    expect(screen.getByText(/DEMO REPLAY — SIMULATED ACTIVITY/)).toBeInTheDocument();
    expect(screen.getByText(/Source: Synthetic replay/)).toBeInTheDocument();
  });
});
