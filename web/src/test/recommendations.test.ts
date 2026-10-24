import { describe, expect, it } from "vitest";
import { recommend, QUOTA_USED_PCT_LIMIT } from "../utils/recommendations";
import { loadFixture } from "./obsFixtures";
import { sessionNode, t3Activity } from "./helpers";
import type { Observability } from "@shared/observability";
import type { Activity } from "@shared/types";

const NOW = Date.parse("2026-10-24T07:01:00+00:00");

function liveActivity(extra: Partial<Activity> = {}): Activity {
  const base = t3Activity(
    [
      sessionNode("w", { status: "IN_PROGRESS", current_task: "Ship UI" }),
      sessionNode("b", { status: "BLOCKED", current_task: "Waiting on review" }),
      sessionNode("f", { status: "FAILED", current_task: "Build broke" }),
    ],
    [],
    "live",
  );
  return { ...base, generated_at: "2026-10-24T07:00:00+00:00", ...extra };
}

function withPool(
  doc: Observability,
  id: string,
  patch: Partial<Observability["quota"]["pools"][number]>,
): Observability {
  const next = structuredClone(doc);
  next.quota.pools = next.quota.pools.map((p) =>
    p.id === id ? { ...p, ...patch, windows: patch.windows ?? p.windows } : p,
  );
  return next;
}

