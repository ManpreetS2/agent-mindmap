import { useCallback, useEffect, useState } from "react";
import { postRefresh } from "../data/postRefresh";
import {
  applyPostRefreshAction,
  postRefreshToAction,
  rateLimitSecondsRemaining,
} from "../utils/refreshFlow";

/**
 * POST /refresh queues work on the server. The open page updates when the
 * named SSE ``activity`` event arrives, or on the poll fallback while the
 * stream is disconnected. No fixed delay.
 */
export function useMindmapRefresh(activityKey: string) {
  const [rateLimitUntilMs, setRateLimitUntilMs] = useState<number | null>(null);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const [nowMs, setNowMs] = useState(() => Date.now());

  useEffect(() => {
    setRefreshError(null);
    setRateLimitUntilMs(null);
  }, [activityKey]);

  useEffect(() => {
    if (rateLimitUntilMs == null) return;
    const tick = () => setNowMs(Date.now());
    const id = window.setInterval(tick, 250);
    return () => window.clearInterval(id);
  }, [rateLimitUntilMs]);

  const handleRefresh = useCallback(async () => {
    const left = rateLimitSecondsRemaining(rateLimitUntilMs, Date.now());
    if (left != null && left > 0) return;

    setRefreshError(null);
    const result = await postRefresh();
    const action = postRefreshToAction(result);
    const applied = applyPostRefreshAction(action, Date.now());
    setRateLimitUntilMs(applied.rateLimitUntilMs);
    setRefreshError(applied.refreshError);
  }, [rateLimitUntilMs]);

  const rateLimitSeconds = rateLimitSecondsRemaining(
    rateLimitUntilMs,
    nowMs,
  );

  return {
    handleRefresh,
    refreshError,
    rateLimitSeconds,
  };
}
