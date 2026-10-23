import { useEffect, useRef, useState } from "react";
import type { Activity } from "@shared/types";
import {
  FRESH_EDGE_MS,
  newlyObservedEdgeIds,
  sourceKey,
} from "../utils/edgeActivity";

/**
 * Ids of verified edges first observed in the latest snapshot, held for a few seconds.
 * The first snapshot (and any change of source or mode) only establishes a baseline.
 */
export function useFreshEdges(activity: Activity): ReadonlySet<string> {
  const seen = useRef<Set<string> | null>(null);
  const key = useRef<string>("");
  const [fresh, setFresh] = useState<ReadonlySet<string>>(() => new Set());
  const timers = useRef(new Set<number>());

  useEffect(() => {
    const live = timers.current;
    return () => {
      for (const t of live) window.clearTimeout(t);
      live.clear();
    };
  }, []);

  useEffect(() => {
    const k = sourceKey(activity);
    if (key.current !== k) {
      key.current = k;
      seen.current = null;
      setFresh(new Set());
    }
    const added = newlyObservedEdgeIds(seen.current, activity);
    seen.current = new Set(activity.edges.map((e) => e.id));
    if (added.size === 0) return;
    setFresh((prev) => new Set([...prev, ...added]));
    // Not cleared on the next snapshot: rapid replay polling must not extend the highlight.
    const t = window.setTimeout(() => {
      timers.current.delete(t);
      setFresh((prev) => {
        const next = new Set(prev);
        for (const id of added) next.delete(id);
        return next;
      });
    }, FRESH_EDGE_MS);
    timers.current.add(t);
  }, [activity]);

  return fresh;
}
