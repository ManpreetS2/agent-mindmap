import type { ObservabilityState } from "../hooks/useObservability";
import {
  countdownTo,
  evaluateObservability,
  formatAge,
} from "../utils/observabilityEval";

interface Props {
  state: ObservabilityState;
  nowMs: number;
}

function Item({ label, tone, children }: { label: string; tone: string; children: React.ReactNode }) {
  return (
    <li className={`source-health__item source-health__item--${tone}`}>
      <span className="source-health__label">{label}</span>
      <span className="source-health__value">{children}</span>
    </li>
  );
}

/** Always-visible provenance strip: demo vs live, collector, feed, machine. */
export function SourceHealthBar({ state, nowMs }: Props) {
  if (state.status === "loading") return null;
  if (state.status === "absent" || state.status === "rejected") {
    return (
      <section className="source-health source-health--unavailable" aria-label="Source health" data-testid="source-health">
        <p role="status">
          <strong>◌ Source health unavailable</strong>
          <span>
            {state.status === "rejected"
              ? ` — observability unavailable (${state.reason}).`
              : " — no observability data from this server. Quota, collector and feed health are unknown."}
          </span>
        </p>
      </section>
    );
  }
  const doc = evaluateObservability(state.data, nowMs);
  const demo = doc.mode === "demo";
  const { collector, feed, machine } = doc;
  const collectorTone = collector.status === "connected" && !doc.documentStale ? "ok" : collector.status === "unavailable" ? "bad" : "unknown";
  const feedTone = feed.status === "fresh" ? "ok" : feed.status === "stale" ? "warn" : feed.status === "unpublished" || feed.status === "disabled" ? "muted" : "unknown";
  const ownership =
    feed.owned_by_this_machine === true
      ? "owned by this machine"
      : feed.owned_by_this_machine === false
        ? "another machine owns publishing"
        : "ownership unknown";
  return (
    <section className={`source-health ${demo ? "source-health--demo" : ""}`} aria-label="Source health" data-testid="source-health">
      {demo && (
        <p className="source-health__demo" role="status">
          <strong>DEMO — SYNTHETIC DATA</strong> Illustrative only: nothing here is a real reading.
        </p>
      )}
      {!demo && doc.documentStale && (
        <p className="source-health__stale" role="status">
          <strong>Observability document is stale</strong> (generated {formatAge(doc.generated_at, nowMs)}).
        </p>
      )}
      <ul className="source-health__list">
        <Item label="Mode" tone={demo ? "demo" : "ok"}>{demo ? "DEMO" : "Live"}</Item>
        <Item label="Collector" tone={collectorTone}>
          <span role="status">
            {collector.status === "connected" ? "● connected" : collector.status === "unavailable" ? "✕ unavailable" : "? unknown"}
          </span>
          {" · last T3 poll "}{formatAge(collector.last_t3_poll, nowMs)}
          {collector.reason ? ` · ${collector.reason}` : ""}
        </Item>
        <Item label="GitHub snapshot" tone={feedTone}>
          <span role="status">{feed.status}</span>
          {feed.last_published_at && <> · published {formatAge(feed.last_published_at, nowMs)}</>}
          {feed.last_observed_at && <> · observed {formatAge(feed.last_observed_at, nowMs)}</>}
          {feed.trusted_until && (
            <> · {countdownTo(feed.trusted_until, nowMs) === "passed" ? "trust expired" : `trusted until ${feed.trusted_until} (${countdownTo(feed.trusted_until, nowMs)})`}</>
          )}
          {feed.last_error ? ` · error: ${feed.last_error}` : ""}
        </Item>
        <Item label="Machine" tone="muted">
          {machine.label} · {machine.role}
        </Item>
        <Item label="Feed owner" tone={feed.owned_by_this_machine === false ? "warn" : "muted"}>
          {feed.owner ? `${feed.owner.label} (epoch ${feed.owner.epoch})` : "no owner"} · {ownership}
        </Item>
      </ul>
    </section>
  );
}
