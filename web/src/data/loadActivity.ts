import type { Activity } from "@shared/types";
import { LEDGER_ERROR_PATH } from "../utils/viewState";

const ACTIVITY_URL = "/activity.json";

export class LedgerLoadError extends Error {
  readonly path = LEDGER_ERROR_PATH;
  constructor() {
    super(`Can't read ${LEDGER_ERROR_PATH}`);
    this.name = "LedgerLoadError";
  }
}

function looksLikeHtml(text: string, contentType: string): boolean {
  if (contentType.includes("text/html")) return true;
  const head = text.trimStart().slice(0, 32).toLowerCase();
  return (
    head.startsWith("<!doctype") ||
    head.startsWith("<html") ||
    head.startsWith("<head")
  );
}

function isActivityShape(data: unknown): data is Activity {
  return (
    typeof data === "object" &&
    data !== null &&
    "schema_version" in data &&
    "nodes" in data &&
    "events" in data
  );
}

export async function loadActivity(
  url = ACTIVITY_URL,
  fetchImpl: typeof fetch = fetch,
): Promise<Activity> {
  const res = await fetchImpl(url);
  if (res.status === 404 || res.status === 422) {
    throw new LedgerLoadError();
  }
  if (!res.ok) {
    throw new Error(`Failed to load activity.json (${res.status})`);
  }

  const contentType = res.headers.get("content-type") ?? "";
  const text = await res.text();

  // Vite SPA fallback serves index.html with HTTP 200 for missing files
  // (QA-MM012-1). Treat HTML / invalid JSON as a ledger load failure.
  if (looksLikeHtml(text, contentType)) {
    throw new LedgerLoadError();
  }

  let data: unknown;
  try {
    data = JSON.parse(text) as unknown;
  } catch {
    throw new LedgerLoadError();
  }

  if (!isActivityShape(data)) {
    throw new LedgerLoadError();
  }

  return data;
}

/** Synchronous load for tests (bundled fixture). */
export function parseActivityJson(json: string): Activity {
  return JSON.parse(json) as Activity;
}
