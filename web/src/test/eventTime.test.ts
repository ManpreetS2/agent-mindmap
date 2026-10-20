import { describe, expect, it } from "vitest";
import type { Event } from "@shared/types";
import {
  isPlottableTimelineEvent,
  isUndatedSourceTime,
  plottableTimelineEvents,
} from "../utils/eventTime";
import { buildTimeScale } from "../utils/timelineScale";
import { allTimelineEvents } from "../utils/timelineLanes";
import type { Activity } from "@shared/types";

const dated: Event = {
  id: "e1",
  type: "handoff",
  actor: "director",
  target: "architect",
  task_id: "RP-009",
  attribution: { method: "ledger_owner" },
  source_url: "https://github.com/o/r/pull/1",
  source_time: "2026-10-19T21:20:00-07:00",
  raw: "handoff",
  provenance: "agent-reported",
};

const undated: Event = {
  ...dated,
  id: "u1",
  type: "unparsed",
  source_time: "1970-01-01T00:00:00-08:00",
};

describe("eventTime (MM-012 bug fixes)", () => {
  it("detects ingest undated sentinel", () => {
    expect(isUndatedSourceTime("1970-01-01T00:00:00-08:00")).toBe(true);
    expect(isUndatedSourceTime("2026-10-19T21:20:00-07:00")).toBe(false);
  });

  it("excludes unparsed and sentinel from plottable events", () => {
    expect(isPlottableTimelineEvent(undated)).toBe(false);
    expect(isPlottableTimelineEvent(dated)).toBe(true);
    expect(plottableTimelineEvents([dated, undated])).toEqual([dated]);
  });

  it("does not merge unparsed into timeline event list", () => {
    const activity = {
      events: [dated],
      unparsed: [undated],
    } as unknown as Activity;
    expect(allTimelineEvents(activity)).toEqual([dated]);
  });

  it("buildTimeScale ignores undated events so dated events spread across width", () => {
    const scale = buildTimeScale([dated, undated], 400);
    const xDated = scale.toX(new Date(dated.source_time).getTime());
    expect(xDated).toBeGreaterThan(50);
    expect(xDated).toBeLessThan(380);
  });
});
