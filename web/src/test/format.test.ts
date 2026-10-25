import { describe, expect, it } from "vitest";
import {
  attributionLabel,
  formatRelativeAgo,
  formatSourceTime,
  sourceKindFromUrl,
} from "../utils/format";

describe("formatSourceTime", () => {
  it("formats valid ISO timestamps in Los Angeles time", () => {
    const formatted = formatSourceTime("2026-01-15T20:30:00Z");
    expect(formatted).toContain("Jan 15");
    expect(formatted).toContain("12:30");
    expect(formatted).toContain("PST");
  });

  it("returns invalid and empty input unchanged", () => {
    expect(formatSourceTime("garbage")).toBe("garbage");
    expect(formatSourceTime("")).toBe("");
  });
});

describe("formatRelativeAgo", () => {
  const now = new Date("2026-01-15T20:30:00Z");

  it("formats recent timestamps", () => {
    expect(formatRelativeAgo("2026-01-15T20:30:00Z", now)).toBe("just now");
    expect(formatRelativeAgo("2026-01-15T20:20:00Z", now)).toBe("10m ago");
    expect(formatRelativeAgo("2026-01-15T17:30:00Z", now)).toBe("3h ago");
    expect(formatRelativeAgo("2026-01-12T20:30:00Z", now)).toBe("3d ago");
  });

  it("returns unknown time for invalid input", () => {
    expect(formatRelativeAgo("garbage", now)).toBe("unknown time");
  });
});

describe("attributionLabel", () => {
  it("labels known methods and passes through unknown methods", () => {
    expect(attributionLabel("signature")).toBe("signature");
    expect(attributionLabel("ledger_owner")).toBe("ledger / task owner");
    expect(attributionLabel("unknown")).toBe("unknown");
    expect(attributionLabel("manual")).toBe("manual");
  });
});

describe("sourceKindFromUrl", () => {
  it("classifies recognized URLs and falls back to source", () => {
    expect(sourceKindFromUrl("https://github.com/org/repo/issues/1")).toBe("GitHub");
    expect(sourceKindFromUrl("https://example.com/task-ledger/1")).toBe("ledger");
    expect(sourceKindFromUrl("/build/tasks/1.md")).toBe("task file");
    expect(sourceKindFromUrl("https://example.com/page")).toBe("source");
  });
});
