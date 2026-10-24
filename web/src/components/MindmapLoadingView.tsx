export function MindmapLoadingView() {
  return (
    <div className="mindmap-layout mindmap-loading" role="status" aria-live="polite">
      <div className="state-panel state-panel--loading">
        <span className="state-mark" aria-hidden="true"><i /><i /><i /></span>
        <p className="state-title">Loading agent activity…</p>
        <p className="state-sub">Waiting for the first snapshot from the monitor.</p>
        <div className="state-skeleton" aria-hidden="true">
          <span className="shimmer" /><span className="shimmer" /><span className="shimmer" />
        </div>
      </div>
    </div>
  );
}
