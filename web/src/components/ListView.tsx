import { useMemo, useState } from "react";
import type { Activity, Edge, Event, Node, Task } from "@shared/types";
import { isHttpSourceUrl } from "../utils/sourceUrl";
import { UnsourcedTag } from "./UnsourcedTag";
import { StatusPill } from "./StatusPill";
import { formatSourceTime } from "../utils/format";

type SortDir = "asc" | "desc";

function ariaSort(
  active: boolean,
  dir: SortDir,
): "ascending" | "descending" | "none" {
  if (!active) return "none";
  return dir === "asc" ? "ascending" : "descending";
}

interface ListViewProps {
  activity: Activity;
  selectedNodeId: string | null;
  onSelectNode: (id: string) => void;
}

function useSortState<T extends string>(defaultKey: T) {
  const [key, setKey] = useState<T>(defaultKey);
  const [dir, setDir] = useState<SortDir>("asc");
  const toggle = (next: T) => {
    if (key === next) setDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setKey(next);
      setDir("asc");
    }
  };
  return { key, dir, toggle };
}

function SortableHeader({
  label,
  active,
  direction,
  onSort,
}: {
  label: string;
  active: boolean;
  direction: SortDir;
  onSort: () => void;
}) {
  return (
    <th scope="col" aria-sort={ariaSort(active, direction)}>
      <button type="button" className="list-th-sort" onClick={onSort}>
        {label}
      </button>
    </th>
  );
}

