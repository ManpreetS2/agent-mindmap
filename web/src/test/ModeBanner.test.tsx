import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ModeBanner } from "../components/ModeBanner";

describe("ModeBanner", () => {
  it("shows LIVE for live mode", () => {
    render(<ModeBanner mode="live" />);
    expect(screen.getByRole("status")).toHaveAttribute("data-mode", "live");
    expect(screen.getByText(/LIVE MODE/i)).toBeInTheDocument();
  });

  it("shows DEMO for demo mode", () => {
    render(<ModeBanner mode="demo" />);
    expect(screen.getByRole("status")).toHaveAttribute("data-mode", "demo");
    expect(screen.getByText(/DEMO MODE/i)).toBeInTheDocument();
  });
});
