import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { SourceHealthBar } from "../components/SourceHealthBar";
import { loadFixture } from "./obsFixtures";

const ok = (n: string) => ({ status: "ok" as const, data: loadFixture(n) });
const at = (n: string, off = 60_000) => Date.parse(loadFixture(n).generated_at) + off;

describe("SourceHealthBar", () => {
  it("absent => source health unavailable", () => {
    render(<SourceHealthBar state={{ status: "absent" }} nowMs={0} />);
    expect(screen.getByText(/Source health unavailable/)).toBeTruthy();
  });
  it("rejected => observability unavailable", () => {
    render(<SourceHealthBar state={{ status: "rejected", reason: "bad" }} nowMs={0} />);
    expect(screen.getByText(/observability unavailable/)).toBeTruthy();
  });
  it("demo is unmistakable and never says verified", () => {
    const { container } = render(<SourceHealthBar state={ok("demo")} nowMs={at("demo")} />);
    expect(screen.getByText(/DEMO — SYNTHETIC DATA/)).toBeTruthy();
    expect(container.textContent!.toLowerCase()).not.toContain("verified");
  });
  it("live-mixed publisher, owned by this machine", () => {
    render(<SourceHealthBar state={ok("live-mixed")} nowMs={at("live-mixed")} />);
    expect(screen.getByText(/Mac B · publisher/)).toBeTruthy();
    expect(screen.getByText(/owned by this machine/)).toBeTruthy();
    expect(screen.getByText(/connected/)).toBeTruthy();
  });
  it("collector down", () => {
    render(<SourceHealthBar state={ok("live-collector-down")} nowMs={at("live-collector-down")} />);
    expect(screen.getByText(/unavailable/)).toBeTruthy();
  });
  it("reader on other owner", () => {
    render(<SourceHealthBar state={ok("reader-other-owner")} nowMs={at("reader-other-owner")} />);
    expect(screen.getByText(/reader/)).toBeTruthy();
    expect(screen.getByText(/another machine owns publishing/)).toBeTruthy();
  });
  it("all-unknown renders", () => {
    render(<SourceHealthBar state={ok("live-all-unknown")} nowMs={at("live-all-unknown")} />);
    expect(screen.getByTestId("source-health")).toBeTruthy();
  });
  it("old document is marked stale", () => {
    render(<SourceHealthBar state={ok("live-mixed")} nowMs={at("live-mixed", 3_600_000)} />);
    expect(screen.getByText(/document is stale/)).toBeTruthy();
  });
});
