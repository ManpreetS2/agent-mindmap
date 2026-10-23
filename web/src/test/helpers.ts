import type { Activity, Edge, Event, Node } from "@shared/types";

export function sessionNode(id: string, over: Partial<Node> = {}, session: Partial<NonNullable<Node["session"]>> = {}): Node {
  return {
    id, label: `Task ${id}`, group: "sessions", status: "IN_PROGRESS", current_task: `Task ${id}`,
    last_activity_ts: "2026-10-22T20:00:00Z", agent_links: [], layout: { x: 0, y: 0 },
    session: { source: "local", thread_id: `thread-${id}`, project: "Proj", provider: "Codex", model: "model-x",
      reported_status: "running", branch: "feat/x", source_links: [], stale: false, ...session },
    ...over,
  };
}

export function delegation(source: string, target: string): { edge: Edge; event: Event } {
  const id = `delegation-${target}`;
  return {
    edge: { id, source, target, type: "delegation", count: 1, event_ids: [id] },
    event: { id, type: "note", actor: source, target, task_id: null, attribution: { method: "unknown" },
      source_url: `t3-thread://v1/${target}`, source_time: "2026-10-22T19:50:00Z", raw: "T3 reported subagent lineage" },
  };
}

export function t3Activity(
  nodes: Node[],
  pairs: Array<[string, string]> = [],
  mode: "live" | "demo" = "live",
  replay?: { stage: number; stage_count: number; cycle: number; step_sec: number; label: string },
  connection: "connected" | "unavailable" = "connected",
): Activity {
  const d = pairs.map(([s, t]) => delegation(s, t));
  const states: Event[] = nodes.map((n) => ({
    id: `state-${n.id}`, type: "note", actor: n.id, target: null, task_id: null, attribution: { method: "unknown" },
    source_url: `t3-thread://v1/${n.id}`, source_time: "2026-10-22T20:00:00Z", raw: "T3 reported thread status: running",
  }));
  return {
    schema_version: "1.0.0", generated_at: "2026-10-22T20:00:00Z", project: "T3 Code",
    meta: { github: "skipped", ledger: "skipped", t3: { source: "local", mode, connection, server_version: "1", stale_after_sec: 300, ...(replay ? { replay } : {}) } },
    nodes, tasks: [], events: [...states, ...d.map((x) => x.event)], edges: d.map((x) => x.edge), unparsed: [],
  };
}
