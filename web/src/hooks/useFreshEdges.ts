import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { Activity } from "@shared/types";
import { FRESH_EDGE_MS, newlyObservedEdgeIds, sourceKey } from "../utils/edgeActivity";

/** A source-scoped observation history. Disappearing/reappearing edges never replay old evidence. */
export function useFreshEdges(activity: Activity): ReadonlySet<string> {
  const seen = useRef<Set<string> | null>(null);
  const evidence = useRef(new Set<string>());
  const key = useRef("");
  const [fresh, setFresh] = useState<ReadonlySet<string>>(() => new Set());
  const timers = useRef(new Set<number>());
  useEffect(() => () => {
    for (const t of timers.current) window.clearTimeout(t);
    timers.current.clear();
  }, []);
  useLayoutEffect(() => {
    const k = sourceKey(activity);
    const changed = key.current !== k;
    if (changed) {
      key.current = k;
      seen.current = null;
      evidence.current.clear();
      for (const t of timers.current) window.clearTimeout(t);
      timers.current.clear();
    }
    const added = newlyObservedEdgeIds(seen.current, activity);
    const events = new Set(activity.events.map(e => e.id));
    for (const e of activity.edges) {
      if (e.event_ids.some(id => evidence.current.has(id))) added.delete(e.id);
      for (const id of e.event_ids) if (events.has(id)) evidence.current.add(id);
    }
    seen.current = new Set([...(seen.current ?? []), ...activity.edges.map(e => e.id)]);
    const present = new Set(activity.edges.map(e => e.id));
    setFresh(prev => {
      const next = new Set([...(changed ? [] : [...prev].filter(id => present.has(id))), ...added]);
      return next.size === prev.size && [...next].every(id => prev.has(id)) ? prev : next;
    });
    if (!added.size) return;
    const t = window.setTimeout(() => {
      timers.current.delete(t);
      setFresh(prev => new Set([...prev].filter(id => !added.has(id))));
    }, FRESH_EDGE_MS);
    timers.current.add(t);
  }, [activity]);
  return fresh;
}
