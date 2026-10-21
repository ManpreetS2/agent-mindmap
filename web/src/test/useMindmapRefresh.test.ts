import { renderHook, act } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { useMindmapRefresh } from "../hooks/useMindmapRefresh";
import * as postRefreshModule from "../data/postRefresh";
import { REFRESH_FORBIDDEN_MESSAGE } from "../utils/viewState";
import { REFRESH_NETWORK_UNREACHABLE } from "../utils/refreshFlow";

describe("useMindmapRefresh / handleRefresh", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("queued refresh does not reload on a fixed timer", async () => {
    vi.spyOn(postRefreshModule, "postRefresh").mockResolvedValue({
      status: "queued",
    });
    const { result } = renderHook(() => useMindmapRefresh("key-1"));
    await act(async () => {
      await result.current.handleRefresh();
    });
    await act(async () => {
      vi.advanceTimersByTime(5_000);
    });
    expect(postRefreshModule.postRefresh).toHaveBeenCalledTimes(1);
    expect(result.current.refreshError).toBeNull();
  });

  it("429 sets countdown and blocks rapid retry", async () => {
    vi.spyOn(postRefreshModule, "postRefresh").mockResolvedValue({
      status: "rate_limited",
      retryAfterS: 3,
    });
    const { result } = renderHook(() => useMindmapRefresh("key-1"));
    await act(async () => {
      await result.current.handleRefresh();
    });
    expect(result.current.rateLimitSeconds).toBeGreaterThan(0);
    await act(async () => {
      await result.current.handleRefresh();
    });
    expect(postRefreshModule.postRefresh).toHaveBeenCalledTimes(1);
  });

  it("403 sets forbidden error message", async () => {
    vi.spyOn(postRefreshModule, "postRefresh").mockResolvedValue({
      status: "forbidden",
    });
    const { result } = renderHook(() => useMindmapRefresh("key-1"));
    await act(async () => {
      await result.current.handleRefresh();
    });
    expect(result.current.refreshError).toBe(REFRESH_FORBIDDEN_MESSAGE);
  });

  it("network error shows unreachable message", async () => {
    vi.spyOn(postRefreshModule, "postRefresh").mockResolvedValue({
      status: "error",
      httpStatus: 0,
    });
    const { result } = renderHook(() => useMindmapRefresh("key-1"));
    await act(async () => {
      await result.current.handleRefresh();
    });
    expect(result.current.refreshError).toBe(REFRESH_NETWORK_UNREACHABLE);
  });

  it("clears refresh errors on activity key change", async () => {
    vi.spyOn(postRefreshModule, "postRefresh").mockResolvedValue({
      status: "forbidden",
    });
    const { result, rerender } = renderHook(
      ({ key }) => useMindmapRefresh(key),
      { initialProps: { key: "a" } },
    );
    await act(async () => {
      await result.current.handleRefresh();
    });
    expect(result.current.refreshError).toBeTruthy();
    rerender({ key: "b" });
    expect(result.current.refreshError).toBeNull();
  });
});
