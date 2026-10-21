import { describe, expect, it, vi } from "vitest";
import {
  SSE_REFETCH_MIN_MS,
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

/** Minimal EventSource stand-in for SSE transport tests. */
class FakeEventSource {
  static instances: FakeEventSource[] = [];
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  onopen: (() => void) | null = null;
  readyState = 0;
  url: string;
  closed = false;
  private listeners = new Map<string, Set<(ev: Event) => void>>();

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, handler: (ev: Event) => void) {
    const set = this.listeners.get(type) ?? new Set();
    set.add(handler);
    this.listeners.set(type, set);
  }

  emitActivity() {
    for (const handler of this.listeners.get("activity") ?? []) {
      handler(new Event("activity"));
    }
  }

  close() {
    this.closed = true;
    this.readyState = 2;
  }

  emitOpen() {
    this.onopen?.();
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

  it("error before onopen reports disconnected only", () => {
    FakeEventSource.instances = [];
    const connections: boolean[] = [];
    const transport = createSseTransport({
      fetchImpl: mockFetch(),
      EventSourceImpl: FakeEventSource as unknown as typeof EventSource,
      onSseConnectionChange: (c) => connections.push(c),
    });
    const stop = transport.subscribe!(() => undefined);
    FakeEventSource.instances[0].emitError();
    expect(connections).toEqual([false]);
    stop();
  });

  it("reports SSE disconnect on error and reconnect on recovery", async () => {
    vi.useFakeTimers();
    FakeEventSource.instances = [];
    const connections: boolean[] = [];
    const fetchImpl = mockFetch();
    const transport = createSseTransport({
      intervalMs: 100,
      sseRetryInitialMs: 200,
      fetchImpl,
      EventSourceImpl: FakeEventSource as unknown as typeof EventSource,
      onSseConnectionChange: (c) => connections.push(c),
    });
    const stop = transport.subscribe!(() => undefined);
    expect(connections).toEqual([]);
    FakeEventSource.instances[0].emitOpen();
    expect(connections).toContain(true);
    FakeEventSource.instances[0].emitError();
    expect(connections).toContain(false);
    await vi.advanceTimersByTimeAsync(250);
    const last = FakeEventSource.instances.at(-1);
    last?.emitOpen();
    expect(connections.filter(Boolean).length).toBeGreaterThanOrEqual(2);
    stop();
    vi.useRealTimers();
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

describe("activity snapshot events", () => {
  it("refetches when a named activity event arrives and onmessage does not", async () => {
    FakeEventSource.instances = [];
    const fetchImpl = mockFetch();
    const seen: Activity[] = [];
    const transport = createSseTransport({
      fetchImpl,
      refetchMinMs: 0,
      EventSourceImpl: FakeEventSource as unknown as typeof EventSource,
    });
    const stop = transport.subscribe!((data) => seen.push(data));
    FakeEventSource.instances[0].emitActivity();
    await vi.waitFor(() => expect(seen.length).toBeGreaterThan(0));
    expect(fetchImpl).toHaveBeenCalled();
    stop();
  });
});

describe("SEC-MM020e-4 debounce", () => {
  it("coalesces burst SSE messages to ~1 refetch per second", async () => {
    vi.useFakeTimers();
    FakeEventSource.instances = [];
    const fetchImpl = mockFetch();
    const transport = createSseTransport({
      fetchImpl,
      refetchMinMs: SSE_REFETCH_MIN_MS,
      EventSourceImpl: FakeEventSource as unknown as typeof EventSource,
    });
    const stop = transport.subscribe!(() => undefined);
    const es = FakeEventSource.instances[0];
    for (let i = 0; i < 120; i++) {
      es.emitMessage();
    }
    await vi.advanceTimersByTimeAsync(500);
    const callsAfterHalfSec = (fetchImpl as ReturnType<typeof vi.fn>).mock.calls
      .length;
    expect(callsAfterHalfSec).toBeLessThanOrEqual(2);
    await vi.advanceTimersByTimeAsync(2000);
    const totalCalls = (fetchImpl as ReturnType<typeof vi.fn>).mock.calls.length;
    expect(totalCalls).toBeGreaterThanOrEqual(2);
    expect(totalCalls).toBeLessThan(20);
    stop();
    vi.useRealTimers();
  });
});

describe("QA-MM020e-3 SSE recovery", () => {
  it("retries EventSource after poll fallback and resumes SSE", async () => {
    vi.useFakeTimers();
    FakeEventSource.instances = [];
    const fetchImpl = mockFetch();
    const transport = createSseTransport({
      intervalMs: 100,
      sseRetryInitialMs: 200,
      fetchImpl,
      EventSourceImpl: FakeEventSource as unknown as typeof EventSource,
    });
    const stop = transport.subscribe!(() => undefined);

    FakeEventSource.instances[0].emitError();
    await vi.advanceTimersByTimeAsync(250);
    expect(FakeEventSource.instances.length).toBeGreaterThanOrEqual(2);

    const retry = FakeEventSource.instances.at(-1)!;
    retry.emitOpen();
    retry.emitMessage();
    await vi.waitFor(() =>
      expect((fetchImpl as ReturnType<typeof vi.fn>).mock.calls.length).toBeGreaterThan(0),
    );

    await vi.advanceTimersByTimeAsync(500);
    stop();
    vi.useRealTimers();
  });
});

function openFakeEventSources(): FakeEventSource[] {
  return FakeEventSource.instances.filter((i) => !i.closed);
}

describe("QA-MM020e-7 unsubscribe cleanup", () => {
  it("closes initial EventSource on immediate unsubscribe", () => {
    FakeEventSource.instances = [];
    const transport = createSseTransport({
      fetchImpl: mockFetch(),
      EventSourceImpl: FakeEventSource as unknown as typeof EventSource,
    });
    const stop = transport.subscribe!(() => undefined);
    expect(openFakeEventSources()).toHaveLength(1);
    stop();
    expect(openFakeEventSources()).toHaveLength(0);
  });

  it("closes pending reconnect EventSource before onopen", async () => {
    vi.useFakeTimers();
    FakeEventSource.instances = [];
    const transport = createSseTransport({
      intervalMs: 100,
      sseRetryInitialMs: 200,
      fetchImpl: mockFetch(),
      EventSourceImpl: FakeEventSource as unknown as typeof EventSource,
    });
    const stop = transport.subscribe!(() => undefined);
    FakeEventSource.instances[0].emitError();
    await vi.advanceTimersByTimeAsync(250);
    expect(openFakeEventSources().length).toBeGreaterThanOrEqual(1);
    stop();
    expect(openFakeEventSources()).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(5000);
    expect(openFakeEventSources()).toHaveLength(0);
    vi.useRealTimers();
  });

  it("closes active source after poll fallback unsubscribe", async () => {
    vi.useFakeTimers();
    FakeEventSource.instances = [];
    const transport = createSseTransport({
      intervalMs: 100,
      sseRetryInitialMs: 500,
      fetchImpl: mockFetch(),
      EventSourceImpl: FakeEventSource as unknown as typeof EventSource,
    });
    const stop = transport.subscribe!(() => undefined);
    FakeEventSource.instances[0].emitError();
    await vi.advanceTimersByTimeAsync(150);
    stop();
    expect(openFakeEventSources()).toHaveLength(0);
    vi.useRealTimers();
  });
});
