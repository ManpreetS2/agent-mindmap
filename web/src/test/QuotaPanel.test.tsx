import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { QuotaPanel } from "../components/QuotaPanel";
import { FIXTURE_NAMES, loadFixture } from "./obsFixtures";
import { evaluatePool } from "../utils/observabilityEval";

const ok = (n: string) => ({ status: "ok" as const, data: loadFixture(n) });
const near = (n: string, off = 60_000) => Date.parse(loadFixture(n).generated_at) + off;

describe("QuotaPanel", () => {
  it("absent => unavailable, no pool numbers", () => {
    const { container } = render(<QuotaPanel state={{ status: "absent" }} nowMs={0} />);
    expect(screen.getByTestId("quota-panel")).toHaveTextContent(/Quota unavailable/);
    expect(container.querySelectorAll('[role="meter"]')).toHaveLength(0);
  });

  it.each(FIXTURE_NAMES)("renders five separate cards for %s", (name) => {
    render(<QuotaPanel state={ok(name)} nowMs={near(name)} />);
    const panel = screen.getByTestId("quota-panel");
    for (const id of ["claude-1", "claude-2", "cursor-premium", "devin-free", "codex"]) {
      expect(within(panel).getByTestId(`quota-pool-${id}`)).toBeTruthy();
    }
    expect(panel.textContent).not.toMatch(/\btotal\b|\baverage\b/i);
    expect(panel.textContent).toMatch(/never combined/i);
  });

  it("demo never says verified and labels DEMO", () => {
    const { container } = render(<QuotaPanel state={ok("demo")} nowMs={near("demo")} />);
    expect(screen.getByText(/DEMO — illustrative/)).toBeTruthy();
    expect(container.textContent!.toLowerCase()).not.toContain("verified");
  });

  it("live-mixed: VERIFIED bars, STALE greyed, UNKNOWN/UNSUPPORTED no numbers", () => {
    const { container } = render(<QuotaPanel state={ok("live-mixed")} nowMs={near("live-mixed")} />);
    const c1 = screen.getByTestId("quota-pool-claude-1");
    expect(c1).toHaveAttribute("data-status", "VERIFIED");
    expect(within(c1).getAllByRole("meter").length).toBeGreaterThan(0);

    const c2 = screen.getByTestId("quota-pool-claude-2");
    expect(c2).toHaveAttribute("data-status", "STALE");
    expect(within(c2).queryAllByRole("meter")).toHaveLength(0);
    expect(c2.textContent).toMatch(/expired reading from/);

    const cursor = screen.getByTestId("quota-pool-cursor-premium");
    expect(cursor).toHaveAttribute("data-status", "UNSUPPORTED");
    expect(within(cursor).queryAllByRole("meter")).toHaveLength(0);
    expect(cursor.textContent).toMatch(/Usage is visible in Cursor/);
    expect(cursor.textContent).not.toMatch(/\d+(\.\d+)?%/);

    const unknown = screen.getByTestId("quota-pool-devin-free");
    expect(unknown).toHaveAttribute("data-status", "UNKNOWN");
    expect(within(unknown).queryAllByRole("meter")).toHaveLength(0);

    // No meters outside verified/manual cards
    for (const el of container.querySelectorAll('[data-status="STALE"], [data-status="UNKNOWN"], [data-status="UNSUPPORTED"], [data-status="ERROR"]')) {
      expect(el.querySelectorAll('[role="meter"]')).toHaveLength(0);
    }
  });

  it("client-side expiry downgrades VERIFIED when expires_at passed", () => {
    const doc = loadFixture("live-mixed");
    const c1 = doc.quota.pools.find((p) => p.id === "claude-1")!;
    expect(c1.status).toBe("VERIFIED");
    const afterExpiry = Date.parse(c1.expires_at!) + 1000;
    render(<QuotaPanel state={{ status: "ok", data: doc }} nowMs={afterExpiry} />);
    const card = screen.getByTestId("quota-pool-claude-1");
    expect(card).toHaveAttribute("data-status", "STALE");
    expect(within(card).queryAllByRole("meter")).toHaveLength(0);
    expect(card.className).toMatch(/client-expired/);
  });

  it("evaluatePool matches panel: reset time passed also stale", () => {
    const doc = loadFixture("live-mixed");
    const c1 = structuredClone(doc.quota.pools.find((p) => p.id === "claude-1")!);
    c1.expires_at = "2099-01-01T00:00:00Z";
    const afterReset = Date.parse(c1.windows[0].resets_at!) + 1000;
    const ev = evaluatePool(c1, afterReset);
    expect(ev.effectiveStatus).toBe("STALE");
    expect(ev.clientExpired).toBe(true);
  });

  it("collector-down ERROR pool shows reason, no meter", () => {
    render(<QuotaPanel state={ok("live-collector-down")} nowMs={near("live-collector-down")} />);
    const c2 = screen.getByTestId("quota-pool-claude-2");
    expect(c2).toHaveAttribute("data-status", "ERROR");
    expect(within(c2).queryAllByRole("meter")).toHaveLength(0);
    expect(c2.textContent).toMatch(/No readable status-line/);
  });

  it("all-unknown: five UNKNOWN cards with reasons", () => {
    render(<QuotaPanel state={ok("live-all-unknown")} nowMs={near("live-all-unknown")} />);
    for (const id of ["claude-1", "claude-2", "cursor-premium", "devin-free", "codex"]) {
      const card = screen.getByTestId(`quota-pool-${id}`);
      expect(card).toHaveAttribute("data-status", "UNKNOWN");
      expect(within(card).queryAllByRole("meter")).toHaveLength(0);
    }
  });
});
