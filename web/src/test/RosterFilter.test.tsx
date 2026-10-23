import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AgentRoster } from "../components/AgentRoster";
import { NetworkLegend } from "../components/NetworkLegend";
import { MindmapView } from "../views/MindmapView";
import { groupRoster, matchesRosterQuery, updatedLabel } from "../utils/rosterOrder";
import { renderMindmap } from "./renderMindmap";
import { sessionNode, t3Activity } from "./helpers";

const nodes = [
  sessionNode("a", { status: "DONE" }),
  sessionNode("b", { status: "FAILED", current_task: "Fix build" }, { provider: "Claude Code", model: "claude-x" }),
  sessionNode("c", { status: "IN_PROGRESS" }),
  sessionNode("d", { status: "BLOCKED", last_activity_ts: null as never }),
  sessionNode("e", { status: "IDLE" }),
];
const props = { selectedId: null, hoveredId: null, onSelect: vi.fn(), onHover: vi.fn(), now: new Date("2026-10-22T20:05:00Z") };
const ids = () => screen.getAllByRole("button").map((b) => b.getAttribute("data-testid")).filter(Boolean);

describe("roster ordering and filtering", () => {
  it("groups by attention then working then settled, stable by id inside groups", () => {
    render(<AgentRoster {...props} nodes={nodes} />);
    expect(ids()).toEqual(["agent-node-b", "agent-node-d", "agent-node-c", "agent-node-a", "agent-node-e"]);
    expect(groupRoster(nodes, "").map((g) => g.key)).toEqual(["attention", "working", "settled"]);
  });

  it("filters the list by provider, model, task and status text", () => {
    expect(matchesRosterQuery(nodes[1], "claude")).toBe(true);
    expect(matchesRosterQuery(nodes[1], "fix BUILD")).toBe(true);
    expect(matchesRosterQuery(nodes[1], "failed")).toBe(true);
    expect(matchesRosterQuery(nodes[2], "in progress")).toBe(true);
    expect(matchesRosterQuery(nodes[0], "claude")).toBe(false);
    render(<AgentRoster {...props} nodes={nodes} />);
    fireEvent.change(screen.getByTestId("roster-filter"), { target: { value: "claude" } });
    expect(ids()).toEqual(["agent-node-b"]);
    expect(screen.getByText("1 of 5")).toBeInTheDocument();
  });

  it("shows 'No agents match' and recovers when cleared", () => {
    render(<AgentRoster {...props} nodes={nodes} />);
    const input = screen.getByTestId("roster-filter");
    fireEvent.change(input, { target: { value: "zzz" } });
    expect(screen.getAllByText("No agents match").length).toBeGreaterThan(0);
    fireEvent.change(input, { target: { value: "" } });
    expect(ids()).toHaveLength(5);
  });

  it("states update time honestly, and never invents one", () => {
    render(<AgentRoster {...props} nodes={nodes} />);
    expect(within(screen.getByTestId("agent-node-a")).getByText("updated 5m ago")).toBeInTheDocument();
    expect(within(screen.getByTestId("agent-node-d")).getByText("Update time not reported by T3")).toBeInTheDocument();
    expect(updatedLabel(null, () => "x")).toBe("Update time not reported by T3");
  });

  it("keeps aria-label and arrow-key navigation (Down from the filter enters the list)", () => {
    render(<AgentRoster {...props} nodes={nodes} />);
    expect(screen.getByTestId("agent-node-b")).toHaveAttribute("aria-label", "Claude, claude-x, FAILED, Fix build");
    screen.getByTestId("roster-filter").focus();
    fireEvent.keyDown(screen.getByTestId("roster-filter"), { key: "ArrowDown" });
    expect(screen.getByTestId("agent-node-b")).toHaveFocus();
    fireEvent.keyDown(screen.getByTestId("agent-node-b"), { key: "ArrowDown" });
    expect(screen.getByTestId("agent-node-d")).toHaveFocus();
    fireEvent.keyDown(screen.getByTestId("agent-node-d"), { key: "ArrowUp" });
    expect(screen.getByTestId("agent-node-b")).toHaveFocus();
  });
});

describe("legend toggle", () => {
  it("is collapsible via aria-expanded", () => {
    render(<NetworkLegend />);
    const t = screen.getByRole("button", { name: /legend/i });
    expect(t).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(t);
    expect(t).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(/Arrows show lineage only/)).not.toBeVisible();
    fireEvent.click(t);
    expect(screen.getByText(/Arrows show lineage only/)).toBeVisible();
  });

  it("starts compact on narrow screens", () => {
    const mm = vi.spyOn(window, "matchMedia").mockImplementation((q) => ({ matches: true, media: q, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent: () => false, onchange: null }) as MediaQueryList);
    render(<NetworkLegend simulated />);
    expect(screen.getByRole("button", { name: /legend/i })).toHaveAttribute("aria-expanded", "false");
    mm.mockRestore();
  });
});

describe("inspector additions", () => {
  const open = (n = nodes) => {
    renderMindmap(<MindmapView activity={t3Activity(n, [])} initialListView={false} />);
    fireEvent.click(screen.getByTestId("agent-node-b"));
    return screen.getByRole("complementary");
  };

  it("shows a provider glyph and a status block that keeps the raw reported status", () => {
    const panel = open();
    expect(panel.querySelector(".inspector__glyph.roster-shape--claude")).not.toBeNull();
    const status = within(panel).getByTestId("inspector-status");
    expect(status).toHaveTextContent("FAILED");
    expect(status).toHaveTextContent("T3 reported: running");
  });

  it("copies the session id to the clipboard only", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const panel = open();
    fireEvent.click(within(panel).getByRole("button", { name: "Copy session id" }));
    expect(writeText).toHaveBeenCalledWith("thread-b");
    expect(await within(panel).findByText("Copied")).toBeInTheDocument();
  });

  it("reports an unavailable clipboard instead of failing silently", async () => {
    Object.defineProperty(navigator, "clipboard", { value: undefined, configurable: true });
    const panel = open();
    fireEvent.click(within(panel).getByRole("button", { name: "Copy session id" }));
    expect(await within(panel).findByText("Copy unavailable in this browser")).toBeInTheDocument();
  });
});
