import { fireEvent, screen, within } from "@testing-library/react";
import { axe } from "vitest-axe";
import { describe, expect, it } from "vitest";
import { MindmapView } from "../views/MindmapView";
import { renderMindmap } from "./renderMindmap";
import { sessionNode, t3Activity } from "./helpers";

const open = (act: ReturnType<typeof t3Activity>, id: string) => {
  const view = renderMindmap(<MindmapView activity={act} initialListView={false} />);
  fireEvent.click(screen.getByTestId(`agent-node-${id}`));
  return { view, panel: screen.getByRole("complementary") };
};

describe("session nodes", () => {
  it("are buttons exposing provider, model, status and task", () => {
    renderMindmap(<MindmapView activity={t3Activity([sessionNode("a", { status: "FAILED" })], [])} initialListView={false} />);
    const node = screen.getByTestId("agent-node-a");
    expect(node.tagName).toBe("BUTTON");
    expect(node).toHaveAttribute("aria-label", "Codex, model-x, FAILED, Task a");
    expect(within(node).getByText("model-x")).toBeInTheDocument();
    expect(node).toHaveAttribute("aria-pressed", "false");
  });

  it("show unknown provider/model honestly and mark selection", () => {
    const n = sessionNode("a", {}, { provider: null, model: null });
    renderMindmap(<MindmapView activity={t3Activity([n], [])} initialListView={false} />);
    const node = screen.getByTestId("agent-node-a");
    expect(within(node).getByText("Unknown provider")).toBeInTheDocument();
    expect(within(node).getByText("Model not reported")).toBeInTheDocument();
    fireEvent.click(node);
    expect(node).toHaveAttribute("aria-pressed", "true");
    expect(node.className).toContain("is-selected");
  });
});

describe("session inspector", () => {
  const a = sessionNode("a", { label: "Parent task" }, { project: "Proj", branch: "feat/p", source_links: ["https://github.com/o/r/pull/3", "javascript:alert(1)"] });
  const b = sessionNode("b", { label: "Child task" }, { provider: "Claude Code", model: "claude-x" });

  it("shows identity, last verified activity, relationships with evidence and history", () => {
    const { panel } = open(t3Activity([a, b], [["a", "b"]]), "b");
    expect(within(panel).getByText("claude-x")).toBeInTheDocument();
    expect(within(panel).getByText("Child task", { selector: "h2" })).toBeInTheDocument();
    expect(within(panel).getByText(/Evidenced parent:/)).toBeInTheDocument();
    expect(within(panel).getByText(/Delegated by/)).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "Parent task" })).toBeInTheDocument();
    expect(within(panel).getAllByText(/T3 reported subagent lineage/).length).toBeGreaterThan(0);
    expect(within(panel).getByText(/does not show that messages were exchanged/)).toBeInTheDocument();
    expect(within(panel).getByText(/Observed status history/i)).toBeInTheDocument();
    expect(within(panel).getByText(/T3 reported thread status: running/)).toBeInTheDocument();
    expect(within(panel).getByText(/not proof of a specific action/)).toBeInTheDocument();
  });

  it("navigates to the related agent", () => {
    const { panel } = open(t3Activity([a, b], [["a", "b"]]), "b");
    fireEvent.click(within(panel).getByRole("button", { name: "Parent task" }));
    expect(screen.getByRole("complementary")).toHaveAccessibleName("Details for Parent task");
  });

  it("only links http(s) sources and states what is unsupported", () => {
    const { panel } = open(t3Activity([a, b], [["a", "b"]]), "a");
    const links = within(panel).getAllByRole("link");
    expect(links.map((l) => l.getAttribute("href"))).toEqual(["https://github.com/o/r/pull/3"]);
    expect(within(panel).getByText(/Prompts, messages, tool output, token usage and credentials are unsupported/)).toBeInTheDocument();
    expect(panel.textContent).not.toMatch(/javascript:/);
  });

  it("makes missing data explicit instead of inventing it", () => {
    const n = sessionNode("x", { current_task: undefined, last_activity_ts: undefined }, { provider: null, model: null, branch: null });
    const { panel } = open(t3Activity([n], []), "x");
    expect(within(panel).getAllByText("Not reported by T3")).toHaveLength(2);
    // task, branch and last-activity are each explicitly "Not reported" (never blank or invented)
    expect(within(panel).getAllByText("Not reported", { selector: "dd" })).toHaveLength(3);
    expect(within(panel).getByTestId("inspector-no-lineage")).toHaveTextContent(/Lineage not reported/);
    expect(within(panel).getByTestId("inspector-no-lineage")).toHaveTextContent(/no delegation lineage reported/i);
    expect(within(panel).getByText(/No external links reported/)).toBeInTheDocument();
  });

  it("explains stale, unknown and unavailable states", () => {
    const stale = sessionNode("s", { status: "STALE" }, { stale: true });
    expect(open(t3Activity([stale], []), "s").panel.textContent).toMatch(/Stale: T3 has reported no update/);
    document.body.innerHTML = "";
    const unknown = sessionNode("u", { status: "UNKNOWN" }, { reported_status: "interrupted" });
    expect(open(t3Activity([unknown], []), "u").panel.textContent).toMatch(/Status unknown: T3 reported “interrupted”/);
    document.body.innerHTML = "";
    const down = open(t3Activity([a], [], "live", undefined, "unavailable"), "a");
    expect(down.panel.textContent).toMatch(/T3 is unavailable\. This is the last known snapshot/);
  });

  it("labels replay data as simulated", () => {
    const { panel } = open(t3Activity([a, b], [["a", "b"]], "demo", { stage: 4, stage_count: 10, cycle: 0, step_sec: 5, label: "x" }), "b");
    expect(within(panel).getByText("SIMULATED")).toBeInTheDocument();
    expect(within(panel).getByText(/Simulated delegation/)).toBeInTheDocument();
    expect(within(panel).getByText("Simulated activity time")).toBeInTheDocument();
  });

  it("has no serious axe violations", async () => {
    const { panel } = open(t3Activity([a, b], [["a", "b"]]), "b");
    const results = await axe(panel, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
  });
});
