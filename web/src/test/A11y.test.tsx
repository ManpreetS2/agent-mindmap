import { screen } from "@testing-library/react";
import { axe } from "vitest-axe";
import { describe, expect, it } from "vitest";
import type { Activity } from "@shared/types";
import fixture from "../../../fixtures/sample-activity.json";
import { MindmapView } from "../views/MindmapView";
import { renderMindmap } from "./renderMindmap";

const activity = fixture as Activity;

function expectNoSeriousOrCritical(results: Awaited<ReturnType<typeof axe>>) {
  const violations = results.violations.filter(
    (v) => v.impact === "serious" || v.impact === "critical",
  );
  expect(violations).toEqual([]);
}

describe("Accessibility (axe)", () => {
  it("list view has no serious or critical axe violations", async () => {
    const { container } = renderMindmap(
      <MindmapView activity={activity} initialListView={true} />,
    );
    expect(screen.getByRole("region", { name: /List view/i })).toBeInTheDocument();
    const results = await axe(container);
    expectNoSeriousOrCritical(results);
  });

  it("graph view shell has no serious or critical axe violations", async () => {
    const { container } = renderMindmap(
      <MindmapView activity={activity} initialListView={false} />,
    );
    const results = await axe(container, {
      rules: {
        "svg-img-alt": { enabled: false },
      },
    });
    expectNoSeriousOrCritical(results);
  });
});
