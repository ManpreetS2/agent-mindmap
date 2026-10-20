import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { Activity } from "@shared/types";
import fixture from "../../../fixtures/sample-activity.json";
import { MindmapView } from "../views/MindmapView";
import { renderMindmap } from "./renderMindmap";

const activity = fixture as unknown as Activity;

describe("Mindmap graph view", () => {
  it("renders every node from the fixture at fixed layout", () => {
    renderMindmap(<MindmapView activity={activity} />);

    for (const node of activity.nodes) {
      expect(screen.getByTestId(`agent-node-${node.id}`)).toBeInTheDocument();
    }
  });

  it("shows thin-handoff banner when handoff edges are below threshold", () => {
    renderMindmap(<MindmapView activity={activity} />);
    expect(
      screen.getByText(/Handoffs happen in chat rooms/i),
    ).toBeInTheDocument();
  });

  it("opens the detail panel on node click with sourced facts", async () => {
    const user = userEvent.setup();
    renderMindmap(<MindmapView activity={activity} />);

    const dev1 = screen.getByTestId("agent-node-dev-1");
    await user.click(dev1);

    const panel = screen.getByRole("complementary", { name: /DEV 1/i });
    expect(within(panel).getByText("Current task")).toBeInTheDocument();
    expect(within(panel).getAllByText("RP-004").length).toBeGreaterThan(0);
    expect(
      within(panel).queryByRole("link", { name: "RP-004" }),
    ).not.toBeInTheDocument();
    expect(within(panel).getAllByLabelText("Unsourced fact").length).toBeGreaterThan(0);
    expect(within(panel).getAllByText(/attribution:/i).length).toBeGreaterThan(
      0,
    );
  });

  it("closes the detail panel on Escape", async () => {
    const user = userEvent.setup();
    renderMindmap(<MindmapView activity={activity} />);
    await user.click(screen.getByTestId("agent-node-architect"));
    expect(screen.getByRole("complementary")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
  });

  it("lists edge types including message in the legend", () => {
    renderMindmap(<MindmapView activity={activity} />);
    const legend = screen.getByRole("list", { name: /Edge types legend/i });
    expect(within(legend).getByText(/Handoff/i)).toBeInTheDocument();
    expect(within(legend).getByText(/Review verdict/i)).toBeInTheDocument();
    expect(within(legend).getByText(/PR link/i)).toBeInTheDocument();
    expect(within(legend).getByText(/Merge/i)).toBeInTheDocument();
    expect(within(legend).getByText(/^Message$/i)).toBeInTheDocument();
  });
});
