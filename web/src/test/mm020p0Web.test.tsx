import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Activity } from "@shared/types";
import {
  createSseTransport,
  SSE_REFETCH_MIN_MS,
} from "../data/activityTransport";
import { MindmapView } from "../views/MindmapView";
import { StatusPill } from "../components/StatusPill";
import { displayProject } from "../utils/activityMeta";
import {
  sourceUnavailableMessage,
} from "../utils/viewState";
import { renderMindmap } from "./renderMindmap";
import { refreshRateLimitMessage } from "../utils/viewState";

const baseActivity: Activity = {
  schema_version: "1.1.0",
  generated_at: "2026-10-20T12:00:00Z",
  project: "fencepost",
  meta: { github: "ok", ledger: "ok" },
  nodes: [
    {
      id: "director",
      label: "Director",
      group: "build",
      groups: ["build"],
      status: "UNKNOWN",
      agent_links: [],
      layout: { x: 0, y: 0 },
    },
  ],
  tasks: [],
  events: [],
  edges: [],
  unparsed: [],
};

describe("MM-020-P0 web contract", () => {
  it("source unavailable includes ledger_error and unhealthy github", () => {
    const msg = sourceUnavailableMessage({
      github: "never_run",
      ledger: "unavailable",
      ledger_error: "ledger not found",
    } as unknown as Activity["meta"]);
    expect(msg).toMatch(/SOURCE UNAVAILABLE/i);
    expect(msg).toMatch(/ledger: unavailable/);
    expect(msg).toMatch(/GitHub: never_run/);
    expect(msg).toMatch(/ledger not found/);
  });

  it("missing meta ledger/github does not show source unavailable", () => {
    expect(sourceUnavailableMessage({ github: "ok" })).toBeNull();
    expect(sourceUnavailableMessage({} as Activity["meta"])).toBeNull();
  });

  it("unknown ledger enum values are treated as unhealthy", () => {
    const msg = sourceUnavailableMessage({
      github: "ok",
      ledger: "mystery",
    } as unknown as Activity["meta"]);
    expect(msg).toMatch(/ledger: mystery/);
  });

  it("header uses meta.project when present", () => {
    const activity = {
      ...baseActivity,
      project: "fencepost",
      meta: { ...baseActivity.meta, project: "agent-mindmap" },
    } as Activity;
    expect(displayProject(activity)).toBe("agent-mindmap");
    renderMindmap(<MindmapView activity={activity} />);
    expect(screen.getByText(/Project: agent-mindmap/)).toBeInTheDocument();
  });

  it("shows DISCONNECTED when SSE is down", () => {
    renderMindmap(
      <MindmapView activity={baseActivity} sseDisconnected />,
    );
    expect(screen.getByText(/DISCONNECTED/i)).toBeInTheDocument();
  });

  it("UNKNOWN status pill is visually distinct from IDLE", () => {
    const { container: idle } = render(<StatusPill status="IDLE" />);
    const { container: unknown } = render(<StatusPill status="UNKNOWN" />);
    const idlePill = idle.querySelector(".status-pill") as HTMLElement;
    const unknownPill = unknown.querySelector(".status-pill") as HTMLElement;
    expect(unknownPill.style.border).toContain("dashed");
    expect(idlePill.style.border).not.toContain("dashed");
  });

  it("maps unknown runtime status to UNKNOWN pill", () => {
    render(<StatusPill status={"BROKEN" as Activity["nodes"][0]["status"]} />);
    expect(screen.getByText("UNKNOWN")).toBeInTheDocument();
  });
});

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  onopen: (() => void) | null = null;
  url: string;
  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }
  close() {}
  emitMessage() {
    this.onmessage?.(new MessageEvent("message", { data: "{}" }));
  }
  emitError() {
    this.onerror?.(new Event("error"));
  }
  emitOpen() {
    this.onopen?.();
  }
}

describe("SSE connection + refetch (MM-020-P0)", () => {
  it("notifies on disconnect and reconnect through backoff", async () => {
    vi.useFakeTimers();
    FakeEventSource.instances = [];
    const connections: boolean[] = [];
    const sample = { ...baseActivity };
    const fetchImpl = vi.fn(
      async () =>
        new Response(JSON.stringify(sample), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    );
    const transport = createSseTransport({
      fetchImpl: fetchImpl as typeof fetch,
      intervalMs: 100,
      sseRetryInitialMs: 200,
      refetchMinMs: SSE_REFETCH_MIN_MS,
      EventSourceImpl: FakeEventSource as unknown as typeof EventSource,
      onSseConnectionChange: (c) => connections.push(c),
    });
    const stop = transport.subscribe!(() => undefined);
    expect(connections).toContain(true);
    FakeEventSource.instances[0].emitError();
    expect(connections).toContain(false);
    await vi.advanceTimersByTimeAsync(250);
    const retryEs = FakeEventSource.instances.at(-1);
    retryEs?.emitOpen();
    expect(connections.filter((c) => c).length).toBeGreaterThanOrEqual(2);
    stop();
    vi.useRealTimers();
  });

  it("refetches activity after SSE message (new data visible)", async () => {
    FakeEventSource.instances = [];
    let version = 0;
    const fetchImpl = vi.fn(async () => {
      version += 1;
      const body = {
        ...baseActivity,
        events:
          version >= 1
            ? [
                {
                  id: "evt-1",
                  type: "message",
                  actor: "director",
                  source_time: "2026-10-20T12:01:00Z",
                  provenance: "agent-reported",
                },
              ]
            : [],
      };
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    });
    const transport = createSseTransport({
      fetchImpl: fetchImpl as typeof fetch,
      refetchMinMs: 10,
      EventSourceImpl: FakeEventSource as unknown as typeof EventSource,
    });
    const seen: Activity[] = [];
    const stop = transport.subscribe!((a) => seen.push(a));
    FakeEventSource.instances[0].emitMessage();
    await vi.waitFor(
      () => expect(seen.some((a) => a.events.length > 0)).toBe(true),
      { timeout: 3000 },
    );
    stop();
  });
});

describe("App refresh flow", () => {
  it("shows 429 try-again-shortly copy", () => {
    renderMindmap(
      <MindmapView
        activity={baseActivity}
        refreshRateLimitMessage="Refresh rate limited — try again in 5s."
      />,
    );
    expect(screen.getByText(/try again in 5s/i)).toBeInTheDocument();
  });

  it("shows 403 refresh error", () => {
    renderMindmap(
      <MindmapView
        activity={baseActivity}
        refreshForbiddenMessage="Refresh denied (403) — check Host/Origin."
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(/403/);
  });

  it("Retry button wires onRefresh from banner", async () => {
    const onRefresh = vi.fn();
    const unhealthy = {
      ...baseActivity,
      meta: { github: "error", ledger: "ok" },
    };
    renderMindmap(
      <MindmapView
        activity={unhealthy as unknown as Activity}
        onRefresh={onRefresh}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(onRefresh).toHaveBeenCalled();
    expect(refreshRateLimitMessage(5)).toMatch(/5/);
  });
});
