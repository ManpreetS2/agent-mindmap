import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useServerMode } from "../hooks/useServerMode";

describe("useServerMode", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("maps explicit live and demo from healthz", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ mode: "demo" }),
      }),
    );
    const { result } = renderHook(() => useServerMode("/healthz"));
    await waitFor(() => expect(result.current.bannerState).toBe("demo"));
  });

  it("treats missing mode as unknown not live", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({}),
      }),
    );
    const { result } = renderHook(() => useServerMode("/healthz"));
    await waitFor(() => expect(result.current.bannerState).toBe("unknown"));
  });

  it("retries after fetch failure and recovers", async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new Error("network"))
      .mockResolvedValue({
        ok: true,
        json: async () => ({ mode: "live" }),
      });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useServerMode("/healthz"));
    await waitFor(() => expect(result.current.bannerState).toBe("unknown"));
    await waitFor(
      () => expect(result.current.bannerState).toBe("live"),
      { timeout: 3000 },
    );
    expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(2);
  });
});
