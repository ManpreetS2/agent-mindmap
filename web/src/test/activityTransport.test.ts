import { describe, expect, it, vi } from "vitest";
import { createPollTransport } from "../data/activityTransport";
import type { Activity } from "@shared/types";

const sample: Activity = {
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

describe("createPollTransport", () => {
  it("exposes poll kind and fetches activity.json", async () => {
    const fetchImpl = vi.fn(async () =>
      new Response(JSON.stringify(sample), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    ) as unknown as typeof fetch;
    const transport = createPollTransport({
      intervalMs: 50,
      fetchImpl,
    });
    expect(transport.kind).toBe("poll");
    const data = await transport.fetch();
    expect(data.generated_at).toBe(sample.generated_at);
    expect(fetchImpl).toHaveBeenCalled();
  });

  it("subscribe polls on an interval", async () => {
    vi.useFakeTimers();
    const fetchImpl = vi.fn(async () =>
      new Response(JSON.stringify(sample), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    ) as unknown as typeof fetch;
    const transport = createPollTransport({
      intervalMs: 100,
      fetchImpl,
    });
    const seen: Activity[] = [];
    const stop = transport.subscribe!((a) => seen.push(a));
    await vi.advanceTimersByTimeAsync(250);
    stop();
    expect(seen.length).toBeGreaterThanOrEqual(2);
    vi.useRealTimers();
  });
});
