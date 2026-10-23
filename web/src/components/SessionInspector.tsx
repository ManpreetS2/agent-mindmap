import { useState } from "react";
import type { Activity, Node } from "@shared/types";
import { formatSourceTime, formatRelativeAgo } from "../utils/format";
import { providerKey, providerLabel } from "../utils/provider";
import {
  chronologyFor,
  freshnessOf,
  relationshipsFor,
} from "../utils/sessionInspector";
import { isHttpSourceUrl } from "../utils/sourceUrl";
import { StatusPill } from "./StatusPill";

interface Props {
  node: Node;
  activity: Activity;
  onClose: () => void;
  onSelectNode?: (id: string) => void;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="inspector-section">
      <h3 className="inspector-section__title">{title}</h3>
      {children}
    </section>
  );
}

function Fact({ label, value, missing, wide, hero }: { label: string; value: React.ReactNode; missing?: boolean; wide?: boolean; hero?: boolean }) {
  return (
    <div className={`inspector-fact${wide || hero ? " inspector-fact--wide" : ""}${hero ? " inspector-fact--hero" : ""}`}>
      <dt>{label}</dt>
      <dd className={missing ? "detail-muted" : undefined}>{value}</dd>
    </div>
  );
}

function CopySessionId({ id }: { id: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(id);
      setState("copied");
    } catch {
      setState("failed");
    }
  };
  return (
    <>
      <button type="button" className="inspector-copy" onClick={copy}>
        Copy session id
      </button>
      <span className="detail-meta" role="status">
        {state === "copied" ? "Copied" : state === "failed" ? "Copy unavailable in this browser" : ""}
      </span>
    </>
  );
}

export function SessionInspector({ node, activity, onClose, onSelectNode }: Props) {
  const session = node.session!;
  const t3 = activity.meta.t3;
  // Any demo mode (static fixture or replay) is synthetic; only live mode may claim verified activity.
  const simulated = t3?.mode === "demo";
  const key = providerKey(session.provider);
  const fresh = freshnessOf(node, activity);
  const relationships = relationshipsFor(node, activity);
  const chronology = chronologyFor(node, activity);
  const links = session.source_links.filter(isHttpSourceUrl);

  return (
    <aside
      className={`detail-panel inspector inspector--${key}`}
      aria-label={`Details for ${node.label}`}
    >
      <div className="detail-panel__header">
        <div>
          <span className={`inspector__provider inspector__provider--${key}`}>
            <span className={`roster-shape roster-shape--${key} inspector__glyph`} aria-hidden="true" />
            {providerLabel(session.provider)}
          </span>
          {simulated && <span className="inspector__sim">SIMULATED</span>}
          <h2>{node.label}</h2>
        </div>
        <button type="button" className="detail-panel__close" onClick={onClose} aria-label="Close detail panel">
          ×
        </button>
      </div>

      {fresh.kind === "unavailable" && (
        <p className="inspector-note inspector-note--warn" role="status">
          T3 is unavailable. This is the last known snapshot and may no longer be accurate.
        </p>
      )}
      {fresh.kind === "stale" && (
        <p className="inspector-note inspector-note--warn" role="status">
          Stale: T3 has reported no update for longer than {t3?.stale_after_sec ?? "the configured"} s.
          The reported status below is not confirmed as current.
        </p>
      )}
      {fresh.kind === "unknown" && (
        <p className="inspector-note" role="status">
          Status unknown: T3 reported “{session.reported_status}”, which this dashboard does not map.
        </p>
      )}

      <div className="inspector-status" data-testid="inspector-status">
        <StatusPill status={node.status} />
        <span className="detail-meta">{simulated ? "Simulated status" : "T3 reported"}: {session.reported_status}</span>
      </div>

      <dl className="inspector-facts">
        <Fact label="Provider" value={session.provider ?? "Not reported by T3"} missing={!session.provider} />
        <Fact label="Model" value={session.model ?? "Not reported by T3"} missing={!session.model} />
        <Fact hero label="Current task" value={node.current_task ?? "Not reported"} missing={!node.current_task} />
        <Fact label="Project" value={session.project} />
        <Fact label="Branch" value={session.branch ?? "Not reported"} missing={!session.branch} />
        <Fact wide label="Session" value={<><span className="mono">{session.thread_id}</span><div><CopySessionId id={session.thread_id} /></div></>} />
        <Fact label="Source" value={session.source} />
        <Fact
          wide
          label={simulated ? "Simulated activity time" : "Last verified activity"}
          missing={!node.last_activity_ts}
          value={
            node.last_activity_ts ? (
              <>
                {formatSourceTime(node.last_activity_ts)}
                <div className="detail-meta">{formatRelativeAgo(node.last_activity_ts)} · {simulated ? "simulated timestamp" : "last T3 thread update, not proof of a specific action"}</div>
              </>
            ) : (
              "Not reported"
            )
          }
        />
      </dl>

      <Section title={simulated ? "Relationships (simulated)" : "Verified relationships"}>
        {relationships.length === 0 ? (
          <p className="detail-muted">No delegation lineage reported for this session.</p>
        ) : (
          <ul className="inspector-list">
            {relationships.map((r) => (
              <li key={r.edge.id}>
                <div>
                  {r.direction === "parent" ? "Delegated by " : "Delegated to "}
                  {r.other ? (
                    <button type="button" className="inspector-link" onClick={() => onSelectNode?.(r.other!.id)}>
                      {r.other.label}
                    </button>
                  ) : (
                    <span className="detail-muted">a session not in this snapshot</span>
                  )}
                </div>
                <div className="detail-meta">
                  {simulated ? "Simulated delegation" : "T3 subagent lineage"} ·{" "}
                  {r.evidence.length
                    ? r.evidence.map((e) => `${e.raw} (${formatSourceTime(e.source_time)})`).join("; ")
                    : "no evidence event in snapshot"}
                </div>
              </li>
            ))}
          </ul>
        )}
        <p className="detail-muted inspector-caveat">
          A delegation edge shows lineage only. It does not show that messages were exchanged or that work is ongoing.
        </p>
      </Section>

      <Section title="Observed status history">
        {chronology.length === 0 ? (
          <p className="detail-muted">No events available for this session.</p>
        ) : (
          <ol className="inspector-timeline">
            {chronology.map((e) => (
              <li key={e.id}>
                <time dateTime={e.source_time}>{formatSourceTime(e.source_time)}</time>
                <span>
                  {e.target === node.id && e.actor !== node.id ? "Incoming: " : ""}
                  {e.raw}
                </span>
              </li>
            ))}
          </ol>
        )}
        <p className="detail-muted inspector-caveat">
          Snapshot-based: transitions between polls may be missed.
        </p>
      </Section>

      <Section title="Links">
        {links.length ? (
          links.map((url) => (
            <div key={url}>
              <a href={url} target="_blank" rel="noopener noreferrer">{url}</a>
            </div>
          ))
        ) : (
          <p className="detail-muted">No external links reported.</p>
        )}
      </Section>

      <p className="detail-muted inspector-caveat">
        {simulated
          ? "Synthetic demo metadata. These are simulated agents, models, tasks and delegation — not real T3 activity."
          : "Read-only metadata. Prompts, messages, tool output, token usage and credentials are unsupported and not published."}
      </p>
    </aside>
  );
}
