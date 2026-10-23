import { StrictMode } from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AgentNetwork } from "../components/AgentNetwork";
import { MindmapView } from "../views/MindmapView";
import type { GLink, GNode } from "../utils/networkModel";
import { fgMock } from "./forceGraphMock";
import { renderMindmap } from "./renderMindmap";
import { sessionNode, t3Activity } from "./helpers";

const nodes = ["a", "b", "c", "d"].map((i) => sessionNode(i));
const base = { selectedNodeId: null as string | null, onOpenNodeDetail: vi.fn(), onClearNodeDetail: vi.fn() };
const props = () => fgMock.props as Record<string, any>;
const gdata = () => props().graphData as { nodes: GNode[]; links: GLink[] };
const frame = () => act(() => {
  const data = gdata();
  for (const link of data.links) {
    if (typeof link.source === "string") link.source = data.nodes.find(n => n.id === link.source)!;
    if (typeof link.target === "string") link.target = data.nodes.find(n => n.id === link.target)!;
  }
  props().onRenderFramePre();
});
const setReduced = (on: boolean) => {
  window.matchMedia = ((q: string) => ({ matches: on && q.includes("reduce"), media: q, addEventListener() {}, removeEventListener() {} })) as never;
};

beforeEach(() => { fgMock.reset(); vi.useFakeTimers(); setReduced(false); });
afterEach(() => { vi.useRealTimers(); setReduced(false); });

