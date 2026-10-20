import type { Event, Verdict } from "@shared/types";

export interface EventGlyph {
  symbol: string;
  label: string;
  title: string;
  fill: string;
}

function verdictLabel(verdict: Verdict | null | undefined): string {
  if (verdict === "PASS") return "PASS";
  if (verdict === "FAIL") return "FAIL";
  if (verdict === "CHANGES") return "CHG";
  return "VER";
}

export function glyphForEvent(event: Event): EventGlyph {
  const baseTitle = `${event.type}${event.task_id ? ` · ${event.task_id}` : ""}`;
  switch (event.type) {
    case "handoff":
    case "assigned":
      return {
        symbol: "⇄",
        label: "HO",
        title: `Handoff ${baseTitle}`,
        fill: "var(--edge-handoff)",
      };
    case "pr_opened":
      return {
        symbol: "PR",
        label: "PR+",
        title: `PR opened ${baseTitle}`,
        fill: "var(--edge-pr)",
      };
    case "pr_updated":
      return {
        symbol: "PR",
        label: "PR~",
        title: `PR updated ${baseTitle}`,
        fill: "var(--edge-pr)",
      };
    case "verdict":
      return {
        symbol: "✓",
        label: verdictLabel(event.verdict),
        title: `Verdict ${event.verdict ?? ""} ${baseTitle}`,
        fill: "var(--edge-verdict)",
      };
    case "merged":
      return {
        symbol: "M",
        label: "MRG",
        title: `Merged ${baseTitle}`,
        fill: "var(--edge-merge)",
      };
    case "blocker":
      return {
        symbol: "!",
        label: "BLK",
        title: `Blocker ${baseTitle}`,
        fill: "var(--status-blocked-bg)",
      };
    case "ci":
      return {
        symbol: "CI",
        label: "CI",
        title: `CI ${baseTitle}`,
        fill: "var(--accent)",
      };
    case "note":
      return {
        symbol: "·",
        label: "NOTE",
        title: `Note ${baseTitle}`,
        fill: "var(--text-muted)",
      };
    case "unparsed":
      return {
        symbol: "?",
        label: "RAW",
        title: `Unparsed ${baseTitle}`,
        fill: "var(--status-unknown-bg)",
      };
  }
}
