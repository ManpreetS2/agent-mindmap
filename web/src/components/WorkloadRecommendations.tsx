import type { Activity } from "@shared/types";
import type { ObservabilityState } from "../hooks/useObservability";
import { recommend } from "../utils/recommendations";

interface Props {
  activity: Activity;
  observability: ObservabilityState;
  nowMs: number;
}

/** Possible next worker suggestions with evidence — never dispatch actions. */
export function WorkloadRecommendations({ activity, observability, nowMs }: Props) {
  const doc = observability.status === "ok" ? observability.data : null;
  const result = recommend(activity, doc, nowMs);
  const demo = doc?.mode === "demo";

  return (
    <section
      className={`workload-recs${demo ? " workload-recs--demo" : ""}`}
      aria-label="Workload recommendations"
      data-testid="workload-recommendations"
    >
      <h2 className="workload-recs__title">Possible next worker (evidence below)</h2>
      {demo && (
        <p className="workload-recs__demo" role="status">
          Illustrative DEMO — not actionable recommendations.
        </p>
      )}

      {result.status === "INSUFFICIENT_DATA" ? (
        <div role="status">
          <p className="workload-recs__status">INSUFFICIENT_DATA</p>
          <ul className="workload-recs__reasons">
            {result.reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </div>
      ) : (
        <ol className="workload-recs__candidates">
          {result.candidates.map((c) => (
            <li key={c.poolId} data-testid={`rec-candidate-${c.poolId}`}>
              <strong>
                #{c.rank} {c.label}
              </strong>{" "}
              <span className="detail-muted">({c.provider})</span>
              <ul className="workload-recs__evidence">
                {c.evidence.map((e) => (
                  <li key={e}>{e}</li>
                ))}
              </ul>
              <ul className="workload-recs__limits">
                {c.limitations.map((l) => (
                  <li key={l}>{l}</li>
                ))}
              </ul>
            </li>
          ))}
        </ol>
      )}

      <div className="workload-recs__blockers">
        <h3>Verified blockers (separate from quota)</h3>
        {result.blockers.length === 0 ? (
          <p className="detail-muted">No BLOCKED/FAILED sessions or waiting tasks reported.</p>
        ) : (
          <ul>
            {result.blockers.map((b) => (
              <li key={`${b.kind}-${b.id}`}>
                <span className="mono">{b.id}</span> · {b.label} · {b.status} · {b.age}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
