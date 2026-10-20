import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Activity, Event, Node } from "@shared/types";
import { DetailPanel } from "../components/DetailPanel";

const baseNode = (overrides: Partial<Node>): Node => ({
  id: "test-bot",
  label: "Test Bot",
  group: "build",
  status: "IN_PROGRESS",
  agent_links: [],
  layout: { x: 0, y: 0 },
  ...overrides,
});

const emptyActivity: Activity = {
  schema_version: "1.0.0",
  generated_at: "2026-10-20T04:58:00-07:00",
  project: "fencepost",
  meta: { github: "ok" },
  nodes: [],
  tasks: [],
  events: [],
  edges: [],
  unparsed: [],
};

function renderPanel(node: Node, activity: Activity) {
  return render(
    <DetailPanel node={node} activity={activity} onClose={() => {}} />,
  );
}

describe("DetailPanel fact sources (QA-MM005-1)", () => {
  it("shows unsourced for ledger event when task is missing from tasks[]", () => {
    const events: Event[] = [
      {
        id: "evt-rp-orphan",
        type: "handoff",
        actor: "test-bot",
        target: "architect",
        task_id: "RP-009",
        attribution: { method: "ledger_owner" },
        source_url: "build/task-ledger.md#line-42",
        source_time: "2026-10-19T21:20:00-07:00",
        raw: "handoff note",
      },
    ];
    const node = baseNode({ id: "test-bot", current_task: "RP-009" });
    renderPanel(node, { ...emptyActivity, events });

    const panel = screen.getByRole("complementary");
    expect(within(panel).getByText("RP-009")).toBeInTheDocument();
    expect(
      within(panel).queryByRole("link", { name: "RP-009" }),
    ).not.toBeInTheDocument();
    expect(within(panel).getAllByLabelText("Unsourced fact").length).toBeGreaterThan(0);
  });

  it("links current task when event source is https", () => {
    const events: Event[] = [
      {
        id: "evt-pr",
        type: "pr_opened",
        actor: "test-bot",
        target: null,
        task_id: "RP-009",
        attribution: { method: "signature" },
        source_url: "https://github.com/o/r/pull/9",
        source_time: "2026-10-19T21:20:00-07:00",
        raw: "pr opened",
      },
    ];
    const node = baseNode({ id: "test-bot", current_task: "RP-009" });
    renderPanel(node, { ...emptyActivity, events });

    const panel = screen.getByRole("complementary");
    const taskLink = within(panel).getByRole("link", { name: "RP-009" });
    expect(taskLink).toHaveAttribute("href", "https://github.com/o/r/pull/9");
  });

  it("shows unsourced for ledger-backed last_activity_ts fallback", () => {
    const events: Event[] = [
      {
        id: "evt-ts-only",
        type: "note",
        actor: null,
        target: null,
        task_id: null,
        attribution: { method: "unknown" },
        source_url: "build/task-ledger.md#note-7",
        source_time: "2026-10-19T22:00:00-07:00",
        raw: "ambient note",
      },
    ];
    const node = baseNode({
      id: "lonely-bot",
      status: "IDLE",
      last_activity_ts: "2026-10-19T22:00:00-07:00",
    });
    renderPanel(node, { ...emptyActivity, events });

    const panel = screen.getByRole("complementary");
    expect(
      within(panel).queryByRole("link", { name: /node snapshot/i }),
    ).not.toBeInTheDocument();
    expect(within(panel).getAllByLabelText("Unsourced fact").length).toBeGreaterThan(0);
  });

  it("shows unsourced tag when no task row and no events exist", () => {
    const node = baseNode({
      current_task: "RP-999",
      last_activity_ts: "2026-10-19T22:05:00-07:00",
    });
    renderPanel(node, emptyActivity);

    const panel = screen.getByRole("complementary");
    const unsourced = within(panel).getAllByLabelText("Unsourced fact");
    expect(unsourced.length).toBeGreaterThanOrEqual(2);
    expect(within(panel).getByText("RP-999")).toBeInTheDocument();
    expect(
      within(panel).queryByRole("link", { name: "RP-999" }),
    ).not.toBeInTheDocument();
    expect(
      within(panel).queryByRole("link", { name: /node snapshot/i }),
    ).not.toBeInTheDocument();
  });
});