describe("recommend()", () => {
  it("absent observability => INSUFFICIENT_DATA", () => {
    const r = recommend(liveActivity(), null, NOW);
    expect(r.status).toBe("INSUFFICIENT_DATA");
    expect(r.reasons[0]).toMatch(/absent/i);
    expect(r.candidates).toEqual([]);
  });

  it("demo => INSUFFICIENT_DATA labelled illustrative", () => {
    const r = recommend(liveActivity(), loadFixture("demo"), NOW);
    expect(r.status).toBe("INSUFFICIENT_DATA");
    expect(r.reasons.join(" ")).toMatch(/DEMO|illustrative/i);
    expect(r.candidates).toEqual([]);
  });

  it("collector down => INSUFFICIENT_DATA", () => {
    const r = recommend(liveActivity(), loadFixture("live-collector-down"), NOW);
    expect(r.status).toBe("INSUFFICIENT_DATA");
    expect(r.reasons.join(" ")).toMatch(/Collector/);
  });

  it("all-unknown => INSUFFICIENT_DATA (collector not fresh)", () => {
    const r = recommend(liveActivity(), loadFixture("live-all-unknown"), NOW);
    expect(r.status).toBe("INSUFFICIENT_DATA");
    expect(r.reasons.join(" ")).toMatch(/Collector/);
    expect(r.candidates).toEqual([]);
  });

  it("connected but no eligible pools => per-pool reasons", () => {
    const doc = loadFixture("live-mixed");
    // Force every pool unknown while keeping collector fresh
    for (const p of doc.quota.pools) {
      p.status = "UNKNOWN";
      p.windows = [];
      p.reason = "No sourced, timestamped reading";
      p.expires_at = null;
    }
    const r = recommend(liveActivity(), doc, NOW);
    expect(r.status).toBe("INSUFFICIENT_DATA");
    expect(r.reasons.length).toBe(5);
    expect(r.reasons.every((x) => /UNKNOWN/.test(x))).toBe(true);
  });

  it("stale activity => INSUFFICIENT_DATA", () => {
    const act = liveActivity();
    act.meta.t3!.connection = "unavailable";
    const r = recommend(act, loadFixture("live-mixed"), NOW);
    expect(r.status).toBe("INSUFFICIENT_DATA");
    expect(r.reasons.join(" ")).toMatch(/stale|unavailable/i);
  });

  it("live-mixed ranks codex before claude-1 (lower max used%)", () => {
    const r = recommend(liveActivity(), loadFixture("live-mixed"), NOW);
    expect(r.status).toBe("RECOMMENDATIONS");
    expect(r.candidates.map((c) => c.poolId)).toEqual(["codex", "claude-1"]);
    expect(r.candidates[0].rank).toBe(1);
    expect(r.candidates[0].evidence.some((e) => e.includes("used_pct=0"))).toBe(true);
    expect(r.candidates[0].limitations).toEqual(
      expect.arrayContaining([
        expect.stringMatching(/session\.account/),
        expect.stringMatching(/not proof of execution/),
        expect.stringMatching(/never combined/),
      ]),
    );
    expect(r.candidates.some((c) => c.poolId === "claude-2")).toBe(false);
  });

  it("used_pct at limit is ineligible", () => {
    let doc = loadFixture("live-mixed");
    doc = withPool(doc, "codex", {
      windows: [
        {
          type: "session",
          label: "5-hour",
          window_minutes: 300,
          used_pct: QUOTA_USED_PCT_LIMIT,
          remaining_pct: 15,
          resets_at: "2026-10-24T11:56:50+00:00",
        },
      ],
    });
    doc = withPool(doc, "claude-1", {
      status: "STALE",
      windows: [],
      reason: "forced out",
    });
    const r = recommend(liveActivity(), doc, NOW);
    expect(r.status).toBe("INSUFFICIENT_DATA");
    expect(r.reasons.some((x) => x.includes("codex") && x.includes(String(QUOTA_USED_PCT_LIMIT)))).toBe(true);
  });

  it("used_pct just under limit stays eligible", () => {
    let doc = loadFixture("live-mixed");
    doc = withPool(doc, "claude-1", { status: "UNKNOWN", windows: [], reason: "out" });
    doc = withPool(doc, "codex", {
      windows: [
        {
          type: "session",
          label: "5-hour",
          window_minutes: 300,
          used_pct: QUOTA_USED_PCT_LIMIT - 0.1,
          remaining_pct: 15.1,
          resets_at: "2026-10-24T11:56:50+00:00",
        },
      ],
    });
    const r = recommend(liveActivity(), doc, NOW);
    expect(r.status).toBe("RECOMMENDATIONS");
    expect(r.candidates.map((c) => c.poolId)).toEqual(["codex"]);
  });

  it("expiry boundary: VERIFIED becomes ineligible after expires_at", () => {
    const doc = loadFixture("live-mixed");
    const c1 = doc.quota.pools.find((p) => p.id === "claude-1")!;
    // Keep collector poll fresh relative to `after` so the failure is pool expiry, not collector.
    doc.collector.last_t3_poll = c1.expires_at;
    const after = Date.parse(c1.expires_at!) + 1;
    const expired = withPool(doc, "codex", { expires_at: c1.expires_at });
    const r = recommend(liveActivity(), expired, after);
    expect(r.status).toBe("INSUFFICIENT_DATA");
    expect(r.reasons.some((x) => x.includes("claude-1") && /expired/i.test(x))).toBe(true);
  });

  it("deterministic with fixed now", () => {
    const doc = loadFixture("live-mixed");
    const a = recommend(liveActivity(), doc, NOW);
    const b = recommend(liveActivity(), doc, NOW);
    expect(a).toEqual(b);
  });

  it("lists blockers separately from quota candidates", () => {
    const r = recommend(liveActivity(), loadFixture("live-mixed"), NOW);
    expect(r.blockers.map((b) => b.id).sort()).toEqual(["b", "f"]);
    expect(r.blockers.every((b) => b.status === "BLOCKED" || b.status === "FAILED")).toBe(true);
    expect(r.candidates.every((c) => !/switch account/i.test(c.label))).toBe(true);
  });

  it("unattributed Claude sessions do not contaminate pool ranking", () => {
    const act = liveActivity({
      nodes: [
        sessionNode("c1", { status: "IN_PROGRESS" }, { provider: "Claude Code", account: undefined }),
        sessionNode("c2", { status: "DONE" }, {
          provider: "Claude Code",
          account: { id: "claudeAgent_2", label: "Claude2" },
        }),
      ],
    });
    const r = recommend(act, loadFixture("live-mixed"), NOW);
    expect(r.status).toBe("RECOMMENDATIONS");
    // Ranking still by quota only — session.account never rewrites pool order
    expect(r.candidates.map((c) => c.poolId)).toEqual(["codex", "claude-1"]);
    expect(r.candidates[0].limitations.some((l) => /session\.account/.test(l))).toBe(true);
  });

  it("never suggests switch account wording in reasons/evidence", () => {
    const r = recommend(liveActivity(), loadFixture("live-mixed"), NOW);
    const blob = JSON.stringify(r).toLowerCase();
    expect(blob).not.toContain("switch account");
    expect(blob).not.toContain("dispatch");
    expect(blob).not.toContain("billing");
  });

  it("tie on used% breaks by fixed pool order", () => {
    let doc = loadFixture("live-mixed");
    const twinWindows = [
      {
        type: "session" as const,
        label: "5-hour",
        window_minutes: 300,
        used_pct: 10,
        remaining_pct: 90,
        resets_at: "2026-10-24T12:00:00+00:00",
      },
    ];
    doc = withPool(doc, "claude-1", { windows: twinWindows });
    doc = withPool(doc, "codex", { windows: twinWindows });
    const r = recommend(liveActivity(), doc, NOW);
    expect(r.candidates.map((c) => c.poolId)).toEqual(["claude-1", "codex"]);
  });
});
