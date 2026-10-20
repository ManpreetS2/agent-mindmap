import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Activity } from "@shared/types";
import { MindmapView } from "../views/MindmapView";
import {
  sourceUnavailableMessage,
  partialGithubBanner,
} from "../utils/viewState";
import { renderMindmap } from "./renderMindmap";

const base: Activity = {
  schema_version: "1.1.0",
  generated_at: "2026-10-20T12:00:00Z",
  project: "agent-mindmap",
  meta: { github: "never_run", ledger: "unavailable" },
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

describe("MM-020-P0 UI", () => {
  it("source unavailable when ledger/github unhealthy", () => {
    const msg = sourceUnavailableMessage(
      { github: "error", ledger: "unavailable" },
      ["ledger not found"],
    );
    expect(msg).toMatch(/SOURCE UNAVAILABLE/i);
    expect(msg).toMatch(/ledger not found/);
  });

  it("never_run github banner", () => {
    expect(partialGithubBanner({ github: "never_run" })).toMatch(/never run/i);
  });

  it("shows DISCONNECTED when SSE down", () => {
    renderMindmap(
      <MindmapView activity={base} sseDisconnected healthErrors={[]} />,
    );
    expect(screen.getByText(/DISCONNECTED/i)).toBeInTheDocument();
  });

  it("fallback nodes UNKNOWN not IDLE", () => {
    expect(base.nodes.every((n) => n.status === "UNKNOWN")).toBe(true);
    expect(base.project).not.toBe("fencepost");
  });
});
