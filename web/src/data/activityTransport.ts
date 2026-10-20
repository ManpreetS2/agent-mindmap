import type { Activity } from "@shared/types";
import { LedgerLoadError, loadActivity } from "./loadActivity";

/** Pluggable activity source for MM-010/011 (SSE/WebSocket later). */
export interface ActivityTransport {
  readonly kind: string;
  fetch(): Promise<Activity>;
  /** Optional continuous subscription; return unsubscribe. */
  subscribe?(onData: (activity: Activity) => void): () => void;
}

export interface PollTransportOptions {
  url?: string;
  /** Poll interval in ms (default 10s). */
  intervalMs?: number;
  fetchImpl?: typeof fetch;
}

const DEFAULT_POLL_MS = 10_000;

export function createPollTransport(
  options: PollTransportOptions = {},
): ActivityTransport {
  const url = options.url ?? "/activity.json";
  const intervalMs = options.intervalMs ?? DEFAULT_POLL_MS;
  const fetchImpl = options.fetchImpl ?? fetch;

  return {
    kind: "poll",
    fetch: () => loadActivity(url, fetchImpl),
    subscribe(onData) {
      let cancelled = false;
      let timer: ReturnType<typeof setInterval> | undefined;

      const tick = () => {
        void loadActivity(url, fetchImpl)
          .then((data) => {
            if (!cancelled) onData(data);
          })
          .catch(() => {
            /* keep last good snapshot; App handles initial errors */
          });
      };

      timer = setInterval(tick, intervalMs);
      return () => {
        cancelled = true;
        if (timer) clearInterval(timer);
      };
    },
  };
}

export { LedgerLoadError, DEFAULT_POLL_MS };
