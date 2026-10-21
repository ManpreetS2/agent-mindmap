import { describe, expect, it, vi } from "vitest";
import { postRefresh } from "../data/postRefresh";

describe("postRefresh", () => {
  it("parses 202 queued", async () => {
    const fetchImpl = vi.fn(async () => new Response(null, { status: 202 }));
    expect(await postRefresh(fetchImpl as typeof fetch)).toEqual({
      status: "queued",
    });
  });

  it("parses 429 retry_after_s", async () => {
    const fetchImpl = vi.fn(
      async () =>
        new Response(JSON.stringify({ retry_after_s: 12 }), { status: 429 }),
    );
    expect(await postRefresh(fetchImpl as typeof fetch)).toEqual({
      status: "rate_limited",
      retryAfterS: 12,
    });
  });

  it("parses 403 forbidden", async () => {
    const fetchImpl = vi.fn(async () => new Response(null, { status: 403 }));
    expect(await postRefresh(fetchImpl as typeof fetch)).toEqual({
      status: "forbidden",
    });
  });

  it("returns httpStatus 0 on network failure", async () => {
    const fetchImpl = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    });
    expect(await postRefresh(fetchImpl as typeof fetch)).toEqual({
      status: "error",
      httpStatus: 0,
    });
  });
});
