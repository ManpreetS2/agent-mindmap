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

export interface SseTransportOptions {
  activityUrl?: string;
  eventsUrl?: string;
  /** Poll interval used only after SSE fallback (default 10s). */
  intervalMs?: number;
  fetchImpl?: typeof fetch;
  /** Injected for tests; defaults to global EventSource when present. */
  EventSourceImpl?: typeof EventSource;
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

/**
 * QA-MM020d-3: prefer SSE on `/events` (browser handles Last-Event-ID).
 * On EventSource error / missing support, fall back to poll transport.
 */
export function createSseTransport(
  options: SseTransportOptions = {},
): ActivityTransport {
  const activityUrl = options.activityUrl ?? "/activity.json";
  const eventsUrl = options.eventsUrl ?? "/events";
  const intervalMs = options.intervalMs ?? DEFAULT_POLL_MS;
  const fetchImpl = options.fetchImpl ?? fetch;
  const EventSourceImpl =
    options.EventSourceImpl ??
    (typeof EventSource !== "undefined" ? EventSource : undefined);

  const poll = createPollTransport({
    url: activityUrl,
    intervalMs,
    fetchImpl,
  });

  return {
    kind: EventSourceImpl ? "sse" : "poll",
    fetch: () => loadActivity(activityUrl, fetchImpl),
    subscribe(onData) {
      if (!EventSourceImpl) {
        return poll.subscribe!(onData);
      }

      let cancelled = false;
      let source: EventSource | null = null;
      let pollStop: (() => void) | null = null;
      let fellBack = false;

      const refetch = () => {
        void loadActivity(activityUrl, fetchImpl)
          .then((data) => {
            if (!cancelled) onData(data);
          })
          .catch(() => {
            /* keep last good snapshot */
          });
      };

      const startPollFallback = () => {
        if (cancelled || fellBack) return;
        fellBack = true;
        if (source) {
          source.close();
          source = null;
        }
        pollStop = poll.subscribe!(onData);
      };

      try {
        source = new EventSourceImpl(eventsUrl);
      } catch {
        startPollFallback();
        return () => {
          cancelled = true;
          pollStop?.();
        };
      }

      source.onmessage = () => {
        if (cancelled || fellBack) return;
        refetch();
      };
      source.onerror = () => {
        startPollFallback();
      };

      return () => {
        cancelled = true;
        if (source) {
          source.close();
          source = null;
        }
        pollStop?.();
      };
    },
  };
}

export { LedgerLoadError, DEFAULT_POLL_MS };
