import { useCallback, useEffect, useRef, useState } from "react";
import { postRefresh } from "../data/postRefresh";
import {
  REFRESH_FALLBACK_MS,
  applyPostRefreshAction,
  postRefreshToAction,
  rateLimitSecondsRemaining,
} from "../utils/refreshFlow";

export function useMindmapRefresh(reload: () => void, activityKey: string) {
  const [rateLimitUntilMs, setRateLimitUntilMs] = useState<number | null>(null);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const fallbackTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const cancelFallbackReload = useCallback(() => {
    if (fallbackTimerRef.current) {
      clearTimeout(fallbackTimerRef.current);
      fallbackTimerRef.current = null;
    }
  }, []);

  const scheduleFallbackReload = useCallback(() => {
    cancelFallbackReload();
    fallbackTimerRef.current = setTimeout(() => {
      fallbackTimerRef.current = null;
      reload();
    }, REFRESH_FALLBACK_MS);
  }, [cancelFallbackReload, reload]);

  const onSsePush = useCallback(() => {
    cancelFallbackReload();
  }, [cancelFallbackReload]);

  useEffect(() => {
    setRefreshError(null);
    setRateLimitUntilMs(null);
    cancelFallbackReload();
  }, [activityKey, cancelFallbackReload]);

  useEffect(() => {
    if (rateLimitUntilMs == null) return;
    const tick = () => setNowMs(Date.now());
    const id = window.setInterval(tick, 250);
    return () => window.clearInterval(id);
  }, [rateLimitUntilMs]);

  useEffect(
    () => () => {
      cancelFallbackReload();
    },
    [cancelFallbackReload],
  );

  const handleRefresh = useCallback(async () => {
    const left = rateLimitSecondsRemaining(rateLimitUntilMs, Date.now());
    if (left != null && left > 0) return;

    setRefreshError(null);
    const result = await postRefresh();
    const action = postRefreshToAction(result);
    const applied = applyPostRefreshAction(action, Date.now());
    setRateLimitUntilMs(applied.rateLimitUntilMs);
    setRefreshError(applied.refreshError);
    if (applied.scheduleFallbackReload) {
      scheduleFallbackReload();
    }
  }, [rateLimitUntilMs, scheduleFallbackReload]);

  const rateLimitSeconds = rateLimitSecondsRemaining(
    rateLimitUntilMs,
    nowMs,
  );

  return {
    handleRefresh,
    onSsePush,
    refreshError,
    rateLimitSeconds,
  };
}
