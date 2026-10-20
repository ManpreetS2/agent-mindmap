export function MindmapLoadingView() {
  return (
    <div className="mindmap-layout mindmap-loading" role="status" aria-live="polite">
      <p className="mindmap-loading__text">Reading ledger and GitHub…</p>
      <div className="mindmap-loading__graph" aria-hidden="true">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="skeleton-node" />
        ))}
      </div>
      <div className="mindmap-loading__timeline shimmer" aria-hidden="true" />
    </div>
  );
}
