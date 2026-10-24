import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { Activity } from "@shared/types";
import { FRESH_EDGE_MS, newlyObservedEdgeIds, sourceKey, edgeObservation, snapshotConnected, type EdgeObservation } from "../utils/edgeActivity";

/** A source-scoped observation history. Disappearing/reappearing edges never replay old evidence. */
export function useFreshEdges(activity: Activity): ReadonlyMap<string, EdgeObservation> {
  const previous = useRef<Activity | null>(null);
  const seen = useRef<Set<string> | null>(null);
  const evidence = useRef(new Set<string>());
  const key = useRef("");
  const [fresh, setFresh] = useState<ReadonlyMap<string, EdgeObservation>>(() => new Map());
  const timers = useRef(new Set<number>());
  useEffect(() => () => {
    for (const t of timers.current) window.clearTimeout(t);
    timers.current.clear();
  }, []);
  useLayoutEffect(() => {
    // Replay explicitly creates a new synthetic scenario each cycle. Reset only observation
    // history, not the graph model/camera/pins. Live data never gains a replay exemption.
    const replayCycle = activity.meta.t3?.mode === "demo" ? activity.meta.t3.replay?.cycle : undefined;
    const k = `${sourceKey(activity)}|${replayCycle ?? "live-history"}`;
    const changed = key.current !== k;
    if (changed) {
      key.current = k;
      seen.current = null;
      previous.current = null;
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
    const observations = new Map(activity.edges.filter(e => added.has(e.id))
      .map(e => [e.id, edgeObservation(e, activity, previous.current)] as const));
    setFresh(prev => {
      const next = new Map([...(changed || !snapshotConnected(activity) ? [] : [...prev].filter(([id]) => present.has(id))), ...observations]);
      return next.size === prev.size && [...next].every(([id, kind]) => prev.get(id) === kind) ? prev : next;
    });
    previous.current = activity;
    if (!added.size) return;
    const t = window.setTimeout(() => {
      timers.current.delete(t);
      setFresh(prev => new Map([...prev].filter(([id]) => !added.has(id))));
    }, FRESH_EDGE_MS);
    timers.current.add(t);
  }, [activity]);
  return fresh;
}
