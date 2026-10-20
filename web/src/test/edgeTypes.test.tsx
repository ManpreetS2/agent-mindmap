import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Activity, Edge, Event, Node } from "@shared/types";
import { ReactFlowProvider } from "@xyflow/react";
import { EdgeLegend } from "../components/EdgeLegend";
import { AgentGraph } from "../components/AgentGraph";
import { buildGraphEdges } from "../utils/buildGraphEdges";
import { EDGE_VISUALS } from "../utils/edgeStyles";
import { readEventProvenance, tooltipForEdge } from "../utils/edgeTooltip";
import { layoutMultiGroupClusters } from "../utils/graphLayout";

function makeNode(
  id: string,
  group: Node["group"],
  groups: string[],
): Node {
  return {
    id,
    label: id,
    group,
    groups,
    status: "IN_PROGRESS",
    agent_links: [],
    layout: { x: 0, y: 0 },
  };
}

const events: Event[] = [
  {
    id: "msg-1",
    type: "message",
    actor: "director",
    target: null,
    task_id: null,
    attribution: { method: "unknown" },
    source_url: "",
    source_time: "2026-10-20T10:00:00-07:00",
    raw: "hello build",
    provenance: "agent-reported",
    group: "build",
  },
  {
    id: "msg-2",
    type: "message",
    actor: "architect",
    target: "qa-verifier",
    task_id: "MM-020",
    attribution: { method: "signature" },
    source_url: "https://example.com",
    source_time: "2026-10-20T10:05:00-07:00",
    raw: "please verify",
    provenance: "observed",
    recipients: ["qa-verifier"],
    group: "qr",
  },
  {
    id: "h-1",
    type: "handoff",
    actor: "architect",
    target: "dev-1",
    task_id: "MM-020",
    attribution: { method: "ledger_owner" },
    source_url: "https://example.com/ledger",
    source_time: "2026-10-20T09:00:00-07:00",
    raw: "handoff",
    provenance: "agent-reported",
  },
];

const edges: Edge[] = [
  {
    id: "edge-msg-group",
    source: "director",
    target: "group:build",
    type: "message",
    count: 1,
    event_ids: ["msg-1"],
  },
  {
    id: "edge-msg-bot",
    source: "architect",
    target: "qa-verifier",
    type: "message",
    count: 1,
    event_ids: ["msg-2"],
  },
  {
    id: "edge-handoff",
    source: "architect",
    target: "dev-1",
    type: "handoff",
    count: 1,
    event_ids: ["h-1"],
  },
];

const activity: Activity = {
  schema_version: "1.1.0",
  generated_at: "2026-10-20T12:00:00-07:00",
  project: "fencepost",
  meta: { github: "ok" },
  nodes: [
    makeNode("director", "build", ["build", "qr", "radar"]),
    makeNode("architect", "build", ["build", "qr"]),
    makeNode("dev-1", "build", ["build"]),
    makeNode("qa-verifier", "qr", ["qr"]),
  ],
  tasks: [],
  events,
  edges,
  unparsed: [],
};

