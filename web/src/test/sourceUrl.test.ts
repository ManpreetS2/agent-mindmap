import { describe, expect, it } from "vitest";
import { factSourceFromUrl, isHttpSourceUrl } from "../utils/sourceUrl";

describe("source URLs (QA-MM006-3)", () => {
  it("treats http(s) as linkable", () => {
    expect(isHttpSourceUrl("https://github.com/o/r/pull/1")).toBe(true);
    expect(isHttpSourceUrl("http://example.com/x")).toBe(true);
    expect(factSourceFromUrl("https://x.test/a").kind).toBe("linked");
  });

  it("treats ledger paths and empty as unsourced", () => {
    expect(isHttpSourceUrl("build/task-ledger.md#RP-004")).toBe(false);
    expect(isHttpSourceUrl("")).toBe(false);
    expect(factSourceFromUrl("build/task-ledger.md").kind).toBe("unsourced");
  });
});
