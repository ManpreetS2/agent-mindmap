import { useCallback, useEffect, useRef, useState } from "react";
import type { Activity } from "@shared/types";
import {
  createPollTransport,
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
  suppliedTransport?: ActivityTransport,
): ActivityFeedState {
  const defaultTransport = useRef<ActivityTransport>();
  if (!defaultTransport.current) defaultTransport.current = createPollTransport();
  const transport = suppliedTransport ?? defaultTransport.current;
  const [activity, setActivity] = useState<Activity | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [lastPatch, setLastPatch] = useState<ActivityPatch | null>(null);
  const [statusPulseNodeIds, setStatusPulseNodeIds] = useState<
    ReadonlySet<string>
  >(() => new Set());
  const [retryToken, setRetryToken] = useState(0);
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
  }, []);

  const reload = useCallback(() => {
    setError(null);
    setActivity(null);
    activityRef.current = null;
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
    if (!transport.subscribe) return;
    return transport.subscribe((data) => {
      applyNext(data);
    }, (failure) => {
      const last = activityRef.current;
      if (last?.meta.t3) {
        setActivity({ ...last, meta: { ...last.meta, t3: { ...last.meta.t3, connection: "unavailable" } },
          nodes: last.nodes.map(n => n.session ? { ...n, status: "STALE", session: { ...n.session, stale: true } } : n) });
      } else if (!last) setError(failure);
    });
  }, [transport, retryToken, applyNext]);

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

