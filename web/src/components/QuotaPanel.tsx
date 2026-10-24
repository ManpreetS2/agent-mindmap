import type { ObservabilityState } from "../hooks/useObservability";
import {
  countdownTo,
  evaluateObservability,
  formatAge,
  type EvaluatedQuotaPool,
} from "../utils/observabilityEval";
import { formatSourceTime } from "../utils/format";
import type { QuotaStatus, QuotaWindow } from "@shared/observability";

interface Props {
  state: ObservabilityState;
  nowMs: number;
}

const STATUS_ICON: Record<QuotaStatus, string> = {
  VERIFIED: "●",
  MANUAL: "✎",
  STALE: "◌",
  UNKNOWN: "?",
  UNSUPPORTED: "⊘",
  ERROR: "✕",
};

function canShowBars(status: QuotaStatus): boolean {
  return status === "VERIFIED" || status === "MANUAL";
}

function WindowRow({
  window: w,
  showMeter,
  stale,
  observedAt,
  nowMs,
}: {
  window: QuotaWindow;
  showMeter: boolean;
  stale: boolean;
  observedAt: string | null;
  nowMs: number;
}) {
  const used = w.used_pct;
  const rem = w.remaining_pct;
  const resetLabel = w.resets_at
    ? `${formatSourceTime(w.resets_at)}${countdownTo(w.resets_at, nowMs) ? ` (${countdownTo(w.resets_at, nowMs)})` : ""}`
    : "reset time not reported";

  if (!showMeter) {
    return (
      <li className={`quota-window${stale ? " quota-window--stale" : ""}`}>
        <div className="quota-window__head">
          <span className="quota-window__label">{w.label}</span>
          {stale && observedAt && (
            <span className="quota-window__expired">
              expired reading from {formatSourceTime(observedAt)}
            </span>
          )}
        </div>
        {stale && used != null ? (
          <p className="quota-window__stale-values">
            <span className="quota-window__struck">
              used {used}% · remaining {rem ?? "—"}%
            </span>
            {" · "}
            reset {resetLabel}
          </p>
        ) : null}
      </li>
    );
  }

  const valueNow = used ?? 0;
  return (
    <li className="quota-window">
      <div className="quota-window__head">
        <span className="quota-window__label">{w.label}</span>
        <span className="quota-window__pct">
          used {used ?? "—"}% · remaining {rem ?? "—"}%
        </span>
      </div>
      {used != null && (
        <div
          className="quota-meter"
          role="meter"
          aria-label={`${w.label} used`}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={valueNow}
          aria-valuetext={`${valueNow}% used`}
        >
          <div className="quota-meter__fill" style={{ width: `${Math.min(100, Math.max(0, valueNow))}%` }} />
        </div>
      )}
      <p className="quota-window__reset">Resets {resetLabel}</p>
    </li>
  );
}

function PoolCard({ pool, nowMs }: { pool: EvaluatedQuotaPool; nowMs: number }) {
  const status = pool.effectiveStatus;
  const demoValue = Boolean(pool.demoValue);
  // Demo never exposes VERIFIED chrome; badge is neutral "DEMO value".
  const displayStatus = demoValue ? "DEMO" : status;
  const bars = !demoValue && canShowBars(status);
  const reasonOnly = status === "UNKNOWN" || status === "UNSUPPORTED" || status === "ERROR";
  const stale = status === "STALE";

  return (
    <article
      className={`quota-card quota-card--${displayStatus.toLowerCase()}${pool.clientExpired ? " quota-card--client-expired" : ""}${demoValue ? " quota-card--demo-value" : ""}`}
      data-testid={`quota-pool-${pool.id}`}
      data-status={displayStatus}
      aria-label={`${pool.label} quota`}
    >
      <header className="quota-card__head">
        <h3 className="quota-card__title">{pool.label}</h3>
        <span
          className={`quota-badge quota-badge--${displayStatus.toLowerCase()}`}
          aria-label={demoValue ? "Status DEMO value" : `Status ${status}`}
        >
          <span aria-hidden="true">{demoValue ? "◌" : STATUS_ICON[status]} </span>
          {demoValue ? "DEMO value" : status}
        </span>
      </header>
      <p className="quota-card__plan">
        Plan: {pool.plan ?? "not reported"}
      </p>
      <p className="quota-card__source">
        Source: {pool.source.method}
        {" · "}
        {pool.source.supported_programmatically
          ? "programmatic source supported"
          : "not supported programmatically"}
      </p>
      <p className="quota-card__observed">
        Observed {pool.observed_at ? `${formatSourceTime(pool.observed_at)} (${formatAge(pool.observed_at, nowMs)})` : "never"}
      </p>

      {reasonOnly ? (
        <p className="quota-card__reason" role="status">
          {pool.reason ?? "No sourced reading"}
        </p>
      ) : (
        <>
          {stale && (
            <p className="quota-card__reason" role="status">
              {pool.reason ?? "Reading expired"}
              {pool.observed_at
                ? ` — expired reading from ${formatSourceTime(pool.observed_at)}`
                : ""}
            </p>
          )}
          {pool.windows.length === 0 ? (
            <p className="quota-card__reason">No windows reported</p>
          ) : (
            <ul className="quota-windows">
              {pool.windows.map((w) => (
                <WindowRow
                  key={`${w.type}-${w.label}`}
                  window={w}
                  showMeter={bars}
                  stale={stale}
                  observedAt={pool.observed_at}
                  nowMs={nowMs}
                />
              ))}
            </ul>
          )}
        </>
      )}
    </article>
  );
}

/** Five separate account quota cards. Never combines or averages pools. */
export function QuotaPanel({ state, nowMs }: Props) {
  if (state.status === "loading") return null;
  if (state.status === "absent" || state.status === "rejected") {
    return (
      <section className="quota-panel quota-panel--unavailable" aria-label="Account quota" data-testid="quota-panel">
        <h2 className="quota-panel__title">Account quota</h2>
        <p role="status">
          {state.status === "rejected"
            ? `Quota unavailable — observability rejected (${state.reason}).`
            : "Quota unavailable — no observability document. Each account’s headroom is unknown."}
        </p>
      </section>
    );
  }

  const doc = evaluateObservability(state.data, nowMs);
  const demo = doc.mode === "demo";

  return (
    <section
      className={`quota-panel${demo ? " quota-panel--demo" : ""}`}
      aria-label="Account quota"
      data-testid="quota-panel"
    >
      <div className="quota-panel__head">
        <h2 className="quota-panel__title">Account quota</h2>
        {demo && (
          <p className="quota-panel__demo" role="status">
            DEMO — illustrative values only; not real account readings.
          </p>
        )}
        <p className="quota-panel__note">
          Five separate pools. Claude 1 and Claude 2 are never combined.
        </p>
      </div>
      <div className="quota-panel__grid">
        {doc.pools.map((pool) => (
          <PoolCard key={pool.id} pool={pool} nowMs={nowMs} />
        ))}
      </div>
    </section>
  );
}
