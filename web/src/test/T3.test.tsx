import { act, fireEvent, renderHook, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Activity } from "@shared/types";
import { MindmapView } from "../views/MindmapView";
import { renderMindmap } from "./renderMindmap";
import { fgMock } from "./forceGraphMock";
import { createPollTransport, type ActivityTransport } from "../data/activityTransport";
import { useActivityFeed } from "../hooks/useActivityFeed";

const sample: Activity = {
  schema_version: "1.0.0", project: "T3 Code", generated_at: "2026-10-22T20:00:00Z",
  meta: { github: "skipped", t3: { source: "local", mode: "demo", connection: "connected", server_version: "demo", stale_after_sec: 300 } },
  nodes: [{ id: "codex", label: "Implement adapter", group: "sessions", status: "IN_PROGRESS", current_task: "Implement adapter", last_activity_ts: "2026-10-22T20:00:00Z", layout: { x: 0, y: 0 }, agent_links: [], session: { source: "local", thread_id: "one", project: "Project", provider: "Codex", model: "reported-model", reported_status: "running", branch: "feat/t3", source_links: ["https://github.com/example/repo/pull/1"], stale: false } },
  { id: "claude", label: "Review tests", group: "sessions", status: "BLOCKED", layout: { x: 300, y: 0 }, agent_links: [], session: { source: "local", thread_id: "two", project: "Project", provider: "Claude Code", model: null, reported_status: "waiting", branch: null, source_links: [], stale: false } }],
  tasks: [], events: [], edges: [{ id: "delegate", source: "codex", target: "claude", type: "delegation", count: 1, event_ids: ["lineage"] }], unparsed: [],
};
afterEach(() => vi.useRealTimers());

describe("T3 sessions", () => {
  it("renders dynamic providers, unknown models, demo label and details", async () => {
    renderMindmap(<MindmapView activity={sample} />);
    expect(screen.getByText(/DEMO — offline fixtures/)).toBeInTheDocument();
    const codex = screen.getByTestId("agent-node-codex");
    expect(within(codex).getByText("Codex")).toBeInTheDocument();
    expect(within(codex).getByText("reported-model")).toBeInTheDocument();
    expect(screen.getAllByText("Model not reported").length).toBeGreaterThan(0);
    expect(screen.getByText(/Verified delegation/)).toBeInTheDocument();
    expect(screen.queryByText(/showing ledger only/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("agent-node-codex")); // jsdom mouse events lack `view`, which d3-drag needs
    const panel = screen.getByRole("complementary");
    expect(within(panel).getByText("feat/t3")).toBeInTheDocument();
    expect(within(panel).getByRole("link")).toHaveAttribute("href", "https://github.com/example/repo/pull/1");
  });

  it("retains nodes as stale on transport failure and recovers in place", async () => {
    let deliver!: (a: Activity) => void;
    let fail!: (e: Error) => void;
    const transport: ActivityTransport = { kind: "test", fetch: async () => sample,
      subscribe: (data, error) => { deliver = data; fail = error!; return () => {}; } };
    const { result } = renderHook(() => useActivityFeed(transport));
    await act(async () => {});
    expect(result.current.activity?.nodes[0].status).toBe("IN_PROGRESS");
    act(() => fail(new Error("offline")));
    expect(result.current.activity?.nodes[0].status).toBe("STALE");
    expect(result.current.activity?.nodes[0].id).toBe("codex");
    act(() => deliver(sample));
    expect(result.current.activity?.nodes[0].status).toBe("IN_PROGRESS");
  });

  it("retries after initial failure without requiring reload", async () => {
    let deliver!: (a: Activity) => void;
    const transport: ActivityTransport = { kind: "test", fetch: async () => { throw new Error("offline"); }, subscribe: data => { deliver = data; return () => {}; } };
    const { result } = renderHook(() => useActivityFeed(transport));
    await act(async () => {});
    expect(result.current.error).not.toBeNull();
    act(() => deliver(sample));
    expect(result.current.error).toBeNull();
    expect(result.current.activity).toEqual(sample);
  });

  it("uses conditional requests and recovers after failure even on 304", async () => {
    vi.useFakeTimers();
    const fetchImpl = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(sample), { headers: { ETag: '"v1"' } }))
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue(new Response(null, { status: 304 }));
    const transport = createPollTransport({ fetchImpl, intervalMs: 1000 });
    await transport.fetch();
    const data = vi.fn(), error = vi.fn();
    const stop = transport.subscribe!(data, error);
    await vi.advanceTimersByTimeAsync(3000);
    expect(error).toHaveBeenCalledOnce();
    expect(data).toHaveBeenCalledOnce();
    expect(fetchImpl.mock.calls[1][1].headers).toEqual({ "If-None-Match": '"v1"' });
    stop();
  });
});

