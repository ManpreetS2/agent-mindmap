import { describe, expect, it } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useObservability } from "../hooks/useObservability";
import type { ObservabilityTransport } from "../data/observabilityTransport";
import { loadFixture } from "./obsFixtures";

const t = (fetch: ObservabilityTransport["fetch"]): ObservabilityTransport => ({ kind: "t", fetch });

describe("useObservability", () => {
  it("ok", async () => {
    const data = loadFixture("demo");
    const { result } = renderHook(() => useObservability(t(async () => ({ kind: "ok", data, etag: null }))));
    expect(result.current.status).toBe("loading");
    await waitFor(() => expect(result.current.status).toBe("ok"));
  });
  it("absent", async () => {
    const { result } = renderHook(() => useObservability(t(async () => ({ kind: "absent" }))));
    await waitFor(() => expect(result.current.status).toBe("absent"));
  });
  it("rejected", async () => {
    const { result } = renderHook(() => useObservability(t(async () => ({ kind: "rejected", reason: "bad" }))));
    await waitFor(() => expect(result.current).toEqual({ status: "rejected", reason: "bad" }));
  });
  it("thrown fetch becomes absent", async () => {
    const { result } = renderHook(() => useObservability(t(async () => { throw new Error("x"); })));
    await waitFor(() => expect(result.current.status).toBe("absent"));
  });
});
