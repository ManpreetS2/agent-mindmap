import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Activity } from "@shared/types";
import { useActivityFeed } from "../hooks/useActivityFeed";
import type { ActivityTransport } from "../data/activityTransport";

const sample = {
  schema_version: "1.1.0",
  generated_at: "2026-10-20T12:00:00Z",
  project: "agent-mindmap",
  meta: { github: "ok", ledger: "ok" },
  nodes: [],
  tasks: [],
  events: [],
  edges: [],
  unparsed: [],
} as Activity;

describe("useActivityFeed", () => {
  it("keeps the current snapshot mounted while a reload is in flight", async () => {
    let releaseSecond: (value: Activity) => void = () => undefined;
    const second = new Promise<Activity>((resolve) => {
      releaseSecond = resolve;
    });
    let calls = 0;
    const transport: ActivityTransport = {
      kind: "poll",
      fetch: () => {
        calls += 1;
        if (calls === 1) return Promise.resolve(sample);
        return second;
      },
      subscribe: () => () => undefined,
    };
    const { result } = renderHook(() => useActivityFeed(transport));
    await waitFor(() => expect(result.current.activity?.generated_at).toBe(sample.generated_at));
    result.current.reload();
    expect(result.current.activity?.generated_at).toBe(sample.generated_at);
    releaseSecond({ ...sample, generated_at: "2026-10-20T12:00:05Z" });
    await waitFor(() =>
      expect(result.current.activity?.generated_at).toBe("2026-10-20T12:00:05Z"),
    );
  });

  it("subscribes even when the first fetch fails", async () => {
    const subscribe = vi.fn(() => () => undefined);
    const transport: ActivityTransport = {
      kind: "sse",
      fetch: () => Promise.reject(new Error("offline")),
      subscribe,
    };
    const { result } = renderHook(() => useActivityFeed(transport));
    await waitFor(() => expect(subscribe).toHaveBeenCalled());
    await waitFor(() => expect(result.current.error?.message).toBe("offline"));
    expect(result.current.activity).toBeNull();
  });
});
