import type { Activity, ActivityMeta } from "@shared/types";

/** MM-020-P0 web contract extensions (activity.json meta). */
export interface MindmapActivityMeta extends ActivityMeta {
  project?: string;
  ledger_error?: string;
}

export function asMindmapMeta(meta: ActivityMeta): MindmapActivityMeta {
  return meta as MindmapActivityMeta;
}

export function displayProject(activity: Activity): string {
  const project = asMindmapMeta(activity.meta).project?.trim();
  if (project) return project;
  return activity.project;
}

const LEDGER_OK = new Set(["ok", "demo", "skipped"]);

export function isLedgerSourceHealthy(ledger: string | undefined): boolean {
  if (ledger === undefined) return true;
  return LEDGER_OK.has(ledger);
}

export function isGithubSourceHealthy(github: string | undefined): boolean {
  if (github === undefined) return true;
  return github === "ok";
}
