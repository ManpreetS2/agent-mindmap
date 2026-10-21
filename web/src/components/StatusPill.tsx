import type { Status } from "@shared/types";

const STATUS_STYLES: Record<
  Status,
  { bg: string; fg: string; dashed?: boolean }
> = {
  IDLE: { bg: "var(--status-idle-bg)", fg: "var(--status-idle-fg)" },
  IN_PROGRESS: {
    bg: "var(--status-progress-bg)",
    fg: "var(--status-progress-fg)",
  },
  IN_REVIEW: { bg: "var(--status-review-bg)", fg: "var(--status-review-fg)" },
  BLOCKED: { bg: "var(--status-blocked-bg)", fg: "var(--status-blocked-fg)" },
  DONE: { bg: "var(--status-done-bg)", fg: "var(--status-done-fg)" },
  UNKNOWN: {
    bg: "var(--status-unknown-bg)",
    fg: "var(--status-unknown-fg)",
    dashed: true,
  },
};

interface StatusPillProps {
  status: Status;
}

function normalizeStatus(status: Status): Status {
  if (status in STATUS_STYLES) return status;
  return "UNKNOWN";
}

export function StatusPill({ status }: StatusPillProps) {
  const normalized = normalizeStatus(status);
  const style = STATUS_STYLES[normalized];
  return (
    <span
      className="status-pill"
      style={{
        background: style.bg,
        color: style.fg,
        border: style.dashed ? "1px dashed var(--text-muted)" : "1px solid transparent",
      }}
      aria-label={`Status ${normalized.replace("_", " ")}`}
    >
      {normalized.replace("_", " ")}
    </span>
  );
}
