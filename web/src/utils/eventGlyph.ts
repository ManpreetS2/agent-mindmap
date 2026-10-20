import type { Event, Verdict } from "@shared/types";

export interface EventGlyph {
  symbol: string;
  label: string;
  title: string;
  fill: string;
}

const KNOWN_VERDICT_LABELS: Record<string, string> = {
  PASS: "PASS",
  FAIL: "FAIL",
  CHANGES: "CHG",
  CONDITIONAL: "COND",
  BLOCKED: "BLK",
  INCONCLUSIVE: "INC",
};

/**
 * Map a verdict token to a short glyph label.
 * Unknown / future values fall back to "VER" so the UI never breaks
 * (Director: widened enum OK iff UI falls back cleanly).
 */
export function verdictLabel(verdict: Verdict | string | null | undefined): string {
  if (verdict == null || verdict === "") return "VER";
  const key = String(verdict).toUpperCase();
  return KNOWN_VERDICT_LABELS[key] ?? "VER";
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
        title: `Verdict ${event.verdict ?? "unknown"} ${baseTitle}`,
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
    case "message":
      return {
        symbol: "✉",
        label: "MSG",
        title: `Message ${baseTitle}`,
        fill: "var(--edge-handoff)",
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
