import { describe, expect, it, vi } from "vitest";
import { FIXTURE_NAMES, loadFixture } from "./obsFixtures";
import { createObservabilityPollTransport } from "../data/observabilityTransport";

function resp(status: number, body?: unknown, headers: Record<string, string> = {}, raw?: string) {
  return {
    status,
    ok: status >= 200 && status < 300,
    headers: { get: (k: string) => headers[k] ?? null },
    json: async () => {
      if (raw !== undefined) return JSON.parse(raw);
      return body;
    },
  } as unknown as Response;
}

describe("observability transport", () => {
  it("accepts all five fixtures", async () => {
    for (const n of FIXTURE_NAMES) {
      const t = createObservabilityPollTransport({
        fetchImpl: vi.fn().mockResolvedValue(resp(200, loadFixture(n))),
      });
      expect((await t.fetch()).kind).toBe("ok");
    }
  });
  it("404 => absent", async () => {
    const t = createObservabilityPollTransport({ fetchImpl: vi.fn().mockResolvedValue(resp(404)) });
    expect(await t.fetch()).toEqual({ kind: "absent" });
  });
  it("network error => absent", async () => {
    const t = createObservabilityPollTransport({ fetchImpl: vi.fn().mockRejectedValue(new Error("x")) });
    expect(await t.fetch()).toEqual({ kind: "absent" });
  });
  it("bad JSON => rejected", async () => {
    const t = createObservabilityPollTransport({
      fetchImpl: vi.fn().mockResolvedValue(resp(200, null, {}, "{nope")),
    });
    expect((await t.fetch()).kind).toBe("rejected");
  });
  it("schema-invalid => rejected", async () => {
    const t = createObservabilityPollTransport({
      fetchImpl: vi.fn().mockResolvedValue(resp(200, { schema: "other" })),
    });
    expect((await t.fetch()).kind).toBe("rejected");
  });
  it("sends If-None-Match and reuses data on 304", async () => {
    const f = vi
      .fn()
      .mockResolvedValueOnce(resp(200, loadFixture("demo"), { ETag: '"a"' }))
      .mockResolvedValueOnce(resp(304));
    const t = createObservabilityPollTransport({ fetchImpl: f });
    await t.fetch();
    const r = await t.fetch();
    expect(r.kind).toBe("not_modified");
    expect((f.mock.calls[1][1] as RequestInit).headers).toEqual({ "If-None-Match": '"a"' });
  });
});
