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

export async function loadActivity(url = ACTIVITY_URL): Promise<Activity> {
  const res = await fetch(url);
  if (res.status === 404 || res.status === 422) {
    throw new LedgerLoadError();
  }
  if (!res.ok) {
    throw new Error(`Failed to load activity.json (${res.status})`);
  }
  const data = (await res.json()) as Activity;
  return data;
}

/** Synchronous load for tests (bundled fixture). */
export function parseActivityJson(json: string): Activity {
  return JSON.parse(json) as Activity;
}
