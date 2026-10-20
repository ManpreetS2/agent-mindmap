import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { Activity } from "@shared/types";
import { LedgerErrorView } from "../components/LedgerErrorView";
import { MindmapLoadingView } from "../components/MindmapLoadingView";
import { MindmapView } from "../views/MindmapView";
import { LEDGER_ERROR_PATH } from "../utils/viewState";
import emptyFixture from "../fixtures/state-empty.json";
import partialError from "../fixtures/state-partial-github-error.json";
import partialRate from "../fixtures/state-partial-github-rate-limited.json";
import partialSkipped from "../fixtures/state-partial-github-skipped.json";
import staleFixture from "../fixtures/state-stale.json";
import unparsedFixture from "../fixtures/state-unparsed.json";
import { renderMindmap } from "./renderMindmap";

const STALE_NOW = new Date("2026-10-20T12:00:00-07:00").getTime();

describe("UI states (MM-007)", () => {
  it("loading view shows ledger + GitHub message and skeletons", () => {
    render(<MindmapLoadingView />);
    expect(screen.getByText(/Reading ledger and GitHub/i)).toBeInTheDocument();
    expect(document.querySelectorAll(".skeleton-node").length).toBeGreaterThan(0);
  });

  it("empty fixture shows no-activity banner with idle graph nodes", () => {
    renderMindmap(<MindmapView activity={emptyFixture as Activity} />);
    expect(screen.getByText(/No activity recorded yet/i)).toBeInTheDocument();
    expect(screen.getByTestId("agent-node-director")).toBeInTheDocument();
  });

  it("empty fixture shows every bot as IDLE (QA-MM007-1)", () => {
    const data = emptyFixture as Activity;
    expect(data.nodes.length).toBeGreaterThan(0);
    for (const node of data.nodes) {
      expect(node.status).toBe("IDLE");
      expect(node.current_task).toBeUndefined();
    }
    renderMindmap(<MindmapView activity={data} />);
    const idlePills = screen.getAllByText("IDLE");
    expect(idlePills.length).toBe(data.nodes.length);
  });

  it("partial GitHub fixtures carry no GitHub events (QA-MM007-2)", () => {
    for (const partial of [partialError, partialSkipped, partialRate] as Activity[]) {
      for (const event of partial.events) {
        expect(event.source_url).not.toMatch(/github\.com/i);
      }
    }
  });

  it("partial GitHub error names the source in banner", () => {
    renderMindmap(<MindmapView activity={partialError as Activity} />);
    expect(
      document.querySelector(".partial-source-banner")?.textContent,
    ).toMatch(/GitHub \(error\)/i);
  });

  it("partial GitHub skipped names the source in banner", () => {
    renderMindmap(<MindmapView activity={partialSkipped as Activity} />);
    expect(
      document.querySelector(".partial-source-banner")?.textContent,
    ).toMatch(/GitHub \(skipped\)/i);
  });

  it("partial GitHub rate_limited names the source in banner", () => {
    renderMindmap(<MindmapView activity={partialRate as Activity} />);
    expect(
      document.querySelector(".partial-source-banner")?.textContent,
    ).toMatch(/rate limited/i);
  });

  it("stale generated_at shows age hint", () => {
    renderMindmap(
      <MindmapView
        activity={staleFixture as Activity}
        nowMs={STALE_NOW}
      />,
    );
    expect(screen.getByText(/stale/i)).toBeInTheDocument();
    expect(screen.getByText(/refresh/i)).toBeInTheDocument();
  });

  it("unparsed fixture renders debug drawer toggle", () => {
    renderMindmap(<MindmapView activity={unparsedFixture as Activity} />);
    expect(screen.getByRole("button", { name: /Debug \(\d+\)/ })).toBeInTheDocument();
  });

  it("ledger error view shows path and retry", async () => {
    const user = userEvent.setup();
    let retried = false;
    render(<LedgerErrorView onRetry={() => { retried = true; }} />);
    expect(screen.getByRole("alert")).toHaveTextContent(LEDGER_ERROR_PATH);
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(retried).toBe(true);
  });
});
