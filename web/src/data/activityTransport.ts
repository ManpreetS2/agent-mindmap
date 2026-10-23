import type { Activity } from "@shared/types";
import { LedgerLoadError } from "./loadActivity";

export interface ActivityTransport {
  readonly kind: string;
  fetch(): Promise<Activity>;
  subscribe?(onData: (activity: Activity) => void, onError?: (error: Error) => void): () => void;
}
export interface PollTransportOptions {
  url?: string;
  intervalMs?: number;
  fetchImpl?: typeof fetch;
}
const DEFAULT_POLL_MS = 10_000;

export function createPollTransport(options: PollTransportOptions = {}): ActivityTransport {
  const url = options.url ?? "/activity.json";
  const intervalMs = Math.max(1000, options.intervalMs ?? DEFAULT_POLL_MS);
  const fetchImpl = options.fetchImpl ?? fetch;
  let etag: string | null = null;
  let last: Activity | null = null;
  let fingerprint = "";
  function ageSessions(data: Activity): Activity {
    if (!data.meta.t3 || data.meta.t3.mode === "demo") return data;
    const now = Date.now();
    const maxAge = data.meta.t3.stale_after_sec * 1000;
    let changed = false;
    const nodes = data.nodes.map(node => {
      if (!node.session || node.session.stale || !["IN_PROGRESS", "BLOCKED"].includes(node.status)) return node;
      const ts = Date.parse(node.last_activity_ts ?? "");
      if (Number.isFinite(ts) && now - ts <= maxAge && ts - now <= 60_000) return node;
      changed = true;
      return { ...node, status: "STALE" as const, session: { ...node.session, stale: true } };
    });
    return changed ? { ...data, nodes } : data;
  }
  async function read(): Promise<Activity> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15_000);
    try {
      const res = await fetchImpl(url, { headers: etag ? { "If-None-Match": etag } : {}, signal: controller.signal });
      if (res.status === 304 && last) { last = ageSessions(last); return last; }
      if (res.status === 404 || res.status === 422) throw new LedgerLoadError();
      if (!res.ok) throw new Error(`Failed to load activity.json (${res.status})`);
      const data = await res.json() as Activity;
      const nextFingerprint = JSON.stringify(data);
      etag = res.headers?.get("ETag") ?? null;
      if (last && nextFingerprint === fingerprint) { last = ageSessions(last); return last; }
      fingerprint = nextFingerprint;
      last = ageSessions(data);
      return last;
    } finally { clearTimeout(timeout); }
  }
  return {
    kind: "poll",
    fetch: read,
    subscribe(onData, onError) {
      let cancelled = false;
      let timer: ReturnType<typeof setTimeout>;
      let delivered = last;
      let failed = false;
      async function tick() {
        try {
          const data = await read();
          if (!cancelled && (data !== delivered || failed)) onData(data);
          delivered = data;
          failed = false;
        } catch (error) {
          failed = true;
          if (!cancelled) onError?.(error instanceof Error ? error : new Error("Connection unavailable"));
        } finally {
          if (!cancelled) timer = setTimeout(tick, intervalMs);
        }
      }
      timer = setTimeout(tick, intervalMs);
      return () => { cancelled = true; clearTimeout(timer); };
    },
  };
}
export { LedgerLoadError, DEFAULT_POLL_MS };
