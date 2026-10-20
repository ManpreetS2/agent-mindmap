import { LEDGER_ERROR_PATH } from "../utils/viewState";

interface LedgerErrorViewProps {
  onRetry: () => void;
}

export function LedgerErrorView({ onRetry }: LedgerErrorViewProps) {
  return (
    <div className="ledger-error" role="alert">
      <h1>Can&apos;t read {LEDGER_ERROR_PATH}</h1>
      <p className="mono">{LEDGER_ERROR_PATH}</p>
      <button type="button" onClick={onRetry}>
        Retry
      </button>
    </div>
  );
}
