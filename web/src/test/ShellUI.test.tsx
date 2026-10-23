import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { Activity } from "@shared/types";
import legacy from "../../../fixtures/sample-activity.json";
import { MindmapView } from "../views/MindmapView";
import { renderMindmap } from "./renderMindmap";
import { sessionNode, t3Activity } from "./helpers";

const nodes = [
  sessionNode("a", { status: "IN_PROGRESS" }), sessionNode("b", { status: "BLOCKED" }),
  sessionNode("c", { status: "FAILED" }), sessionNode("d", { status: "DONE" }),
];
beforeEach(() => window.localStorage.clear());
afterEach(() => window.localStorage.clear());

describe("header", () => {
  it("shows agents, state breakdown and DELEGATIONS (not ledger handoffs) for T3 data", () => {
    renderMindmap(<MindmapView activity={t3Activity(nodes, [["a", "b"]], "live")} initialListView={false} />);
    const summary = screen.getByRole("list", { name: "Agent summary" });
    expect(within(summary).getByText("4")).toBeInTheDocument();
    expect(within(summary).getByText(/working/)).toBeInTheDocument();
    expect(within(summary).getByText(/blocked/)).toBeInTheDocument();
    expect(within(summary).getByText(/failed/)).toBeInTheDocument();
    expect(screen.getByLabelText("Delegation relationship count")).toHaveTextContent("1 delegation");
    expect(screen.queryByLabelText("Handoff edge count")).not.toBeInTheDocument();
  });

  it("keeps the ledger 'Handoffs' counter for legacy data", () => {
    renderMindmap(<MindmapView activity={legacy as Activity} />);
    expect(screen.getByLabelText("Handoff edge count")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Agent summary" })).not.toBeInTheDocument();
  });

  it.each([
    ["live", "connected", "source-chip--live"],
    ["live", "unavailable", "source-chip--unavailable"],
    ["demo", "connected", "source-chip--demo"],
  ] as const)("source chip is %s/%s", (mode, connection, cls) => {
    const { container } = renderMindmap(<MindmapView activity={t3Activity(nodes, [], mode, undefined, connection)} initialListView={false} />);
    expect(container.querySelector(`.source-chip.${cls}`)).not.toBeNull();
  });
});

describe("demo indicator stays unmistakable but compact", () => {
  it("static demo: one slim persistent strip with an explanation", () => {
    const { container } = renderMindmap(<MindmapView activity={t3Activity(nodes, [], "demo")} initialListView={false} />);
    const strip = container.querySelector(".demo-replay-banner")!;
    expect(strip).toHaveTextContent("DEMO — SYNTHETIC FIXTURE DATA");
    expect(strip).toHaveAttribute("title", expect.stringMatching(/not real T3 activity/));
    expect(container.querySelectorAll(".demo-replay-banner")).toHaveLength(1);
  });
  it("replay: strip says SIMULATED and shows the stage", () => {
    const { container } = renderMindmap(
      <MindmapView activity={t3Activity(nodes, [], "demo", { stage: 2, stage_count: 10, cycle: 0, step_sec: 5, label: "Tests run" })} initialListView={false} />,
    );
    const strip = container.querySelector(".demo-replay-banner")!;
    expect(strip).toHaveTextContent("DEMO REPLAY — SIMULATED ACTIVITY");
    expect(strip).toHaveTextContent("Stage 3/10: Tests run");
  });
  it("live data never shows a demo strip", () => {
    const { container } = renderMindmap(<MindmapView activity={t3Activity(nodes, [], "live")} initialListView={false} />);
    expect(container.querySelector(".demo-replay-banner")).toBeNull();
  });
});

describe("timeline drawer", () => {
  it("is collapsed for T3 sessions and opens on demand (graph is not resized)", () => {
    const { container } = renderMindmap(<MindmapView activity={t3Activity(nodes, [], "live")} initialListView={false} />);
    const toggle = screen.getByRole("button", { name: /Activity timeline/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(container.querySelector(".timeline-region--overlay")).not.toBeNull();
    expect(container.querySelector("#timeline-drawer")).toHaveAttribute("hidden");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(container.querySelector("#timeline-drawer")).not.toHaveAttribute("hidden");
  });
  it("stays open for the legacy ledger view", () => {
    renderMindmap(<MindmapView activity={legacy as Activity} />);
    expect(screen.getByRole("button", { name: /Activity timeline/ })).toHaveAttribute("aria-expanded", "true");
  });
});

describe("roster", () => {
  const open = () => renderMindmap(<MindmapView activity={t3Activity(nodes, [["a", "b"]], "live")} initialListView={false} />);
  it("filters by state chips and announces the result", () => {
    open();
    const group = screen.getByRole("group", { name: "Show agents by state" });
    fireEvent.click(within(group).getByRole("button", { name: /Attention/ }));
    expect(screen.getByTestId("agent-node-b")).toBeInTheDocument();
    expect(screen.getByTestId("agent-node-c")).toBeInTheDocument();
    expect(screen.queryByTestId("agent-node-a")).not.toBeInTheDocument();
    expect(within(group).getByRole("button", { name: /Attention/ })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(within(group).getByRole("button", { name: /^All/ }));
    expect(screen.getByTestId("agent-node-a")).toBeInTheDocument();
  });
  it("collapses to a rail, keeps every agent reachable, and remembers the choice", () => {
    const { unmount } = open();
    const collapse = screen.getByRole("button", { name: "Collapse agents panel" });
    expect(collapse).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(collapse);
    expect(screen.getByRole("button", { name: "Expand agents panel" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("navigation", { name: "Agents" })).toHaveClass("is-collapsed");
    expect(screen.getByTestId("agent-node-a")).toBeInTheDocument(); // still operable from the rail
    expect(window.localStorage.getItem("mindmapRosterCollapsed")).toBe("1");
    unmount();
    open();
    expect(screen.getByRole("navigation", { name: "Agents" })).toHaveClass("is-collapsed");
  });
});

describe("list view (T3)", () => {
  it("uses agent/relationship vocabulary, shows provider+model and honest empty states", () => {
    renderMindmap(<MindmapView activity={t3Activity(nodes, [], "live")} initialListView />);
    expect(screen.getByRole("heading", { name: /^Agents/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /^Relationships/ })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /^Bots/ })).not.toBeInTheDocument();
    expect(screen.getByText("No delegation relationships reported.")).toBeInTheDocument();
    expect(screen.getByText(/No ledger tasks/)).toBeInTheDocument();
    expect(screen.getAllByRole("columnheader", { name: /Provider · model/ }).length).toBeGreaterThan(0);
  });
  it("keeps the legacy vocabulary for ledger data", () => {
    renderMindmap(<MindmapView activity={legacy as Activity} initialListView />);
    expect(screen.getByRole("heading", { name: /^Bots/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /^Edges/ })).toBeInTheDocument();
  });
});
