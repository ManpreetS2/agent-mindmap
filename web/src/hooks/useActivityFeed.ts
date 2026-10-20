import { useCallback, useEffect, useRef, useState } from "react";
import type { Activity } from "@shared/types";
import {
  createPollTransport,
  LedgerLoadError,
  type ActivityTransport,
} from "../data/activityTransport";
import {
  patchActivity,
  statusChangedNodeIds,
  type ActivityPatch,
} from "../utils/activityDiff";

export interface ActivityFeedState {
  activity: Activity | null;
  error: Error | null;
  lastPatch: ActivityPatch | null;
  statusPulseNodeIds: ReadonlySet<string>;
  reload: () => void;
}

export function useActivityFeed(
  transport: ActivityTransport = createPollTransport(),
): ActivityFeedState {
  const [activity, setActivity] = useState<Activity | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [lastPatch, setLastPatch] = useState<ActivityPatch | null>(null);
  const [statusPulseNodeIds, setStatusPulseNodeIds] = useState<
    ReadonlySet<string>
  >(() => new Set());
  const [retryToken, setRetryToken] = useState(0);
  const [liveReady, setLiveReady] = useState(false);
  const activityRef = useRef<Activity | null>(null);

  const applyNext = useCallback((next: Activity) => {
    const prev = activityRef.current;
    const patch = patchActivity(prev, next);
    const pulses = statusChangedNodeIds(prev, next);
    activityRef.current = patch.activity;
    setActivity(patch.activity);
    setLastPatch(patch);
    setStatusPulseNodeIds(pulses);
    setError(null);
    setLiveReady(true);
  }, []);

  const reload = useCallback(() => {
    setError(null);
    setActivity(null);
    activityRef.current = null;
    setLiveReady(false);
    setRetryToken((t) => t + 1);
  }, []);

  useEffect(() => {
    let cancelled = false;
    transport
      .fetch()
      .then((data) => {
        if (!cancelled) applyNext(data);
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setError(
            e instanceof Error ? e : new Error("Failed to load data"),
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [transport, retryToken, applyNext]);

  useEffect(() => {
    if (!transport.subscribe || !liveReady) return;
    if (error instanceof LedgerLoadError) return;
    return transport.subscribe((data) => {
      applyNext(data);
    });
  }, [transport, liveReady, error, applyNext]);

  useEffect(() => {
    if (statusPulseNodeIds.size === 0) return;
    const t = window.setTimeout(() => setStatusPulseNodeIds(new Set()), 1600);
    return () => window.clearTimeout(t);
  }, [statusPulseNodeIds]);

  return {
    activity,
    error,
    lastPatch,
    statusPulseNodeIds,
    reload,
  };
}
