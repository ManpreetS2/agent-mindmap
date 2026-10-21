import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Activity } from "@shared/types";
import { createSseTransport } from "../data/activityTransport";
import { MindmapView } from "../views/MindmapView";
import { StatusPill } from "../components/StatusPill";
import { displayProject } from "../utils/activityMeta";
import { sourceUnavailableMessage } from "../utils/viewState";
import { renderMindmap } from "./renderMindmap";
import {
  buildMindmapStatusBar,
  DISCONNECTED_SEGMENT,
} from "../utils/refreshFlow";
import { REFRESH_FORBIDDEN_MESSAGE } from "../utils/viewState";

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
  addEventListener() {}
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

describe("MM-020-P0 web contract", () => {
  it("source unavailable includes ledger_error and unhealthy github", () => {
    const msg = sourceUnavailableMessage({
      github: "never_run",
      ledger: "unavailable",
      ledger_error: "ledger not found",
    } as unknown as Activity["meta"]);
    expect(msg).toMatch(/SOURCE UNAVAILABLE/i);
    expect(msg).toMatch(/ledger not found/);
  });

  it("missing meta ledger/github does not show source unavailable", () => {
    expect(sourceUnavailableMessage({ github: "ok" })).toBeNull();
    expect(sourceUnavailableMessage({} as Activity["meta"])).toBeNull();
  });

  it("header uses meta.project when present", () => {
    const activity = {
      ...baseActivity,
      meta: { ...baseActivity.meta, project: "agent-mindmap" },
    } as Activity;
    expect(displayProject(activity)).toBe("agent-mindmap");
    renderMindmap(<MindmapView activity={activity} />);
    expect(screen.getByText(/Project: agent-mindmap/)).toBeInTheDocument();
  });

  it("single status bar shows DISCONNECTED segment", () => {
    const statusBar = buildMindmapStatusBar({
      meta: baseActivity.meta,
      sse: "disconnected",
      refreshError: null,
      rateLimitSeconds: null,
    });
    renderMindmap(
      <MindmapView activity={baseActivity} statusBar={statusBar} />,
    );
    expect(screen.getByText(new RegExp(DISCONNECTED_SEGMENT))).toBeInTheDocument();
    expect(document.querySelectorAll(".mindmap-status-bar")).toHaveLength(1);
  });

  it("UNKNOWN status pill is visually distinct from IDLE", () => {
    const { container: idle } = render(<StatusPill status="IDLE" />);
    const { container: unknown } = render(<StatusPill status="UNKNOWN" />);
    const idlePill = idle.querySelector(".status-pill") as HTMLElement;
    const unknownPill = unknown.querySelector(".status-pill") as HTMLElement;
    expect(unknownPill.style.border).toContain("dashed");
    expect(idlePill.style.border).not.toContain("dashed");
  });
});

describe("SSE onSseEvent", () => {
  it("invokes onSseEvent before refetch on message", async () => {
    FakeEventSource.instances = [];
    const onSseEvent = vi.fn();
    const fetchImpl = vi.fn(
      async () =>
        new Response(JSON.stringify(baseActivity), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    );
    const transport = createSseTransport({
      fetchImpl: fetchImpl as typeof fetch,
      refetchMinMs: 10,
      EventSourceImpl: FakeEventSource as unknown as typeof EventSource,
      onSseEvent,
    });
    const stop = transport.subscribe!(() => undefined);
    FakeEventSource.instances[0].emitOpen();
    FakeEventSource.instances[0].emitMessage();
    await vi.waitFor(() => expect(onSseEvent).toHaveBeenCalled());
    stop();
  });
});

describe("Mindmap status bar refresh copy", () => {
  it("shows 429 in unified bar with disabled retry", () => {
    const statusBar = buildMindmapStatusBar({
      meta: baseActivity.meta,
      sse: "connected",
      refreshError: null,
      rateLimitSeconds: 5,
    });
    renderMindmap(
      <MindmapView
        activity={baseActivity}
        statusBar={statusBar}
        onRefresh={() => undefined}
      />,
    );
    expect(screen.getByText(/try again in 5s/i)).toBeInTheDocument();
    const bar = document.querySelector(".mindmap-status-bar");
    expect(bar?.querySelector("button")).toBeDisabled();
  });

  it("shows 403 in unified bar", () => {
    const statusBar = buildMindmapStatusBar({
      meta: baseActivity.meta,
      sse: "connected",
      refreshError: REFRESH_FORBIDDEN_MESSAGE,
      rateLimitSeconds: null,
    });
    renderMindmap(
      <MindmapView activity={baseActivity} statusBar={statusBar} />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(/403/);
  });

  it("Retry button wires onRefresh", async () => {
    const onRefresh = vi.fn();
    const unhealthy = {
      ...baseActivity,
      meta: { github: "error", ledger: "ok" },
    };
    const statusBar = buildMindmapStatusBar({
      meta: unhealthy.meta as Activity["meta"],
      sse: "connected",
      refreshError: null,
      rateLimitSeconds: null,
    });
    renderMindmap(
      <MindmapView
        activity={unhealthy as unknown as Activity}
        statusBar={statusBar}
        onRefresh={onRefresh}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(onRefresh).toHaveBeenCalled();
  });
});
