import { useMemo, useState } from "react";
import type { Activity, Event, Node, Task } from "@shared/types";
import { StatusPill } from "./StatusPill";

type SortDir = "asc" | "desc";

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

function SortButton({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className={`list-sort-btn${active ? " is-active" : ""}`}
      onClick={onClick}
      aria-pressed={active}
    >
      {label}
    </button>
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

  return (
    <div className="list-view" role="region" aria-label="List view">
      <section>
        <h2>Bots</h2>
        <div className="list-sort-row">
          <SortButton
            label="Name"
            active={botSort.key === "label"}
            onClick={() => botSort.toggle("label")}
          />
          <SortButton
            label="Status"
            active={botSort.key === "status"}
            onClick={() => botSort.toggle("status")}
          />
        </div>
        <table>
          <caption className="sr-only">Bots roster</caption>
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col">Status</th>
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
        <div className="list-sort-row">
          <SortButton
            label="ID"
            active={taskSort.key === "id"}
            onClick={() => taskSort.toggle("id")}
          />
          <SortButton
            label="Owner"
            active={taskSort.key === "owner"}
            onClick={() => taskSort.toggle("owner")}
          />
        </div>
        <table>
          <caption className="sr-only">Tasks</caption>
          <thead>
            <tr>
              <th scope="col">ID</th>
              <th scope="col">Owner</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {tasks.map((t: Task) => (
              <tr key={t.id}>
                <td>
                  <a href={t.source_url} className="mono">{t.id}</a>
                </td>
                <td>{t.owner}</td>
                <td><StatusPill status={t.status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section>
        <h2>Events</h2>
        <div className="list-sort-row">
          <SortButton
            label="Time"
            active={eventSort.key === "time"}
            onClick={() => eventSort.toggle("time")}
          />
          <SortButton
            label="Type"
            active={eventSort.key === "type"}
            onClick={() => eventSort.toggle("type")}
          />
        </div>
        <table>
          <caption className="sr-only">Events</caption>
          <thead>
            <tr>
              <th scope="col">Time</th>
              <th scope="col">Type</th>
              <th scope="col">Task</th>
              <th scope="col">Source</th>
            </tr>
          </thead>
          <tbody>
            {events.map((e: Event) => (
              <tr key={e.id}>
                <td>{e.source_time}</td>
                <td>{e.type}</td>
                <td className="mono">{e.task_id ?? "—"}</td>
                <td>
                  {e.source_url ? (
                    <a href={e.source_url}>source</a>
                  ) : (
                    <span className="unsourced-tag" aria-label="Unsourced fact">
                      unsourced
                    </span>
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
