import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}

globalThis.ResizeObserver = ResizeObserverMock;

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
