import { describe, expect, it } from "vitest";
import { staleAgeLabel } from "../utils/viewState";

const nowMs = Date.parse("2026-10-28T12:00:00Z");

function timestampMinutesAgo(minutes: number): string {
  return new Date(nowMs - minutes * 60_000).toISOString();
}

function timestampHoursAgo(hours: number): string {
  return new Date(nowMs - hours * 60 * 60_000).toISOString();
}

describe("staleAgeLabel", () => {
  it.each([
    [1, "1 minute ago"],
    [59, "59 minutes ago"],
    [60, "1 hour ago"],
    [89, "1 hour ago"],
    [90, "2 hours ago"],
  ])("labels %i minutes ago", (minutes, expected) => {
    expect(staleAgeLabel(timestampMinutesAgo(minutes), nowMs)).toBe(expected);
  });

  it.each([
    [47, "47 hours ago"],
    [48, "2 days ago"],
  ])("labels %i hours ago", (hours, expected) => {
    expect(staleAgeLabel(timestampHoursAgo(hours), nowMs)).toBe(expected);
  });

  it("returns unknown age for an invalid timestamp", () => {
    expect(staleAgeLabel("not a timestamp", nowMs)).toBe("unknown age");
  });

  it("returns just now for a future timestamp", () => {
    expect(staleAgeLabel(new Date(nowMs + 30 * 60_000).toISOString(), nowMs)).toBe(
      "just now",
    );
  });
});
