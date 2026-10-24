import { LEDGER_ERROR_PATH } from "../utils/viewState";

interface LedgerErrorViewProps {
  onRetry: () => void;
}

export function LedgerErrorView({ onRetry }: LedgerErrorViewProps) {
  return (
    <div className="ledger-error state-panel state-panel--error" role="alert">
      <span className="state-icon" aria-hidden="true">!</span>
      <h1>Can&apos;t read {LEDGER_ERROR_PATH}</h1>
      <p className="state-sub">No activity data is available yet. Check that the monitor is running, then retry.</p>
      <p className="mono state-path">{LEDGER_ERROR_PATH}</p>
      <button type="button" className="state-button" onClick={onRetry}>
        Retry
      </button>
    </div>
  );
}
