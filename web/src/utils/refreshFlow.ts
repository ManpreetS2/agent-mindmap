import type { PostRefreshResult } from "../data/postRefresh";
import type { ActivityMeta } from "@shared/types";
import {
  REFRESH_FORBIDDEN_MESSAGE,
  partialGithubBanner,
  refreshRateLimitMessage,
  sourceUnavailableMessage,
} from "./viewState";

export const REFRESH_FALLBACK_MS = 1500;

export const REFRESH_NETWORK_UNREACHABLE =
  "Refresh failed (server unreachable)";

export type SseConnectionState = "connecting" | "connected" | "disconnected";

export function refreshErrorMessage(httpStatus: number): string {
  if (httpStatus === 0) return REFRESH_NETWORK_UNREACHABLE;
  return `Refresh failed (${httpStatus}).`;
}

export const DISCONNECTED_SEGMENT =
  "DISCONNECTED — live event stream unavailable; using poll fallback.";

export interface MindmapStatusBarModel {
  segments: string[];
  retryDisabled: boolean;
  showRetry: boolean;
}

export function buildMindmapStatusBar(params: {
  meta: ActivityMeta;
  sse: SseConnectionState;
  refreshError: string | null;
  rateLimitSeconds: number | null;
}): MindmapStatusBarModel {
  const segments: string[] = [];
  const sourceUnavailable = sourceUnavailableMessage(params.meta);
  if (sourceUnavailable) {
    segments.push(sourceUnavailable);
  } else {
    const partial = partialGithubBanner(params.meta);
    if (partial) segments.push(partial);
  }
  if (params.sse === "disconnected") {
    segments.push(DISCONNECTED_SEGMENT);
  }
  if (params.rateLimitSeconds != null && params.rateLimitSeconds > 0) {
    segments.push(refreshRateLimitMessage(params.rateLimitSeconds));
  } else if (params.refreshError) {
    segments.push(params.refreshError);
  }
  const retryDisabled =
    params.rateLimitSeconds != null && params.rateLimitSeconds > 0;
  return {
    segments,
    retryDisabled,
    showRetry: segments.length > 0,
  };
}

export type PostRefreshAction =
  | { type: "queued" }
  | { type: "rate_limited"; retryAfterS: number }
  | { type: "forbidden" }
  | { type: "error"; message: string };

export function postRefreshToAction(result: PostRefreshResult): PostRefreshAction {
  if (result.status === "queued") return { type: "queued" };
  if (result.status === "rate_limited") {
    return { type: "rate_limited", retryAfterS: result.retryAfterS };
  }
  if (result.status === "forbidden") return { type: "forbidden" };
  return { type: "error", message: refreshErrorMessage(result.httpStatus) };
}

export function applyPostRefreshAction(
  action: PostRefreshAction,
  nowMs: number,
): {
  rateLimitUntilMs: number | null;
  refreshError: string | null;
  scheduleFallbackReload: boolean;
} {
  if (action.type === "queued") {
    return {
      rateLimitUntilMs: null,
      refreshError: null,
      scheduleFallbackReload: true,
    };
  }
  if (action.type === "rate_limited") {
    return {
      rateLimitUntilMs: nowMs + action.retryAfterS * 1000,
      refreshError: null,
      scheduleFallbackReload: false,
    };
  }
  if (action.type === "forbidden") {
    return {
      rateLimitUntilMs: null,
      refreshError: REFRESH_FORBIDDEN_MESSAGE,
      scheduleFallbackReload: false,
    };
  }
  return {
    rateLimitUntilMs: null,
    refreshError: action.message,
    scheduleFallbackReload: false,
  };
}

export function rateLimitSecondsRemaining(
  rateLimitUntilMs: number | null,
  nowMs: number,
): number | null {
  if (rateLimitUntilMs == null) return null;
  const left = Math.ceil((rateLimitUntilMs - nowMs) / 1000);
  return left > 0 ? left : null;
}
