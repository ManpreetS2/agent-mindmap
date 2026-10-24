import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AgentRoster } from "../components/AgentRoster";
import { MindmapView } from "../views/MindmapView";
import { renderMindmap } from "./renderMindmap";
import { sessionNode, t3Activity } from "./helpers";

describe("roster account + inspector lineage", () => {
  it("keeps pinned aria-label and shows account separately", () => {
    const withAcct = sessionNode(
      "b",
      { status: "FAILED", current_task: "Fix build" },
      { provider: "Claude Code", model: "claude-x", account: { id: "claudeAgent_2", label: "Claude2" } },
    );
    const without = sessionNode("a", { status: "DONE" });
    render(
      <AgentRoster
        nodes={[withAcct, without]}
        selectedId={null}
        hoveredId={null}
        onSelect={vi.fn()}
        onHover={vi.fn()}
        now={new Date("2026-10-22T20:05:00Z")}
      />,
    );
    expect(screen.getByTestId("agent-node-b")).toHaveAttribute(
      "aria-label",
      "Claude, claude-x, FAILED, Fix build",
    );
    expect(screen.getByTestId("roster-account-b")).toHaveTextContent("Claude2");
    expect(screen.getByTestId("roster-account-a")).toHaveTextContent("account not reported");
    expect(screen.getByTestId("roster-account-a").textContent).toMatch(/not an available worker/);
    expect(screen.getByTestId("agent-node-b").getAttribute("aria-description")).toMatch(/Claude2/);
  });

  it("inspector shows evidenced parent with time vs lineage not reported", () => {
    const a = sessionNode("a", { label: "Parent task" });
    const b = sessionNode("b", { label: "Child task" }, { provider: "Claude Code", model: "claude-x" });
    renderMindmap(<MindmapView activity={t3Activity([a, b], [["a", "b"]])} initialListView={false} />);
    fireEvent.click(screen.getByTestId("agent-node-b"));
    const panel = screen.getByRole("complementary");
    expect(within(panel).getByText(/Evidenced parent:/)).toBeTruthy();
    expect(within(panel).getByText(/evidence /)).toBeTruthy();
    expect(within(panel).getByText(/account not reported/i)).toBeTruthy();

    document.body.innerHTML = "";
    renderMindmap(<MindmapView activity={t3Activity([sessionNode("x")], [])} initialListView={false} />);
    fireEvent.click(screen.getByTestId("agent-node-x"));
    expect(screen.getByTestId("inspector-no-lineage")).toHaveTextContent(/Lineage not reported/);
    expect(screen.getByTestId("inspector-no-lineage")).toHaveTextContent(/no delegation lineage reported/);
  });
});
