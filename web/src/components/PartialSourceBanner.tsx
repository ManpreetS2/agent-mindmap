interface PartialSourceBannerProps {
  message: string;
  onRetry?: () => void;
}

export function PartialSourceBanner({ message, onRetry }: PartialSourceBannerProps) {
  return (
    <div className="partial-source-banner" role="status">
      <span>{message}</span>
      {onRetry && (
        <button type="button" className="partial-source-banner__retry" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}
