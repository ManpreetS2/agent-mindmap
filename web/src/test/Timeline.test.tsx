import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { Activity } from "@shared/types";
import fixture from "../../../fixtures/sample-activity.json";
import { MindmapView } from "../views/MindmapView";
import { renderMindmap } from "./renderMindmap";

const activity = fixture as unknown as Activity;

describe("Timeline (MM-006)", () => {
  it("renders one swim lane label per bot plus unknown", () => {
    renderMindmap(<MindmapView activity={activity} />);
    const timeline = screen.getByRole("group", {
      name: /Activity timeline swim lanes/i,
    });
    expect(within(timeline).getAllByText("Director").length).toBeGreaterThan(0);
    expect(within(timeline).getAllByText("DEV 1").length).toBeGreaterThan(0);
    expect(within(timeline).getAllByText("unattributed").length).toBeGreaterThan(0);
    expect(within(timeline).getAllByText(/Verifier|QA/).length).toBeGreaterThan(0);
  });

  it("toggles type filter chips with aria-pressed", async () => {
    const user = userEvent.setup();
    renderMindmap(<MindmapView activity={activity} />);
    const handoffs = screen.getByRole("button", { name: "Handoffs" });
    expect(handoffs).toHaveAttribute("aria-pressed", "false");
    await user.click(handoffs);
    expect(handoffs).toHaveAttribute("aria-pressed", "true");
  });

  it("exposes timeline task buttons and source links to assistive tech", () => {
    renderMindmap(<MindmapView activity={activity} />);
    expect(
      screen.getAllByRole("button", { name: /RP-005/i }).length,
    ).toBeGreaterThan(0);
    expect(
      screen.getAllByRole("link", {
        name: /Open event source in new tab/i,
      }).length,
    ).toBeGreaterThan(0);
  });

  it("highlights task lifecycle in timeline and graph when task id is clicked", async () => {
    const user = userEvent.setup();
    renderMindmap(<MindmapView activity={activity} />);
    const taskBtn = screen.getAllByTestId("timeline-task-RP-005")[0];
    await user.click(taskBtn);
    expect(screen.getByText(/Lifecycle highlight:/)).toBeInTheDocument();
    expect(screen.getByText(/lifecycle may be incomplete/i)).toBeInTheDocument();
    const dev1 = screen.getByTestId("agent-node-dev-1");
    expect(dev1.className).toMatch(/is-lifecycle-highlight/);
    const dev2 = screen.getByTestId("agent-node-dev-2");
    expect(dev2.className).not.toMatch(/is-lifecycle-highlight/);
  });
});