export function ListView({
  activity,
  selectedNodeId,
  onSelectNode,
}: ListViewProps) {
  const botSort = useSortState<"label" | "status">("label");
  const taskSort = useSortState<"id" | "owner">("id");
  const eventSort = useSortState<"time" | "type">("time");
  const edgeSort = useSortState<"source" | "type">("source");

  const labelById = useMemo(() => {
    const map = new Map<string, string>();
    for (const n of activity.nodes) map.set(n.id, n.label);
    return map;
  }, [activity.nodes]);

  const bots = useMemo(() => {
    const rows = [...activity.nodes];
    rows.sort((a, b) => {
      const av = botSort.key === "label" ? a.label : a.status;
      const bv = botSort.key === "label" ? b.label : b.status;
      const cmp = av.localeCompare(bv);
      return botSort.dir === "asc" ? cmp : -cmp;
    });
    return rows;
  }, [activity.nodes, botSort.dir, botSort.key]);

  const tasks = useMemo(() => {
    const rows = [...activity.tasks];
    rows.sort((a, b) => {
      const av = taskSort.key === "id" ? a.id : a.owner;
      const bv = taskSort.key === "id" ? b.id : b.owner;
      const cmp = av.localeCompare(bv);
      return taskSort.dir === "asc" ? cmp : -cmp;
    });
    return rows;
  }, [activity.tasks, taskSort.dir, taskSort.key]);

  const events = useMemo(() => {
    const rows = [...activity.events];
    rows.sort((a, b) => {
      if (eventSort.key === "time") {
        const cmp =
          new Date(a.source_time).getTime() - new Date(b.source_time).getTime();
        return eventSort.dir === "asc" ? cmp : -cmp;
      }
      const cmp = a.type.localeCompare(b.type);
      return eventSort.dir === "asc" ? cmp : -cmp;
    });
    return rows;
  }, [activity.events, eventSort.dir, eventSort.key]);

  const edges = useMemo(() => {
    const rows = [...activity.edges];
    rows.sort((a, b) => {
      const av = edgeSort.key === "source" ? a.source : a.type;
      const bv = edgeSort.key === "source" ? b.source : b.type;
      const cmp = av.localeCompare(bv);
      return edgeSort.dir === "asc" ? cmp : -cmp;
    });
    return rows;
  }, [activity.edges, edgeSort.dir, edgeSort.key]);

  const eventById = useMemo(() => {
    const map = new Map<string, Event>();
    for (const e of activity.events) map.set(e.id, e);
    return map;
  }, [activity.events]);

  return (
    <div className="list-view focus-region" role="region" aria-label="List view" tabIndex={0}>
      <section>
        <h2>Bots</h2>
        <table>
          <caption className="sr-only">Bots roster</caption>
          <thead>
            <tr>
              <SortableHeader
                label="Name"
                active={botSort.key === "label"}
                direction={botSort.dir}
                onSort={() => botSort.toggle("label")}
              />
              <SortableHeader
                label="Status"
                active={botSort.key === "status"}
                direction={botSort.dir}
                onSort={() => botSort.toggle("status")}
              />
              <th scope="col">Task</th>
            </tr>
          </thead>
          <tbody>
            {bots.map((n: Node) => (
              <tr
                key={n.id}
                className={selectedNodeId === n.id ? "is-selected" : ""}
              >
                <td>
                  <button type="button" onClick={() => onSelectNode(n.id)}>
                    {n.label}
                  </button>
                </td>
                <td><StatusPill status={n.status} /></td>
                <td className="mono">{n.current_task ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section>
        <h2>Tasks</h2>
        <table>
          <caption className="sr-only">Tasks</caption>
          <thead>
            <tr>
              <SortableHeader
                label="ID"
                active={taskSort.key === "id"}
                direction={taskSort.dir}
                onSort={() => taskSort.toggle("id")}
              />
              <SortableHeader
                label="Owner"
                active={taskSort.key === "owner"}
                direction={taskSort.dir}
                onSort={() => taskSort.toggle("owner")}
              />
              <th scope="col">Status</th>
              <th scope="col">Source</th>
            </tr>
          </thead>
          <tbody>
            {tasks.map((t: Task) => (
              <tr key={t.id}>
                <td className="mono">{t.id}</td>
                <td>{t.owner}</td>
                <td><StatusPill status={t.status} /></td>
                <td>
                  {isHttpSourceUrl(t.source_url) ? (
                    <a href={t.source_url}>ledger</a>
                  ) : (
                    <UnsourcedTag />
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section>
        <h2>Edges</h2>
        <table>
          <caption className="sr-only">Derived edges</caption>
          <thead>
            <tr>
              <SortableHeader
                label="Source"
                active={edgeSort.key === "source"}
                direction={edgeSort.dir}
                onSort={() => edgeSort.toggle("source")}
              />
              <th scope="col">Target</th>
              <SortableHeader
                label="Type"
                active={edgeSort.key === "type"}
                direction={edgeSort.dir}
                onSort={() => edgeSort.toggle("type")}
              />
              <th scope="col">Count</th>
              <th scope="col">Events</th>
            </tr>
          </thead>
          <tbody>
            {edges.map((edge: Edge) => (
              <tr key={edge.id}>
                <td>{labelById.get(edge.source) ?? edge.source}</td>
                <td>{labelById.get(edge.target) ?? edge.target}</td>
                <td>{edge.type}</td>
                <td>{edge.count}</td>
                <td>
                  {edge.event_ids.map((id) => {
                    const ev = eventById.get(id);
                    return isHttpSourceUrl(ev?.source_url) ? (
                      <a key={id} href={ev!.source_url} className="mono">
                        {id}
                      </a>
                    ) : (
                      <span key={id} className="mono">
                        {id} {!ev?.source_url ? null : <UnsourcedTag />}
                      </span>
                    );
                  })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section>
        <h2>Events</h2>
        <table>
          <caption className="sr-only">Events</caption>
          <thead>
            <tr>
              <SortableHeader
                label="Time"
                active={eventSort.key === "time"}
                direction={eventSort.dir}
                onSort={() => eventSort.toggle("time")}
              />
              <SortableHeader
                label="Type"
                active={eventSort.key === "type"}
                direction={eventSort.dir}
                onSort={() => eventSort.toggle("type")}
              />
              <th scope="col">Task</th>
              <th scope="col">Source</th>
            </tr>
          </thead>
          <tbody>
            {events.map((e: Event) => (
              <tr key={e.id}>
                <td>{formatSourceTime(e.source_time)}</td>
                <td>{e.type}</td>
                <td className="mono">{e.task_id ?? "—"}</td>
                <td>
                  {isHttpSourceUrl(e.source_url) ? (
                    <a href={e.source_url}>source</a>
                  ) : (
                    <UnsourcedTag />
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
