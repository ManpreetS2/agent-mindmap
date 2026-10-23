import type { Status } from "@shared/types";

const STATUS_STYLES: Record<
  Status,
  { bg: string; fg: string; border: string; dashed?: boolean }
> = {
  FAILED: { bg: "rgba(240, 89, 107, 0.16)", fg: "#ffa3ae", border: "rgba(240, 89, 107, 0.40)" },
  STALE: { bg: "rgba(123, 132, 153, 0.12)", fg: "#aab3c5", border: "rgba(123, 132, 153, 0.55)", dashed: true },
  IDLE: { bg: "rgba(123, 132, 153, 0.14)", fg: "#bfc7d6", border: "rgba(123, 132, 153, 0.30)" },
  IN_PROGRESS: { bg: "rgba(91, 140, 255, 0.16)", fg: "#b3cbff", border: "rgba(91, 140, 255, 0.42)" },
  IN_REVIEW: { bg: "rgba(139, 124, 255, 0.16)", fg: "#cbc3ff", border: "rgba(139, 124, 255, 0.42)" },
  BLOCKED: { bg: "rgba(245, 185, 66, 0.14)", fg: "#f7cf7a", border: "rgba(245, 185, 66, 0.40)" },
  DONE: { bg: "rgba(70, 201, 138, 0.14)", fg: "#8fe3b5", border: "rgba(70, 201, 138, 0.38)" },
  UNKNOWN: { bg: "rgba(123, 132, 153, 0.12)", fg: "#aab3c5", border: "rgba(123, 132, 153, 0.55)", dashed: true },
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
        border: `1px ${style.dashed ? "dashed" : "solid"} ${style.border}`,
      }}
      aria-label={`Status ${status.replace("_", " ")}`}
    >
      {status.replace("_", " ")}
    </span>
  );
}

