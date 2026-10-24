import { useEffect, useRef, useState } from "react";
import type { Observability } from "@shared/observability";
import {
  createObservabilityPollTransport,
  type ObservabilityFetchResult,
  type ObservabilityTransport,
} from "../data/observabilityTransport";

export type ObservabilityState =
  | { status: "loading" }
  | { status: "absent" }
  | { status: "rejected"; reason: string }
  | { status: "ok"; data: Observability };

/** Polls observability.json separately from activity.json. Never throws into the app. */
export function useObservability(
  supplied?: ObservabilityTransport,
): ObservabilityState {
  const fallback = useRef<ObservabilityTransport>();
  if (!supplied && !fallback.current) {
    fallback.current = createObservabilityPollTransport();
  }
  const transport = supplied ?? fallback.current!;
  const [state, setState] = useState<ObservabilityState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    const apply = (r: ObservabilityFetchResult) => {
      if (cancelled) return;
      if (r.kind === "absent") setState({ status: "absent" });
      else if (r.kind === "rejected") setState({ status: "rejected", reason: r.reason });
      else setState({ status: "ok", data: r.data });
    };
    transport.fetch().then(apply, () => apply({ kind: "absent" }));
    const unsubscribe = transport.subscribe?.(apply);
    return () => {
      cancelled = true;
      unsubscribe?.();
    };
  }, [transport]);

  return state;
}
