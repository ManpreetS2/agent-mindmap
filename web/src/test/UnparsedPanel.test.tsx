import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { Event } from "@shared/types";
import { UnparsedPanel } from "../components/UnparsedPanel";

const line: Event = {
  id: "unparsed-1",
  type: "unparsed",
  actor: null,
  target: null,
  task_id: null,
  attribution: { method: "unknown" },
  source_url: "build/task-ledger.md",
  source_time: "1970-01-01T00:00:00-08:00",
  raw: "malformed line",
};

describe("UnparsedPanel debug drawer", () => {
  it("shows collapsed Debug toggle and Undated label when expanded", async () => {
    const user = userEvent.setup();
    render(<UnparsedPanel lines={[line]} />);
    expect(screen.getByRole("button", { name: "Debug (1)" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    await user.click(screen.getByRole("button", { name: "Debug (1)" }));
    expect(screen.getByText("Undated")).toBeInTheDocument();
    expect(screen.queryByText(/Jan 1/i)).not.toBeInTheDocument();
  });
});
