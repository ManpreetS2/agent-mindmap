import "@testing-library/jest-dom/vitest";
import "vitest-axe/extend-expect";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";
import { forwardRef, useImperativeHandle } from "react";
import { vi } from "vitest";
import { fgMock } from "./forceGraphMock";

// The canvas force graph cannot render in jsdom: replace it with a recorder (see forceGraphMock.ts).
vi.mock("react-force-graph-2d", () => ({
  default: forwardRef(function ForceGraphStub(props: Record<string, unknown>, ref) {
    fgMock.props = props;
    fgMock.renders++;
    useImperativeHandle(ref, () => fgMock.methods as never);
    return <canvas data-testid="force-graph" />;
  }),
}));

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}

globalThis.ResizeObserver = ResizeObserverMock;

Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
});

Element.prototype.getBoundingClientRect = () => ({
  width: 1280,
  height: 720,
  top: 0,
  left: 0,
  bottom: 720,
  right: 1280,
  x: 0,
  y: 0,
  toJSON: () => ({}),
});

afterEach(() => {
  cleanup();
});
