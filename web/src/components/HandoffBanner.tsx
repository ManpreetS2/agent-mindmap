interface HandoffBannerProps {
  handoffCount: number;
  threshold: number;
}

export function HandoffBanner({ handoffCount, threshold }: HandoffBannerProps) {
  if (handoffCount >= threshold) return null;
  return (
    <div className="handoff-banner" role="status">
      Handoffs happen in chat rooms and appear only when recorded in the ledger.
      <span className="handoff-banner__count">
        ({handoffCount} handoff edge{handoffCount === 1 ? "" : "s"} shown)
      </span>
    </div>
  );
}
