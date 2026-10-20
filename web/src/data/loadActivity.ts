import type { Activity } from "@shared/types";

const ACTIVITY_URL = "/activity.json";

export async function loadActivity(url = ACTIVITY_URL): Promise<Activity> {
  const res = await fetch(url);
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
