/** Independent QA. Optional imports keep the tests collectible before UI integration. */
import type { ComponentType } from "react";
import { describe, expect, it } from "vitest";
import { render, within } from "@testing-library/react";
import type { Activity } from "@shared/types";
import type { Observability, QuotaStatus } from "@shared/observability";
import liveFixture from "../../../fixtures/observability/live-mixed.json";
import demoFixture from "../../../fixtures/observability/demo.json";
import { sessionNode, t3Activity } from "./helpers";
import shellCss from "../styles/shell.css?inline";

const loaders = import.meta.glob([
  "../components/QuotaPanel.tsx",
  "../utils/recommendations.ts",
  "../data/observabilityTransport.ts",
]);
const quota = loaders["../components/QuotaPanel.tsx"]
  ? await loaders["../components/QuotaPanel.tsx"]() as { QuotaPanel: ComponentType<{ state: { status: "ok"; data: Observability }; nowMs: number }> }
  : null;
const recommendations = loaders["../utils/recommendations.ts"]
  ? await loaders["../utils/recommendations.ts"]() as { recommend: (a: Activity, d: Observability | null, now: number) => { status: string; candidates: unknown[] } }
  : null;
const transport = loaders["../data/observabilityTransport.ts"]
  ? await loaders["../data/observabilityTransport.ts"]() as {
      createObservabilityPollTransport: (o: { fetchImpl: typeof fetch }) => {
        fetch: () => Promise<{ kind: string; data?: Observability }>;
      };
    }
  : null;

const NOW = Date.parse("2026-10-24T07:01:00Z");
function doc(): Observability { return structuredClone(liveFixture) as Observability; }
function activity(): Activity {
  return { ...t3Activity([sessionNode("qa-session")]), generated_at: new Date(NOW).toISOString() };
}
function onlyCodex(): Observability {
  const d = doc();
  for (const pool of d.quota.pools) {
    if (pool.id !== "codex") { pool.status = "UNKNOWN"; pool.windows = []; }
  }
  return d;
}
async function receive(d: Observability) {
  const fetchImpl = (async () => new Response(JSON.stringify(d), {
    status: 200, headers: { "Content-Type": "application/json" },
  })) as typeof fetch;
  return transport!.createObservabilityPollTransport({ fetchImpl }).fetch();
}

describe.skipIf(!quota || !recommendations || !transport)("independent observability attacks", () => {
  const Panel = quota?.QuotaPanel as NonNullable<typeof quota>["QuotaPanel"];

  it.each(["UNKNOWN", "STALE", "UNSUPPORTED", "ERROR"] as QuotaStatus[])(
    "%s with injected numeric windows has no meter or verified green badge", (status) => {
      const d = doc();
      for (const pool of d.quota.pools) {
        pool.status = status;
        pool.windows = structuredClone(d.quota.pools[4].windows);
      }
      const { container } = render(<><style>{shellCss}</style><Panel state={{ status: "ok", data: d }} nowMs={NOW} /></>);
      for (const card of container.querySelectorAll(".quota-card")) {
        expect(within(card as HTMLElement).queryAllByRole("meter")).toHaveLength(0);
        expect(card.querySelector(".quota-meter, .quota-badge--verified")).toBeNull();
        const badge = card.querySelector(".quota-badge")!;
        expect(getComputedStyle(badge).color).not.toBe("rgb(143, 227, 181)");
      }
    },
  );

  it("expiry at the exact current time removes all bars", () => {
    const d = doc();
    for (const p of d.quota.pools) p.expires_at = new Date(NOW).toISOString();
    const { container } = render(<Panel state={{ status: "ok", data: d }} nowMs={NOW} />);
    expect(container.querySelectorAll('[role="meter"]')).toHaveLength(0);
    expect(container.querySelector(".quota-badge--verified")).toBeNull();
  });

  it("synthetic demo is labelled and cannot produce actionable recommendations", () => {
    const d = structuredClone(demoFixture) as Observability;
    const { container } = render(<Panel state={{ status: "ok", data: d }} nowMs={Date.parse(d.generated_at)} />);
    expect(container.textContent).toContain("DEMO");
    expect(container.querySelector(".quota-badge--verified")).toBeNull();
    expect(recommendations!.recommend(activity(), d, NOW).status).toBe("INSUFFICIENT_DATA");
  });

  it("QA-013: demo flag must override a forged VERIFIED pool", () => {
    const d = doc(); d.mode = "demo";
    const { container } = render(<Panel state={{ status: "ok", data: d }} nowMs={NOW} />);
    expect(container.querySelector('[data-status="VERIFIED"]')).toBeNull();
    expect(container.querySelector(".quota-badge--verified")).toBeNull();
  });

  it.each(["UNKNOWN", "STALE", "ERROR", "UNSUPPORTED"] as QuotaStatus[])(
    "%s evidence never produces a recommendation", (status) => {
      const d = onlyCodex(); d.quota.pools[4].status = status;
      const result = recommendations!.recommend(activity(), d, NOW);
      expect(result.status).toBe("INSUFFICIENT_DATA");
      expect(result.candidates).toEqual([]);
    },
  );

  it.each(["missing-percentages", "missing-expiry", "missing-observation", "future-observation", "future-poll", "old-document"])(
    "QA-014: %s must return INSUFFICIENT_DATA", (attack) => {
      const d = onlyCodex(); const p = d.quota.pools[4];
      if (attack === "missing-percentages") for (const w of p.windows) { w.used_pct = null; w.remaining_pct = null; }
      if (attack === "missing-expiry") p.expires_at = null;
      if (attack === "missing-observation") p.observed_at = null;
      if (attack === "future-observation") p.observed_at = new Date(NOW + 86400_000).toISOString();
      if (attack === "future-poll") d.collector.last_t3_poll = new Date(NOW + 86400_000).toISOString();
      if (attack === "old-document") d.generated_at = new Date(NOW - 86400_000).toISOString();
      const result = recommendations!.recommend(activity(), d, NOW);
      expect(result.status).toBe("INSUFFICIENT_DATA");
      expect(result.candidates).toEqual([]);
    },
  );

  it.each(["/Users/qa/private", "qa@example.invalid", "Bearer syntheticcredential123"])(
    "QA-015: transport-to-DOM boundary must exclude private metadata: %s", async (privateValue) => {
      const d = onlyCodex();
      d.quota.pools[4].source.method = privateValue;
      const result = await receive(d);
      if (result.kind === "rejected") return;
      expect(result.kind).toBe("ok");
      const { container } = render(<Panel state={{ status: "ok", data: result.data! }} nowMs={NOW} />);
      expect(container.outerHTML).not.toContain(privateValue);
    },
  );

  it("QA-016: null quota window must be rejected before rendering can crash", async () => {
    const d = onlyCodex();
    d.quota.pools[4].windows = [null] as unknown as Observability["quota"]["pools"][number]["windows"];
    expect((await receive(d)).kind).toBe("rejected");
  });
});
