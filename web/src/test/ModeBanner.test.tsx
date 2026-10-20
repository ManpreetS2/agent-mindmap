import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ModeBanner } from "../components/ModeBanner";

describe("ModeBanner", () => {
  it("shows LIVE for live mode", () => {
    render(<ModeBanner state="live" />);
    expect(screen.getByRole("status")).toHaveAttribute("data-mode", "live");
    expect(screen.getByText(/LIVE MODE/i)).toBeInTheDocument();
  });

  it("shows DEMO for demo mode", () => {
    render(<ModeBanner state="demo" />);
    expect(screen.getByRole("status")).toHaveAttribute("data-mode", "demo");
    expect(screen.getByText(/DEMO MODE/i)).toBeInTheDocument();
  });

  it("shows LOADING while mode is unresolved", () => {
    render(<ModeBanner state="loading" />);
    expect(screen.getByRole("status")).toHaveAttribute("data-mode", "loading");
    expect(screen.getByText(/LOADING MODE/i)).toBeInTheDocument();
  });

  it("shows UNKNOWN when healthz mode is missing or invalid", () => {
    render(<ModeBanner state="unknown" />);
    expect(screen.getByRole("status")).toHaveAttribute("data-mode", "unknown");
    expect(screen.getByText(/UNKNOWN MODE/i)).toBeInTheDocument();
  });
});