it("expires running sessions even when the server returns unchanged 304 snapshots", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-22T20:00:00Z"));
  const live: Activity = { ...sample, meta: { ...sample.meta, t3: { ...sample.meta.t3!, mode: "live" } } };
  const fetchImpl = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(live), { headers: { ETag: '"v1"' } }))
    .mockResolvedValue(new Response(null, { status: 304 }));
  const transport = createPollTransport({ fetchImpl, intervalMs: 1000 });
  expect((await transport.fetch()).nodes[0].status).toBe("IN_PROGRESS");
  vi.setSystemTime(new Date("2026-10-22T20:06:00Z"));
  const expired = await transport.fetch();
  expect(expired.nodes[0].status).toBe("STALE");
  expect(expired.nodes[0].id).toBe("codex");
});

function replayStage(tick: number): Activity {
  const stage = tick % 10;
  const states = [
    ["IDLE", "IDLE"], ["IDLE", "IDLE"], ["IN_PROGRESS", "IDLE"],
    ["IN_PROGRESS", "BLOCKED"], ["IN_PROGRESS", "IN_PROGRESS"],
    ["BLOCKED", "IN_PROGRESS"], ["BLOCKED", "FAILED"],
    ["IN_PROGRESS", "IN_PROGRESS"], ["DONE", "DONE"], ["IDLE", "IDLE"],
  ] as const;
  return { ...sample, generated_at: new Date(tick * 5000).toISOString(),
    meta: { ...sample.meta, t3: { ...sample.meta.t3!, replay: {
      stage, stage_count: 10, cycle: Math.floor(tick / 10), step_sec: 5, label: `Simulated stage ${stage + 1}`,
    } } },
    nodes: sample.nodes.map((n, i) => ({ ...n, status: states[stage][i] })),
    edges: stage >= 3 && stage <= 8 ? sample.edges : [],
  };
}

it("shows every replay stage through the existing feed without reloading or duplicate nodes", async () => {
  vi.useFakeTimers();
  let tick = 0;
  const fetchImpl = vi.fn(async () => new Response(JSON.stringify(replayStage(tick))));
  const transport = createPollTransport({ fetchImpl }); // production default is still 10s
  function ReplayView() {
    const feed = useActivityFeed(transport);
    return feed.activity ? <MindmapView activity={feed.activity} statusPulseNodeIds={feed.statusPulseNodeIds} /> : null;
  }
  renderMindmap(<ReplayView />);
  await act(async () => {});
  expect(screen.getByText("DEMO REPLAY — SIMULATED ACTIVITY")).toBeInTheDocument();
  expect(screen.getByText(/Simulated delegation/)).toBeInTheDocument();
  // Subscribe starts before the first response: discovering replay must shorten its first timer too.
  for (tick = 1; tick <= 10; tick++) {
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(screen.getByText(new RegExp(`Stage ${tick % 10 + 1}/10:`))).toBeInTheDocument();
    expect(screen.getAllByTestId(/^agent-node-/)).toHaveLength(2);
    const expected = replayStage(tick);
    for (const node of expected.nodes) {
      expect(screen.getByTestId(`agent-node-${node.id}`)).toHaveAttribute("aria-label", expect.stringContaining(node.status));
    }
    // the canvas model follows the feed in place: same two agents, same objects, current statuses
    const g = (fgMock.props.graphData as { nodes: Array<{ id: string; status: string }> }).nodes;
    expect(g.map((n) => n.id).sort()).toEqual(expected.nodes.map((n) => n.id).sort());
    for (const node of expected.nodes) expect(g.find((n) => n.id === node.id)!.status).toBe(node.status);
  }
  expect(screen.getByText(/Cycle 2/)).toBeInTheDocument();
  expect(fetchImpl.mock.calls.length).toBe(11);
});

it("keeps the normal cadence for static demo and live sources with stray replay metadata", async () => {
  vi.useFakeTimers();
  for (const activity of [sample, { ...replayStage(0), meta: { ...sample.meta, t3: { ...replayStage(0).meta.t3!, mode: "live" as const } } }]) {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify(activity)));
    const transport = createPollTransport({ fetchImpl });
    await transport.fetch();
    const stop = transport.subscribe!(vi.fn());
    await vi.advanceTimersByTimeAsync(9000);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    stop();
  }
});
