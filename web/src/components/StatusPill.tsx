import type { Status } from "@shared/types";

const STATUS_STYLES: Record<
  Status,
  { bg: string; fg: string; dashed?: boolean }
> = {
  FAILED: { bg: "#491b24", fg: "#ffb5c0" },
  STALE: { bg: "var(--status-unknown-bg)", fg: "var(--status-unknown-fg)", dashed: true },
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

export function StatusPill({ status }: StatusPillProps) {
  const style = STATUS_STYLES[status];
  return (
    <span
      className="status-pill"
      style={{
        background: style.bg,
        color: style.fg,
        border: style.dashed ? "1px dashed var(--text-muted)" : "1px solid transparent",
      }}
      aria-label={`Status ${status.replace("_", " ")}`}
    >
      {status.replace("_", " ")}
    </span>
  );
}

