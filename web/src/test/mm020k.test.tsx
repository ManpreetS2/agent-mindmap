import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { Activity, Event } from "@shared/types";
import { MindmapView } from "../views/MindmapView";
import { collectGroupIds, groupsForNode } from "../utils/groupMembership";
import {
  EMPTY_FILTERS,
  filterTimelineEvents,
  uniqueRepos,
} from "../utils/timelineFilters";
import { ledgerStatusBanner, partialGithubBanner } from "../utils/viewState";
import { renderMindmap } from "./renderMindmap";
import fixture from "../../../fixtures/sample-activity.json";

const sample = fixture as unknown as Activity;

describe("MM-020k UI (QA-MM020g)", () => {
  it("g-2: collectGroupIds is exactly three team groups (no Owner frame)", () => {
    const ids = collectGroupIds(sample.nodes);
    expect(ids).toEqual(["build", "qr", "radar"]);
    const manpreet = sample.nodes.find((n) => n.id === "manpreet")!;
    expect(groupsForNode(manpreet)).toEqual([]);
  });

  it("g-5: bug-fixer groups empty and home is build", () => {
    const bf = sample.nodes.find((n) => n.id === "bug-fixer")!;
    expect(bf.group).toBe("build");
    expect(bf.groups).toEqual([]);
  });

  it("g-7: header shows agent-mindmap as app name", () => {
    renderMindmap(<MindmapView activity={sample} />);
    expect(screen.getByTestId("app-name")).toHaveTextContent("agent-mindmap");
  });

  it("g-7: repo filter chips and timeline repo tags", async () => {
    const user = userEvent.setup();
    renderMindmap(<MindmapView activity={sample} />);
    const chips = screen.getAllByRole("button", { name: /agent-mindmap|fencepost/i });
    expect(chips.length).toBeGreaterThan(0);
    await user.click(chips[0]);
    // Filtering by one repo still leaves the chip pressed.
    expect(chips[0]).toHaveAttribute("aria-pressed", "true");
  });

  it("g-7: uniqueRepos + filterTimelineEvents by repo", () => {
    const events = sample.events as Event[];
    const repos = uniqueRepos(events);
    expect(repos.length).toBeGreaterThan(0);
    const one = repos[0];
    const filtered = filterTimelineEvents(
      events,
      { ...EMPTY_FILTERS, repos: new Set([one]) },
      new Set(sample.nodes.map((n) => n.id)),
    );
    expect(filtered.every((e) => e.repo === one)).toBe(true);
  });

  it("g-1: director/architect appear once with multi-group membership", () => {
    expect(sample.nodes.filter((n) => n.id === "director")).toHaveLength(1);
    expect(sample.nodes.filter((n) => n.id === "architect")).toHaveLength(1);
    const d = sample.nodes.find((n) => n.id === "director")!;
    expect(new Set(d.groups)).toEqual(new Set(["build", "qr", "radar"]));
  });

  it("g-4: sample has message edges", () => {
    expect(sample.edges.some((e) => e.type === "message")).toBe(true);
  });

  it("self-test: empty / partial / errored source banners", () => {
    expect(partialGithubBanner({ github: "ok" })).toBeNull();
    expect(partialGithubBanner({ github: "never_run" })).toMatch(/never run/i);
    expect(partialGithubBanner({ github: "error" })).toMatch(/GitHub \(error\)/);
    expect(ledgerStatusBanner({ github: "ok", ledger: "ok" })).toBeNull();
    expect(ledgerStatusBanner({ github: "ok", ledger: "unavailable" })).toMatch(
      /Ledger unavailable/i,
    );
    expect(ledgerStatusBanner({ github: "ok", ledger: "error" })).toMatch(
      /Ledger \(error\)/i,
    );
  });
});
