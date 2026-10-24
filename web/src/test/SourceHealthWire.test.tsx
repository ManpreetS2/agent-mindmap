import { describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import { MindmapView } from "../views/MindmapView";
import { renderMindmap } from "./renderMindmap";
import { sessionNode, t3Activity } from "./helpers";
import { loadFixture } from "./obsFixtures";

describe("SourceHealthBar wiring", () => {
  it("shows unavailable when observability is absent and still renders the graph", () => {
    const { container } = renderMindmap(
      <MindmapView activity={t3Activity([sessionNode("a")], [])} initialListView={false} observability={{ status: "absent" }} />,
    );
    expect(screen.getByTestId("source-health")).toHaveTextContent(/Source health unavailable/);
    expect(container.querySelector(".mindmap-body")).toBeTruthy();
    expect(container.querySelector(".mindmap-main")).toBeTruthy();
    // Mounted as sibling above mindmap-body, not inside mindmap-main
    const health = container.querySelector("[data-testid=source-health]")!;
    const body = container.querySelector(".mindmap-body")!;
    expect(health.compareDocumentPosition(body) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(body.contains(health)).toBe(false);
  });

  it("demo observability never says verified", () => {
    const { container } = renderMindmap(
      <MindmapView
        activity={t3Activity([sessionNode("a")], [], "demo")}
        initialListView={false}
        observability={{ status: "ok", data: loadFixture("demo") }}
        nowMs={Date.parse(loadFixture("demo").generated_at) + 60_000}
      />,
    );
    expect(screen.getByText(/DEMO — SYNTHETIC DATA/)).toBeTruthy();
    expect(container.textContent!.toLowerCase()).not.toMatch(/\bverified\b/);
  });
});
