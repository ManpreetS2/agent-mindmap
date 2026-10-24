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
      new Response(JSON.stringify(sample), { status: 200 }),
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

  it("subscribe polls without duplicate delivery", async () => {
    vi.useFakeTimers();
    const fetchImpl = vi.fn(async () =>
      new Response(JSON.stringify(sample), { status: 200 }),
    ) as unknown as typeof fetch;
    const transport = createPollTransport({
      intervalMs: 100,
      fetchImpl,
    });
    const seen: Activity[] = [];
    const stop = transport.subscribe!((a) => seen.push(a));
    await vi.advanceTimersByTimeAsync(2500);
    stop();
    expect(seen.length).toBe(1);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    vi.useRealTimers();
  });

  describe("overlapping requests", () => {
    function deferred() {
      let resolve!: (r: Response) => void;
      const promise = new Promise<Response>(r => { resolve = r; });
      return { promise, resolve };
    }
    const at = (generated_at: string): Activity => ({ ...sample, generated_at });
    const ok = (body: Activity, etag: string) =>
      new Response(JSON.stringify(body), { status: 200, headers: { ETag: etag } });

    it("discards an older 200 that resolves after a newer one", async () => {
      const first = deferred();
      const second = deferred();
      const headers: Array<HeadersInit | undefined> = [];
      const queue = [first, second];
      const fetchImpl = vi.fn(async (_url: unknown, init?: RequestInit) => {
        headers.push(init?.headers);
        return (queue.shift() as ReturnType<typeof deferred>).promise;
      }) as unknown as typeof fetch;
      const transport = createPollTransport({ fetchImpl });
      const a = transport.fetch();
      const b = transport.fetch();
      second.resolve(ok(at("2026-10-20T05:00:00-07:00"), '"new"'));
      expect((await b).generated_at).toBe("2026-10-20T05:00:00-07:00");
      first.resolve(ok(at("2026-10-20T04:00:00-07:00"), '"old"'));
      expect((await a).generated_at).toBe("2026-10-20T05:00:00-07:00");
      const third = transport.fetch();
      void third.catch(() => undefined);
      expect(headers[2]).toEqual({ "If-None-Match": '"new"' });
    });

    it("ignores a stale 304 after a newer 200 and keeps the newer ETag", async () => {
      const first = deferred();
      const second = deferred();
      const queue = [first, second];
      const seen: Array<HeadersInit | undefined> = [];
      const fetchImpl = vi.fn(async (_url: unknown, init?: RequestInit) => {
        seen.push(init?.headers);
        return (queue.shift() as ReturnType<typeof deferred>).promise;
      }) as unknown as typeof fetch;
      const transport = createPollTransport({ fetchImpl });
      // Prime with a seed response, then race a 304 (older) against a 200 (newer).
      const prime = deferred();
      queue.unshift(prime);
      const p = transport.fetch();
      prime.resolve(ok(at("2026-10-20T03:00:00-07:00"), '"seed"'));
      await p;
      const older = transport.fetch();
      const newer = transport.fetch();
      second.resolve(ok(at("2026-10-20T06:00:00-07:00"), '"newer"'));
      await newer;
      first.resolve(new Response(null, { status: 304 }));
      expect((await older).generated_at).toBe("2026-10-20T06:00:00-07:00");
      const next = transport.fetch();
      void next.catch(() => undefined);
      expect(seen[seen.length - 1]).toEqual({ "If-None-Match": '"newer"' });
    });

    it("a 304 that resolves first does not suppress a newer 200 still in flight", async () => {
      const prime = deferred();
      const first = deferred();
      const second = deferred();
      const queue = [prime, first, second];
      const fetchImpl = vi.fn(async () => (queue.shift() as ReturnType<typeof deferred>).promise) as unknown as typeof fetch;
      const transport = createPollTransport({ fetchImpl });
      const p = transport.fetch();
      prime.resolve(ok(at("2026-10-20T03:00:00-07:00"), '"A"'));
      await p;
      const r1 = transport.fetch();
      const r2 = transport.fetch();
      second.resolve(new Response(null, { status: 304 }));
      await r2;
      first.resolve(ok(at("2026-10-20T07:00:00-07:00"), '"B"'));
      expect((await r1).generated_at).toBe("2026-10-20T07:00:00-07:00");
    });
  });
});
