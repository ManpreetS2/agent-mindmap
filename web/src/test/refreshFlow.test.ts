import { describe, expect, it } from "vitest";
import {
  REFRESH_NETWORK_UNREACHABLE,
  applyPostRefreshAction,
  buildMindmapStatusBar,
  postRefreshToAction,
  refreshErrorMessage,
} from "../utils/refreshFlow";
import { REFRESH_FORBIDDEN_MESSAGE } from "../utils/viewState";

describe("refreshFlow", () => {
  it("buildMindmapStatusBar prioritizes source, disconnect, refresh", () => {
    const bar = buildMindmapStatusBar({
      meta: {
        github: "error",
        ledger: "unavailable",
      } as unknown as import("@shared/types").ActivityMeta,
      sse: "disconnected",
      refreshError: REFRESH_NETWORK_UNREACHABLE,
      rateLimitSeconds: null,
    });
    expect(bar.segments.length).toBe(3);
    expect(bar.segments[0]).toMatch(/SOURCE UNAVAILABLE/);
    expect(bar.segments[1]).toMatch(/DISCONNECTED/);
    expect(bar.segments[2]).toMatch(/unreachable/);
    expect(bar.showRetry).toBe(true);
  });

  it("rate limit disables retry", () => {
    const bar = buildMindmapStatusBar({
      meta: { github: "ok" },
      sse: "connected",
      refreshError: null,
      rateLimitSeconds: 4,
    });
    expect(bar.retryDisabled).toBe(true);
    expect(bar.segments[0]).toMatch(/4s/);
  });

  it("postRefreshToAction maps network error", () => {
    const action = postRefreshToAction({ status: "error", httpStatus: 0 });
    expect(action).toEqual({
      type: "error",
      message: REFRESH_NETWORK_UNREACHABLE,
    });
  });

  it("applyPostRefreshAction queued schedules fallback only", () => {
    const applied = applyPostRefreshAction({ type: "queued" }, 1000);
    expect(applied.scheduleFallbackReload).toBe(true);
    expect(applied.refreshError).toBeNull();
  });

  it("applyPostRefreshAction forbidden sets message", () => {
    const applied = applyPostRefreshAction({ type: "forbidden" }, 1000);
    expect(applied.refreshError).toBe(REFRESH_FORBIDDEN_MESSAGE);
  });

  it("refreshErrorMessage for http status", () => {
    expect(refreshErrorMessage(502)).toMatch(/502/);
    expect(refreshErrorMessage(0)).toBe(REFRESH_NETWORK_UNREACHABLE);
  });
});
