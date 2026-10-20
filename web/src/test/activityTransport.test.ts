import { describe, expect, it, vi } from "vitest";
import {
  createPollTransport,
  createSseTransport,
} from "../data/activityTransport";
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

function mockFetch(): typeof fetch {
  return vi.fn(async () =>
    new Response(JSON.stringify(sample), {
      status: 200,
      headers: { "content-type": "application/json" },
    }),
  ) as unknown as typeof fetch;
}

/** Minimal EventSource stand-in for QA-MM020d-3 tests. */
class FakeEventSource {
  static instances: FakeEventSource[] = [];
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  readyState = 0;
  url: string;
  closed = false;

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  close() {
    this.closed = true;
    this.readyState = 2;
  }

  emitMessage() {
    this.onmessage?.(new MessageEvent("message", { data: "{}" }));
  }

  emitError() {
    this.onerror?.(new Event("error"));
  }
}

describe("createPollTransport", () => {
  it("exposes poll kind and fetches activity.json", async () => {
    const fetchImpl = mockFetch();
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
    const fetchImpl = mockFetch();
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

describe("createSseTransport (QA-MM020d-3)", () => {
  it("uses sse kind when EventSource is available", async () => {
    FakeEventSource.instances = [];
    const fetchImpl = mockFetch();
    const transport = createSseTransport({
      fetchImpl,
      EventSourceImpl: FakeEventSource as unknown as typeof EventSource,
    });
    expect(transport.kind).toBe("sse");
    const data = await transport.fetch();
    expect(data.project).toBe("fencepost");
  });

  it("refetches activity.json on SSE message", async () => {
    FakeEventSource.instances = [];
    const fetchImpl = mockFetch();
    const transport = createSseTransport({
      fetchImpl,
      EventSourceImpl: FakeEventSource as unknown as typeof EventSource,
    });
    const seen: Activity[] = [];
    const stop = transport.subscribe!((a) => seen.push(a));
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(FakeEventSource.instances[0].url).toBe("/events");

    FakeEventSource.instances[0].emitMessage();
    await vi.waitFor(() => expect(seen.length).toBe(1));
    expect(fetchImpl).toHaveBeenCalled();
    stop();
    expect(FakeEventSource.instances[0].closed).toBe(true);
  });

  it("falls back to poll when EventSource errors", async () => {
    vi.useFakeTimers();
    FakeEventSource.instances = [];
    const fetchImpl = mockFetch();
    const transport = createSseTransport({
      intervalMs: 100,
      fetchImpl,
      EventSourceImpl: FakeEventSource as unknown as typeof EventSource,
    });
    const seen: Activity[] = [];
    const stop = transport.subscribe!((a) => seen.push(a));

    FakeEventSource.instances[0].emitError();
    expect(FakeEventSource.instances[0].closed).toBe(true);

    await vi.advanceTimersByTimeAsync(250);
    stop();
    expect(seen.length).toBeGreaterThanOrEqual(2);
    vi.useRealTimers();
  });

  it("falls back to poll when EventSource is unsupported", async () => {
    vi.useFakeTimers();
    const fetchImpl = mockFetch();
    const transport = createSseTransport({
      intervalMs: 100,
      fetchImpl,
      EventSourceImpl: undefined,
    });
    expect(transport.kind).toBe("poll");
    const seen: Activity[] = [];
    const stop = transport.subscribe!((a) => seen.push(a));
    await vi.advanceTimersByTimeAsync(250);
    stop();
    expect(seen.length).toBeGreaterThanOrEqual(2);
    vi.useRealTimers();
  });
});
