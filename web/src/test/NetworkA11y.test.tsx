import { render, screen } from "@testing-library/react";
import { axe } from "vitest-axe";
import { describe, expect, it, vi } from "vitest";
import { AgentNetwork } from "../components/AgentNetwork";
import { MindmapView } from "../views/MindmapView";
import { renderMindmap } from "./renderMindmap";
import { sessionNode, t3Activity } from "./helpers";

const nodes = ["a", "b", "c"].map((i) => sessionNode(i));
const base = { selectedNodeId: null, onOpenNodeDetail: vi.fn(), onClearNodeDetail: vi.fn() };

describe("network accessibility", () => {
  it("network view (roster, controls, legend) has no serious axe violations", async () => {
    const { container } = renderMindmap(<MindmapView activity={t3Activity(nodes, [["a", "b"]])} initialListView={false} />);
    const region = container.querySelector(".graph-region") as HTMLElement;
    const results = await axe(region, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
  });

  it("describes delegation lineage in text for non-visual users", () => {
    render(<AgentNetwork {...base} activity={t3Activity(nodes, [["a", "b"]])} />);
    expect(screen.getByText("delegated 1 agent")).toBeInTheDocument();
    expect(screen.getByText("delegated by Task a")).toBeInTheDocument();
    expect(screen.getByTestId("agent-node-b").getAttribute("aria-description")).toMatch(/delegated by Task a/);
  });

  it("never encodes provider or status by colour alone", () => {
    render(<AgentNetwork {...base} activity={t3Activity([sessionNode("x", { status: "FAILED" }, { provider: "Claude Code" })], [])} />);
    const item = screen.getByTestId("agent-node-x");
    expect(item).toHaveTextContent("Claude");
    expect(item).toHaveTextContent("FAILED");
  });
});
