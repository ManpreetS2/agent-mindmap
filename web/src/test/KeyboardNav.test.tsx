import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { Activity } from "@shared/types";
import fixture from "../../../fixtures/sample-activity.json";
import { SkipLink } from "../components/SkipLink";
import { ListView } from "../components/ListView";
import { MindmapView } from "../views/MindmapView";
import { renderMindmap } from "./renderMindmap";

const activity = fixture as Activity;

describe("Keyboard navigation (MM-007 §6)", () => {
  it("skip link targets main content", () => {
    renderMindmap(
      <>
        <SkipLink />
        <MindmapView activity={activity} initialListView={false} />
      </>,
    );
    const skip = screen.getByRole("link", { name: /Skip to main content/i });
    expect(skip).toHaveAttribute("href", "#main-content");
  });

  it("slash focuses timeline filter chips", async () => {
    const user = userEvent.setup();
    renderMindmap(<MindmapView activity={activity} initialListView={false} />);
    await user.keyboard("/");
    expect(screen.getByRole("button", { name: "All" })).toHaveFocus();
  });

  it("arrow keys move between graph nodes spatially", () => {
    renderMindmap(<MindmapView activity={activity} initialListView={false} />);
    const graph = screen.getByRole("region", { name: /Agent graph/i });
    graph.focus();
    fireEvent.keyDown(graph, { key: "ArrowDown" });
    expect(screen.getByTestId("agent-node-director")).toHaveFocus();
  });

  it("arrow keys do not open the detail panel (QA-MM007-4)", () => {
    renderMindmap(<MindmapView activity={activity} initialListView={false} />);
    const graph = screen.getByRole("region", { name: /Agent graph/i });
    graph.focus();
    fireEvent.keyDown(graph, { key: "ArrowDown" });
    expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
    fireEvent.keyDown(graph, { key: "ArrowRight" });
    expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
  });

  it("arrow keys move between timeline event focus targets", () => {
    renderMindmap(<MindmapView activity={activity} initialListView={false} />);
    const timeline = screen.getByRole("region", { name: /Activity timeline/i });
    timeline.focus();
    fireEvent.keyDown(timeline, { key: "ArrowRight" });
    const buttons = document.querySelectorAll("[data-timeline-focus]");
    expect(buttons.length).toBeGreaterThan(0);
    expect(document.activeElement?.getAttribute("data-timeline-focus")).toBeTruthy();
  });

  it("Tab reaches graph and list focus regions", async () => {
    const user = userEvent.setup();
    renderMindmap(
      <MindmapView activity={activity} initialListView={true} />,
    );
    await user.tab();
    await user.tab();
    const listRegion = screen.getByRole("region", { name: /List view/i });
    expect(listRegion).toHaveAttribute("tabindex", "0");
  });

  it("Enter on graph node opens detail panel", async () => {
    const user = userEvent.setup();
    renderMindmap(<MindmapView activity={activity} initialListView={false} />);
    const dev1 = screen.getByTestId("agent-node-dev-1");
    dev1.focus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("complementary", { name: /DEV 1/i })).toBeInTheDocument();
  });

  it("Escape closes detail panel before lifecycle highlight", async () => {
    const user = userEvent.setup();
    renderMindmap(<MindmapView activity={activity} initialListView={false} />);
    await user.click(screen.getByTestId("agent-node-architect"));
    expect(screen.getByRole("complementary")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
  });

  it("list view shows UnsourcedTag for non-http task source_url (QA-MM006-3)", () => {
    const withLedger: Activity = {
      ...activity,
      tasks: [
        {
          id: "RP-888",
          title: "ledger only",
          project: "fencepost",
          owner: "DEV 1",
          status_raw: "PLANNED",
          status: "IDLE",
          prs: [],
          source_url: "build/task-ledger.md#RP-888",
        },
      ],
    };
    renderMindmap(
      <ListView activity={withLedger} selectedNodeId={null} onSelectNode={() => {}} />,
    );
    expect(screen.getAllByLabelText("Unsourced fact").length).toBeGreaterThan(0);
    expect(screen.queryByRole("link", { name: "ledger" })).not.toBeInTheDocument();
  });

  it("list view shows UnsourcedTag when task has no source_url", () => {
    const withUnsourced: Activity = {
      ...activity,
      tasks: [
        {
          id: "RP-999",
          title: "orphan",
          project: "fencepost",
          owner: "DEV 1",
          status_raw: "PLANNED",
          status: "IDLE",
          prs: [],
          source_url: "",
        },
      ],
    };
    renderMindmap(
      <ListView activity={withUnsourced} selectedNodeId={null} onSelectNode={() => {}} />,
    );
    expect(screen.getAllByLabelText("Unsourced fact").length).toBeGreaterThan(0);
  });
});
