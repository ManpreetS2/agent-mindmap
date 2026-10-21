interface MindmapStatusBarProps {
  segments: string[];
  onRetry?: () => void;
  retryDisabled?: boolean;
}

export function MindmapStatusBar({
  segments,
  onRetry,
  retryDisabled = false,
}: MindmapStatusBarProps) {
  if (segments.length === 0) return null;
  const isAlert = segments.some((s) => /403|denied/i.test(s));
  return (
    <div
      className="partial-source-banner mindmap-status-bar"
      role={isAlert ? "alert" : "status"}
    >
      <span className="mindmap-status-bar__text">{segments.join(" · ")}</span>
      {onRetry && (
        <button
          type="button"
          className="partial-source-banner__retry"
          onClick={onRetry}
          disabled={retryDisabled}
        >
          Retry
        </button>
      )}
    </div>
  );
}
