import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { Activity } from "@shared/types";
import fixture from "../../../fixtures/sample-activity.json";
import { SkipLink } from "../components/SkipLink";
import { MindmapView } from "../views/MindmapView";
import { renderMindmap } from "./renderMindmap";

const activity = fixture as Activity;

describe("Keyboard navigation (MM-007)", () => {
  it("skip link targets main content", () => {
    renderMindmap(
      <>
        <SkipLink />
        <MindmapView activity={activity} />
      </>,
    );
    const skip = screen.getByRole("link", { name: /Skip to main content/i });
    expect(skip).toHaveAttribute("href", "#main-content");
    expect(document.getElementById("main-content")).toBeTruthy();
  });

  it("slash focuses timeline filter chips", async () => {
    const user = userEvent.setup();
    renderMindmap(<MindmapView activity={activity} />);
    await user.keyboard("/");
    const allChip = screen.getByRole("button", { name: "All" });
    expect(allChip).toHaveFocus();
  });
});