describe("AgentNetwork", () => {
  it("passes stable graph data and keeps identity and positions across status polls", () => {
    const view = render(<AgentNetwork {...base} activity={t3Activity(nodes, [["a", "b"]])} />);
    const data = gdata();
    expect(data.nodes.map((n) => n.id)).toEqual(["a", "b", "c", "d"]);
    data.nodes[0].x = 321;
    for (const status of ["FAILED", "DONE", "BLOCKED", "IN_PROGRESS"] as const) {
      view.rerender(<AgentNetwork {...base} activity={t3Activity(nodes.map((n) => ({ ...n, status })), [["a", "b"]])} />);
      expect(gdata()).toBe(data); // engine never sees a new graph => no re-heat, no jump
      expect(gdata().nodes[0].x).toBe(321);
    }
  });

  it("changes graph data only on topology change; removed agents leave no ghosts", () => {
    const view = render(<AgentNetwork {...base} activity={t3Activity(nodes, [["a", "b"]])} />);
    const first = gdata();
    view.rerender(<AgentNetwork {...base} activity={t3Activity(nodes, [["a", "b"], ["b", "c"]])} />);
    expect(gdata()).not.toBe(first);
    expect(gdata().links).toHaveLength(2);
    view.rerender(<AgentNetwork {...base} activity={t3Activity(nodes.slice(0, 2), [])} />);
    expect(gdata().nodes.map((n) => n.id)).toEqual(["a", "b"]);
    expect(screen.queryByTestId("agent-node-d")).toBeNull();
  });

  it("emits a one-shot particle only for a newly observed verified delegation", () => {
    const view = render(<AgentNetwork {...base} activity={t3Activity(nodes, [["a", "b"]])} />);
    act(() => { vi.advanceTimersByTime(2000); });
    expect(fgMock.methods.emitParticle).not.toHaveBeenCalled(); // baseline/historical edge
    view.rerender(<AgentNetwork {...base} activity={t3Activity(nodes, [["a", "b"], ["a", "c"]])} />);
    frame();
    expect(fgMock.methods.emitParticle).toHaveBeenCalledTimes(1);
    expect((fgMock.methods.emitParticle.mock.calls[0] as unknown[])[0]).toMatchObject({ id: "delegation-c" });
    expect(props().linkDirectionalParticles()).toBe(0); // never continuous
    act(() => { vi.advanceTimersByTime(500); });
    expect(fgMock.methods.emitParticle).toHaveBeenCalledTimes(1); // exactly one particle, no delayed follow-up
    // repeated polls do not re-trigger it
    view.rerender(<AgentNetwork {...base} activity={t3Activity(nodes, [["a", "b"], ["a", "c"]])} />);
    act(() => { vi.advanceTimersByTime(7000); });
    expect(fgMock.methods.emitParticle).toHaveBeenCalledTimes(1);
  });

  it("never emits particles for an unevidenced edge or after a mode switch", () => {
    const view = render(<AgentNetwork {...base} activity={t3Activity(nodes, [])} />);
    const noEvidence = t3Activity(nodes, [["a", "b"]]);
    noEvidence.events = noEvidence.events.filter((e) => e.id !== "delegation-b");
    view.rerender(<AgentNetwork {...base} activity={noEvidence} />);
    expect(fgMock.methods.emitParticle).not.toHaveBeenCalled();
    view.rerender(<AgentNetwork {...base} activity={t3Activity(nodes, [["a", "b"], ["a", "c"]], "demo")} />);
    expect(fgMock.methods.emitParticle).not.toHaveBeenCalled();
  });

  it("reduced motion: no particles, no animation, positions pre-computed, pause disabled", () => {
    setReduced(true);
    const view = render(<AgentNetwork {...base} activity={t3Activity(nodes, [])} />);
    view.rerender(<AgentNetwork {...base} activity={t3Activity(nodes, [["a", "b"]])} />);
    expect(fgMock.methods.emitParticle).not.toHaveBeenCalled();
    expect(props().cooldownTicks).toBe(0);
    expect(props().warmupTicks).toBeGreaterThan(100);
    expect(props().autoPauseRedraw).toBe(true);
    expect(screen.getByRole("button", { name: /Resume motion/ })).toBeDisabled();
  });

  it("pause stops continuous redraw but keeps the network interactive", () => {
    render(<AgentNetwork {...base} activity={t3Activity(nodes, [])} />);
    expect(props().autoPauseRedraw).toBe(false); // active agents animate
    fireEvent.click(screen.getByRole("button", { name: "Pause motion" }));
    expect(screen.getByRole("button", { name: "Resume motion" })).toHaveAttribute("aria-pressed", "true");
    expect(props().autoPauseRedraw).toBe(true);
    expect(props().cooldownTicks).toBe(0); // pause also freezes physics
  });

  it("idle networks do not run a render loop", () => {
    render(<AgentNetwork {...base} activity={t3Activity(nodes.map((n) => ({ ...n, status: "DONE" as const })), [])} />);
    expect(props().autoPauseRedraw).toBe(true);
  });

  it("dragging pins a node; release frees it", () => {
    render(<AgentNetwork {...base} activity={t3Activity(nodes, [])} />);
    const n = gdata().nodes[1];
    n.x = 40; n.y = 50;
    act(() => props().onNodeDragEnd(n));
    expect([n.fx, n.fy, n.pinned]).toEqual([40, 50, true]);
    fireEvent.click(screen.getByRole("button", { name: "Release 1 pinned" }));
    expect([n.fx, n.fy, n.pinned]).toEqual([undefined, undefined, false]);
    expect(fgMock.methods.d3ReheatSimulation).toHaveBeenCalled();
    expect(screen.queryByText(/pinned/)).toBeNull();
  });

  it("selection and background clicks go through the shared inspector callbacks", () => {
    const open = vi.fn(), clear = vi.fn();
    render(<AgentNetwork {...base} onOpenNodeDetail={open} onClearNodeDetail={clear} activity={t3Activity(nodes, [])} />);
    props().onNodeClick(gdata().nodes[2]);
    props().onBackgroundClick();
    expect(open).toHaveBeenCalledWith("c");
    expect(clear).toHaveBeenCalled();
  });

  it("hover focuses the neighbourhood: incident links stay bright, others fade", () => {
    render(<AgentNetwork {...base} activity={t3Activity(nodes, [["a", "b"], ["c", "d"]])} />);
    const [ab, cd] = gdata().links;
    const idle = props().linkColor(ab);
    act(() => props().onNodeHover(gdata().nodes[0]));
    expect(props().linkColor(ab)).not.toBe(idle);
    expect(props().linkColor(ab)).toMatch(/0\.98/);
    expect(props().linkColor(cd)).toMatch(/0\.12/);
    act(() => props().onNodeHover(null));
    expect(props().linkColor(cd)).toBe(idle);
  });

  it("fits the camera once after the first layout and never again on polls or pans", () => {
    const view = render(<AgentNetwork {...base} activity={t3Activity(nodes, [["a", "b"]])} />);
    act(() => { vi.advanceTimersByTime(1500); });
    expect(fgMock.methods.zoom.mock.calls.filter(c => c.length)).toHaveLength(1);
    for (const status of ["FAILED", "DONE"] as const) {
      view.rerender(<AgentNetwork {...base} activity={t3Activity(nodes.map((n) => ({ ...n, status })), [["a", "b"]])} />);
      act(() => { vi.advanceTimersByTime(2000); });
    }
    expect(fgMock.methods.zoom.mock.calls.filter(c => c.length)).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Fit view" }));
    expect(fgMock.methods.zoom.mock.calls.filter(c => c.length)).toHaveLength(2);
  });

  it("does not auto-fit once the user has panned or zoomed", () => {
    const { container } = render(<AgentNetwork {...base} activity={t3Activity(nodes, [])} />);
    fireEvent.wheel(container.querySelector(".network-canvas")!);
    act(() => { vi.advanceTimersByTime(3000); });
    expect(fgMock.methods.zoom).not.toHaveBeenCalled();
  });

  it("arrows point parent → child and edges are directional but not animated", () => {
    render(<AgentNetwork {...base} activity={t3Activity(nodes, [["a", "b"]])} />);
    expect(props().linkDirectionalArrowLength).toBeGreaterThan(0);
    const link = gdata().links[0];
    expect([link.source, link.target]).toEqual(["a", "b"]);
    expect(props().linkDirectionalParticles()).toBe(0);
  });

  it("repaints status/selection changes without replacing graphData or reheating", () => {
    const input = t3Activity(nodes, []);
    const view = render(<AgentNetwork {...base} activity={input} />);
    const data = gdata(), draw = props().nodeCanvasObject;
    view.rerender(<AgentNetwork {...base} activity={structuredClone(input)} />);
    expect(props().nodeCanvasObject).toBe(draw);
    view.rerender(<AgentNetwork {...base} activity={t3Activity(nodes.map(n => ({ ...n, status: "DONE" })), [])} />);
    expect(props().nodeCanvasObject).not.toBe(draw);
    expect(gdata()).toBe(data);
    const statusDraw = props().nodeCanvasObject;
    view.rerender(<AgentNetwork {...base} selectedNodeId="a" activity={input} />);
    expect(props().nodeCanvasObject).not.toBe(statusDraw);
    expect(fgMock.methods.d3ReheatSimulation).not.toHaveBeenCalled();
  });

  it("restores both camera coordinates and default zoom after pan-only topology changes", () => {
    const view = render(<AgentNetwork {...base} activity={t3Activity(nodes, [])} />);
    fireEvent.pointerDown(view.container.querySelector(".network-canvas")!);
    fgMock.methods.centerAt.mockReturnValue({ x: 103, y: -71 });
    fgMock.methods.zoom.mockReturnValue(1);
    props().onZoom();
    view.rerender(<AgentNetwork {...base} activity={t3Activity([...nodes, sessionNode("z")], [])} />);
    // Simulate the library's topology-triggered auto zoom before the next canvas frame.
    fgMock.methods.zoom.mockReturnValue(2.9);
    props().onZoom();
    frame();
    expect(fgMock.methods.zoom).toHaveBeenCalledWith(1, 0);
    expect(fgMock.methods.centerAt).toHaveBeenCalledWith(103, -71, 0);
  });

  it("dedupes disappearing/reappearing edges and renamed edges carrying old evidence", () => {
    const view = render(<AgentNetwork {...base} activity={t3Activity(nodes, [])} />);
    const added = t3Activity(nodes, [["a", "b"]]);
    view.rerender(<AgentNetwork {...base} activity={added} />);
    expect(fgMock.methods.emitParticle).not.toHaveBeenCalled(); // not initialized yet
    frame();
    view.rerender(<AgentNetwork {...base} activity={t3Activity(nodes, [])} />);
    frame();
    view.rerender(<AgentNetwork {...base} activity={added} />);
    frame();
    const renamed = structuredClone(added); renamed.edges[0].id = "alias";
    view.rerender(<AgentNetwork {...base} activity={renamed} />);
    frame();
    expect(fgMock.methods.emitParticle).toHaveBeenCalledTimes(1);
  });

  it("drops a queued particle if its link disappears before initialization", () => {
    const view = render(<AgentNetwork {...base} activity={t3Activity(nodes, [])} />);
    view.rerender(<AgentNetwork {...base} activity={t3Activity(nodes, [["a", "b"]])} />);
    view.rerender(<AgentNetwork {...base} activity={t3Activity(nodes, [])} />);
    frame(); act(() => vi.advanceTimersByTime(8000));
    expect(fgMock.methods.emitParticle).not.toHaveBeenCalled();
  });

  it("does not replay events observed while paused on resume", () => {
    const view = render(<AgentNetwork {...base} activity={t3Activity(nodes, [])} />);
    fireEvent.click(screen.getByRole("button", { name: "Pause motion" }));
    const clearParticles = props().linkDirectionalParticles;
    view.rerender(<AgentNetwork {...base} activity={t3Activity(nodes, [["a", "b"]])} />);
    frame();
    fireEvent.click(screen.getByRole("button", { name: "Resume motion" }));
    frame();
    expect(props().linkDirectionalParticles).not.toBe(clearParticles);
    expect(props().linkDirectionalParticles()).toBe(0);
    expect(fgMock.methods.emitParticle).not.toHaveBeenCalled();
  });

  it("StrictMode registers stable named forces, no duplicate particles or timers", () => {
    const view = render(<StrictMode><AgentNetwork {...base} activity={t3Activity(nodes, [])} /></StrictMode>);
    const registrations = (fgMock.methods.d3Force.mock.calls as unknown as unknown[][]).filter(c => c.length > 1);
    for (const name of ["x", "y", "collide"]) {
      const calls = registrations.filter(c => c[0] === name);
      expect(calls).toHaveLength(2);
      expect(calls[0][1]).toBe(calls[1][1]);
    }
    view.rerender(<StrictMode><AgentNetwork {...base} activity={t3Activity(nodes, [["a", "b"]])} /></StrictMode>);
    frame(); frame();
    expect(fgMock.methods.emitParticle).toHaveBeenCalledTimes(1);
    view.unmount();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("empty network states that nothing was observed", () => {
    render(<AgentNetwork {...base} activity={t3Activity([], [])} />);
    expect(screen.getByText(/No agent sessions observed yet/)).toBeInTheDocument();
  });
});

describe("roster (accessible access to the canvas)", () => {
  it("lists every agent with provider, model, status and task; supports arrow-key navigation", () => {
    const act1 = t3Activity([sessionNode("a", { status: "FAILED" }, { provider: "Claude Code", model: "claude-x" }), sessionNode("b", {}, { provider: null, model: null })], []);
    render(<AgentNetwork {...base} activity={act1} />);
    const a = screen.getByTestId("agent-node-a");
    expect(a).toHaveAttribute("aria-label", "Claude, claude-x, FAILED, Task a");
    expect(screen.getByTestId("agent-node-b")).toHaveAttribute("aria-label", "Unknown provider, Model not reported, IN_PROGRESS, Task b");
    a.focus();
    fireEvent.keyDown(a, { key: "ArrowDown" });
    expect(document.activeElement).toBe(screen.getByTestId("agent-node-b"));
  });

  it("marks the selected agent and reports selection", () => {
    const open = vi.fn();
    render(<AgentNetwork {...base} selectedNodeId="b" onOpenNodeDetail={open} activity={t3Activity(nodes, [])} />);
    expect(screen.getByTestId("agent-node-b")).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByTestId("agent-node-c"));
    expect(open).toHaveBeenCalledWith("c");
  });
});

describe("real vs replay separation", () => {
  it("real mode shows no synthetic labels", () => {
    renderMindmap(<MindmapView activity={t3Activity(nodes, [["a", "b"]], "live")} initialListView={false} />);
    expect(screen.queryByText(/SIMULATED|DEMO/i)).toBeNull();
    expect(screen.getByText(/Verified delegation/)).toBeInTheDocument();
    expect(screen.getByText(/never as proof of ongoing messages/)).toBeInTheDocument();
  });
  it("replay is labelled simulated everywhere", () => {
    const replay = { stage: 4, stage_count: 10, cycle: 0, step_sec: 5, label: "Delegation" };
    renderMindmap(<MindmapView activity={t3Activity(nodes, [["a", "b"]], "demo", replay)} initialListView={false} />);
    expect(screen.getByText(/DEMO REPLAY — SIMULATED ACTIVITY/)).toBeInTheDocument();
    expect(screen.getByText(/Simulated delegation \(parent → child\)/)).toBeInTheDocument();
  });
});
