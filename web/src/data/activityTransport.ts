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
  /** SEC-MM020e-4: minimum ms between SSE-triggered activity refetches. */
  refetchMinMs?: number;
  /** QA-MM020e-3: initial backoff before retrying EventSource while polling. */
  sseRetryInitialMs?: number;
  sseRetryMaxMs?: number;
  /** MM-020-P0: true only after EventSource onopen; false when disconnected. */
  onSseConnectionChange?: (connected: boolean) => void;
  /** Fired on each SSE message (before debounced activity refetch). */
  onSseEvent?: () => void;
}

const DEFAULT_POLL_MS = 10_000;
export const SSE_REFETCH_MIN_MS = 1000;
const DEFAULT_SSE_RETRY_INITIAL_MS = 1000;
const DEFAULT_SSE_RETRY_MAX_MS = 30_000;

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

function createDebouncedRefetch(
  refetch: () => void,
  minIntervalMs: number,
): () => void {
  let lastRun = 0;
  let pending = false;

  return () => {
    const now = Date.now();
    const elapsed = now - lastRun;
    if (elapsed >= minIntervalMs) {
      lastRun = now;
      refetch();
      return;
    }
    if (pending) return;
    pending = true;
    const wait = minIntervalMs - elapsed;
    setTimeout(() => {
      pending = false;
      lastRun = Date.now();
      refetch();
    }, wait);
  };
}

/**
 * QA-MM020d-3: prefer SSE on `/events` (browser handles Last-Event-ID).
 * QA-MM020e-3: while on poll fallback, retry EventSource with backoff.
 * SEC-MM020e-4: debounce SSE-triggered refetches (~1/s).
 */
export function createSseTransport(
  options: SseTransportOptions = {},
): ActivityTransport {
  const activityUrl = options.activityUrl ?? "/activity.json";
  const eventsUrl = options.eventsUrl ?? "/events";
  const intervalMs = options.intervalMs ?? DEFAULT_POLL_MS;
  const fetchImpl = options.fetchImpl ?? fetch;
  const refetchMinMs = options.refetchMinMs ?? SSE_REFETCH_MIN_MS;
  const sseRetryInitialMs =
    options.sseRetryInitialMs ?? DEFAULT_SSE_RETRY_INITIAL_MS;
  const sseRetryMaxMs = options.sseRetryMaxMs ?? DEFAULT_SSE_RETRY_MAX_MS;
  const onSseConnectionChange = options.onSseConnectionChange;
  const onSseEvent = options.onSseEvent;
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
      let pendingReconnect: EventSource | null = null;
      let pollStop: (() => void) | null = null;
      let fellBack = false;
      let sseRetryTimer: ReturnType<typeof setTimeout> | undefined;
      let sseBackoffMs = sseRetryInitialMs;

      const refetch = () => {
        void loadActivity(activityUrl, fetchImpl)
          .then((data) => {
            if (!cancelled) onData(data);
          })
          .catch(() => {
            /* keep last good snapshot */
          });
      };

      const debouncedRefetch = createDebouncedRefetch(refetch, refetchMinMs);

      const clearSseRetry = () => {
        if (sseRetryTimer) {
          clearTimeout(sseRetryTimer);
          sseRetryTimer = undefined;
        }
      };

      const closePendingReconnect = () => {
        if (pendingReconnect) {
          pendingReconnect.close();
          pendingReconnect = null;
        }
      };

      const dispose = () => {
        cancelled = true;
        clearSseRetry();
        closePendingReconnect();
        if (source) {
          source.close();
          source = null;
        }
        pollStop?.();
        pollStop = null;
      };

      const startPollFallback = () => {
        if (cancelled || fellBack) return;
        fellBack = true;
        onSseConnectionChange?.(false);
        if (source) {
          source.close();
          source = null;
        }
        pollStop = poll.subscribe!(onData);
        scheduleSseRetry();
      };

      const scheduleSseRetry = () => {
        if (cancelled || !fellBack) return;
        clearSseRetry();
        const delay = sseBackoffMs;
        sseRetryTimer = setTimeout(() => {
          if (cancelled || !fellBack) return;
          tryReconnectSse();
          sseBackoffMs = Math.min(sseBackoffMs * 2, sseRetryMaxMs);
        }, delay);
      };

      const wireSource = (es: EventSource) => {
        es.onmessage = () => {
          if (cancelled) return;
          onSseEvent?.();
          debouncedRefetch();
        };
        es.onerror = () => {
          if (cancelled) return;
          es.close();
          if (source === es) source = null;
          if (pendingReconnect === es) pendingReconnect = null;
          if (!fellBack) {
            startPollFallback();
          } else {
            scheduleSseRetry();
          }
        };
        if ("onopen" in es) {
          (es as EventSource & { onopen: (() => void) | null }).onopen = () => {
            if (cancelled) {
              es.close();
              if (pendingReconnect === es) pendingReconnect = null;
              return;
            }
            onSseConnectionChange?.(true);
            if (fellBack) {
              pollStop?.();
              pollStop = null;
              clearSseRetry();
              fellBack = false;
              sseBackoffMs = sseRetryInitialMs;
            }
            if (pendingReconnect === es) pendingReconnect = null;
            source = es;
          };
        }
      };

      const tryReconnectSse = () => {
        if (cancelled || !fellBack) return;
        closePendingReconnect();
        try {
          const next = new EventSourceImpl(eventsUrl);
          pendingReconnect = next;
          wireSource(next);
          if (!fellBack) {
            pendingReconnect = null;
            source = next;
          }
        } catch {
          scheduleSseRetry();
        }
      };

      try {
        source = new EventSourceImpl(eventsUrl);
        wireSource(source);
      } catch {
        startPollFallback();
        return dispose;
      }

      return dispose;
    },
  };
}

export { LedgerLoadError, DEFAULT_POLL_MS };
