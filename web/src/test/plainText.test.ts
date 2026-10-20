import { describe, expect, it } from "vitest";
import { plainTextForDisplay } from "../utils/plainText";

describe("plainTextForDisplay (QA-MM020e-6)", () => {
  it("strips HTML tags from raw display text", () => {
    const raw = '<img src=x onerror="alert(1)">hello';
    expect(plainTextForDisplay(raw)).toBe("hello");
  });

  it("leaves normal text unchanged", () => {
    expect(plainTextForDisplay("Opened PR #9")).toBe("Opened PR #9");
  });
});