describe("edge types (MM-020f)", () => {
  it("message edge visual is distinct from handoff", () => {
    expect(EDGE_VISUALS.message.stroke).toBe("var(--edge-message)");
    expect(EDGE_VISUALS.message.strokeDasharray).toBeTruthy();
    expect(EDGE_VISUALS.message.stroke).not.toBe(EDGE_VISUALS.handoff.stroke);
    expect(EDGE_VISUALS.message.label).toBe("Message");
  });

  it("tooltip includes provenance for message edges", () => {
    const tip = tooltipForEdge(edges[0], events);
    expect(tip).toMatch(/Message/);
    expect(tip).toMatch(/director/);
    expect(tip).toMatch(/group:Build/);
    expect(tip).toMatch(/provenance: agent-reported/);
    // 1.1.0 events always carry provenance
    expect(readEventProvenance(events[0])).toBe("agent-reported");
  });

  it("tolerates legacy 1.0.0 events that omit provenance on disk", () => {
    const legacy = {
      id: "legacy-1",
      type: "handoff" as const,
      actor: "architect",
      target: "dev-1",
      task_id: null,
      attribution: { method: "ledger_owner" as const },
      source_url: "",
      source_time: "2026-10-19T12:00:00-07:00",
      raw: "old",
    };
    expect(readEventProvenance(legacy as Event)).toBeUndefined();
    const tip = tooltipForEdge(
      {
        id: "e-legacy",
        source: "architect",
        target: "dev-1",
        type: "handoff",
        count: 1,
        event_ids: ["legacy-1"],
      },
      [legacy as Event],
    );
    expect(tip).toMatch(/Handoff/);
    expect(tip).not.toMatch(/provenance:/);
  });

  it("buildGraphEdges uses messageEdge type and keeps handoff particles", () => {
    const layout = layoutMultiGroupClusters(activity.nodes, activity.edges);
    const visible = new Set(activity.nodes.map((n) => n.id));
    const selected = new Set(["build", "qr", "radar"]);
    const flowEdges = buildGraphEdges({
      activity,
      visibleAgentIds: visible,
      selectedGroups: selected,
      membershipLinks: layout.membershipLinks,
      lifecycleActive: false,
      lifecycleEdgeIds: null,
      reduceMotion: false,
      nowMs: Date.parse("2026-10-20T12:00:00-07:00"),
    });

    const msgGroup = flowEdges.find((e) => e.id === "edge-msg-group");
    expect(msgGroup?.type).toBe("messageEdge");
    expect(msgGroup?.data).toMatchObject({ showParticles: false });
    expect(String((msgGroup?.data as { tooltip?: string })?.tooltip)).toMatch(
      /provenance: agent-reported/,
    );

    const msgBot = flowEdges.find((e) => e.id === "edge-msg-bot");
    expect(msgBot?.type).toBe("messageEdge");
    expect(msgBot?.target).toBe("qa-verifier");

    const handoff = flowEdges.find((e) => e.id === "edge-handoff");
    expect(handoff?.type).toBe("handoffEdge");
    // Recent relative to nowMs → particles on for handoff only
    expect(handoff?.data).toMatchObject({ showParticles: true });

    const membership = flowEdges.filter((e) => e.type === "membershipEdge");
    expect(membership.some((e) => e.id === "membership:director:qr")).toBe(
      true,
    );
    expect(membership.some((e) => e.target === "group:qr")).toBe(true);
  });

  it("legend lists message and membership alongside classic types", () => {
    render(<EdgeLegend />);
    const legend = screen.getByRole("list", { name: /Edge types legend/i });
    expect(within(legend).getByText(/Handoff/i)).toBeInTheDocument();
    expect(within(legend).getByText(/^Message$/i)).toBeInTheDocument();
    expect(
      within(legend).getByText(/Multi-group membership/i),
    ).toBeInTheDocument();
  });

  it("renders group filter, anchors, and multi-group agents", () => {
    render(
      <ReactFlowProvider>
        <div style={{ width: 800, height: 600 }}>
          <AgentGraph
            activity={activity}
            selectedNodeId={null}
            onOpenNodeDetail={() => {}}
            onClearNodeDetail={() => {}}
            lifecycleNodeIds={null}
            lifecycleEdgeIds={null}
          />
        </div>
      </ReactFlowProvider>,
    );

    expect(screen.getByTestId("group-filter")).toBeInTheDocument();
    expect(screen.getByTestId("group-anchor-build")).toBeInTheDocument();
    expect(screen.getByTestId("group-anchor-qr")).toBeInTheDocument();
    expect(screen.getByTestId("agent-node-director")).toBeInTheDocument();
    expect(screen.getByTestId("group-filter-build")).toBeInTheDocument();
  });
});
