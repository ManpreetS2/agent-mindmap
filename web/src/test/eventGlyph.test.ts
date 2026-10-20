import { describe, expect, it } from "vitest";
import type { Event } from "@shared/types";
import { glyphForEvent, verdictLabel } from "../utils/eventGlyph";

function verdictEvent(verdict: string | null): Event {
  return {
    id: "t",
    type: "verdict",
    actor: "qa-verifier",
    target: "dev-1",
    task_id: "MM-004",
    attribution: { method: "signature" },
    source_url: "https://github.com/ManpreetS2/fencepost/pull/1",
    source_time: "2026-10-20T00:00:00Z",
    raw: "test",
    verdict: verdict as Event["verdict"],
  };
}

describe("verdictLabel / unknown verdict fallback (QA-MM004)", () => {
  it("maps known widened enum tokens", () => {
    expect(verdictLabel("PASS")).toBe("PASS");
    expect(verdictLabel("FAIL")).toBe("FAIL");
    expect(verdictLabel("CHANGES")).toBe("CHG");
    expect(verdictLabel("CONDITIONAL")).toBe("COND");
    expect(verdictLabel("BLOCKED")).toBe("BLK");
    expect(verdictLabel("INCONCLUSIVE")).toBe("INC");
  });

  it("falls back cleanly on null, empty, and unknown values", () => {
    expect(verdictLabel(null)).toBe("VER");
    expect(verdictLabel(undefined)).toBe("VER");
    expect(verdictLabel("")).toBe("VER");
    expect(verdictLabel("TOTALLY_NEW_TOKEN")).toBe("VER");
    expect(verdictLabel("weird")).toBe("VER");
  });

  it("glyphForEvent does not throw on unknown verdict strings", () => {
    const glyph = glyphForEvent(verdictEvent("FUTURE_VERDICT_XYZ"));
    expect(glyph.label).toBe("VER");
    expect(glyph.title).toMatch(/FUTURE_VERDICT_XYZ/);
    expect(glyph.fill).toBe("var(--edge-verdict)");
  });
});
