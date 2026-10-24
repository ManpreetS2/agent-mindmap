import type { Observability } from "@shared/observability";
import { isObservabilityShape } from "../utils/observabilityEval";

export type ObservabilityFetchResult =
  | { kind: "ok"; data: Observability; etag: string | null }
  | { kind: "not_modified"; data: Observability; etag: string | null }
  | { kind: "absent" }
  | { kind: "rejected"; reason: string };

export interface ObservabilityTransport {
  readonly kind: string;
  fetch(): Promise<ObservabilityFetchResult>;
  subscribe?(
    onResult: (result: ObservabilityFetchResult) => void,
  ): () => void;
}

export interface ObservabilityPollOptions {
  url?: string;
  intervalMs?: number;
  fetchImpl?: typeof fetch;
}

const DEFAULT_POLL_MS = 10_000;
const TIMEOUT_MS = 15_000;

/**
 * Separate from activity.json transport. 404 / network failure => absent (dashboard
 * keeps working). Invalid JSON / schema-violating payload => rejected, never crash.
 */
export function createObservabilityPollTransport(
  options: ObservabilityPollOptions = {},
): ObservabilityTransport {
  const url = options.url ?? `${import.meta.env.BASE_URL}observability.json`;
  const intervalMs = Math.max(1000, options.intervalMs ?? DEFAULT_POLL_MS);
  const fetchImpl = options.fetchImpl ?? fetch;
  let etag: string | null = null;
  let last: Observability | null = null;
  let started = 0;
  let applied = 0;

  async function read(): Promise<ObservabilityFetchResult> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), TIMEOUT_MS);
    const seq = ++started;
    try {
      const res = await fetchImpl(url, {
        headers: etag ? { "If-None-Match": etag } : {},
        signal: controller.signal,
      });
      if (res.status === 304 && last) {
        return { kind: "not_modified", data: last, etag };
      }
      if (res.status === 404) return { kind: "absent" };
      if (!res.ok) {
        // Treat other HTTP failures like absent so activity-only dashboards still work.
        return { kind: "absent" };
      }
      let raw: unknown;
      try {
        raw = await res.json();
      } catch {
        return { kind: "rejected", reason: "Response is not valid JSON" };
      }
      if (!isObservabilityShape(raw)) {
        return {
          kind: "rejected",
          reason: "Payload does not match observability v1 shape",
        };
      }
      if (seq < applied && last) {
        return { kind: "ok", data: last, etag };
      }
      applied = seq;
      etag = res.headers?.get("ETag") ?? null;
      last = raw;
      return { kind: "ok", data: raw, etag };
    } catch {
      // Network / abort: absent, not a hard app error.
      return { kind: "absent" };
    } finally {
      clearTimeout(timeout);
    }
  }

  return {
    kind: "poll",
    fetch: read,
    subscribe(onResult) {
      let cancelled = false;
      let timer: ReturnType<typeof setTimeout>;
      async function tick() {
        const result = await read();
        if (!cancelled) onResult(result);
        if (!cancelled) {
          clearTimeout(timer);
          timer = setTimeout(tick, intervalMs);
        }
      }
      timer = setTimeout(tick, intervalMs);
      return () => {
        cancelled = true;
        clearTimeout(timer);
      };
    },
  };
}

export { DEFAULT_POLL_MS as OBSERVABILITY_POLL_MS };
