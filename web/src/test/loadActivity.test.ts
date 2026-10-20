import { describe, expect, it, vi } from "vitest";
import type { Activity } from "@shared/types";
import { LedgerLoadError, loadActivity } from "../data/loadActivity";

const sample: Activity = {
  schema_version: "1.0.0",
  generated_at: "2026-10-20T04:58:00-07:00",
  project: "fencepost",
  meta: { github: "ok" },
  nodes: [],
  tasks: [],
  events: [],
  edges: [],
  unparsed: [],
};

describe("loadActivity (QA-MM012-1)", () => {
  it("loads valid application/json activity", async () => {
    const fetchImpl = vi.fn(async () =>
      new Response(JSON.stringify(sample), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    ) as unknown as typeof fetch;

    const data = await loadActivity("/activity.json", fetchImpl);
    expect(data.generated_at).toBe(sample.generated_at);
  });

  it("throws LedgerLoadError on 404 / 422", async () => {
    for (const status of [404, 422]) {
      const fetchImpl = vi.fn(async () =>
        new Response("missing", { status }),
      ) as unknown as typeof fetch;
      await expect(loadActivity("/activity.json", fetchImpl)).rejects.toBeInstanceOf(
        LedgerLoadError,
      );
    }
  });

  it("throws LedgerLoadError when Vite serves HTML with HTTP 200", async () => {
    const html = "<!doctype html>\n<html lang=\"en\"><head></head><body></body></html>";
    const fetchImpl = vi.fn(async () =>
      new Response(html, {
        status: 200,
        headers: { "content-type": "text/html" },
      }),
    ) as unknown as typeof fetch;

    await expect(loadActivity("/activity.json", fetchImpl)).rejects.toBeInstanceOf(
      LedgerLoadError,
    );
  });

  it("throws LedgerLoadError when body is HTML even without content-type", async () => {
    const html = "<!DOCTYPE html><html><body>SPA</body></html>";
    const fetchImpl = vi.fn(async () =>
      new Response(html, { status: 200 }),
    ) as unknown as typeof fetch;

    await expect(loadActivity("/activity.json", fetchImpl)).rejects.toBeInstanceOf(
      LedgerLoadError,
    );
  });

  it("throws LedgerLoadError on invalid JSON", async () => {
    const fetchImpl = vi.fn(async () =>
      new Response("{not-json", {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    ) as unknown as typeof fetch;

    await expect(loadActivity("/activity.json", fetchImpl)).rejects.toBeInstanceOf(
      LedgerLoadError,
    );
  });

  it("throws LedgerLoadError when JSON is not an activity shape", async () => {
    const fetchImpl = vi.fn(async () =>
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    ) as unknown as typeof fetch;

    await expect(loadActivity("/activity.json", fetchImpl)).rejects.toBeInstanceOf(
      LedgerLoadError,
    );
  });
});
