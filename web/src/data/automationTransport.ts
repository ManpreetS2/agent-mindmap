import type { Automation } from "@shared/automation";
import { isAutomationShape, sanitizeAutomation } from "../utils/automationEval";

export type AutomationFetchResult =
  | { kind: "ok"; data: Automation }
  | { kind: "absent" }
  | { kind: "rejected"; reason: string };

export interface AutomationTransport {
  readonly kind: string;
  fetch(): Promise<AutomationFetchResult>;
  subscribe?(onResult: (result: AutomationFetchResult) => void): () => void;
}

export interface AutomationPollOptions {
  url?: string;
  intervalMs?: number;
  fetchImpl?: typeof fetch;
}

export const AUTOMATION_POLL_MS = 10_000;
const TIMEOUT_MS = 15_000;

/**
 * Separate from activity.json and observability.json. 404 / network failure => absent (the dashboard
 * keeps working and says taskbot activity is not connected). Off-contract payload => rejected.
 */
export function createAutomationPollTransport(options: AutomationPollOptions = {}): AutomationTransport {
  const url = options.url ?? `${import.meta.env.BASE_URL}automation.json`;
  const intervalMs = Math.max(1000, options.intervalMs ?? AUTOMATION_POLL_MS);
  const fetchImpl = options.fetchImpl ?? fetch;
  let started = 0;
  let applied = 0;
  let last: Automation | null = null;

  async function read(): Promise<AutomationFetchResult> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), TIMEOUT_MS);
    const seq = ++started;
    try {
      const res = await fetchImpl(url, { signal: controller.signal, cache: "no-store" });
      if (!res.ok) return { kind: "absent" };
      let raw: unknown;
      try {
        raw = await res.json();
      } catch {
        return { kind: "rejected", reason: "Response is not valid JSON" };
      }
      if (!isAutomationShape(raw)) {
        return { kind: "rejected", reason: "Payload does not match automation v1 shape" };
      }
      const data = sanitizeAutomation(raw);
      if (seq < applied && last) return { kind: "ok", data: last };
      applied = seq;
      last = data;
      return { kind: "ok", data };
    } catch {
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
