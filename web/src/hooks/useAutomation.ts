import { useEffect, useRef, useState } from "react";
import type { Automation } from "@shared/automation";
import {
  createAutomationPollTransport,
  type AutomationFetchResult,
  type AutomationTransport,
} from "../data/automationTransport";

export type AutomationState =
  | { status: "loading" }
  | { status: "absent" }
  | { status: "rejected"; reason: string }
  | { status: "ok"; data: Automation };

/** Polls automation.json separately from activity.json. Never throws into the app. */
export function useAutomation(supplied?: AutomationTransport): AutomationState {
  const fallback = useRef<AutomationTransport>();
  if (!supplied && !fallback.current) fallback.current = createAutomationPollTransport();
  const transport = supplied ?? fallback.current!;
  const [state, setState] = useState<AutomationState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    const apply = (r: AutomationFetchResult) => {
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
