import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useNetworkPointer } from "../hooks/useNetworkPointer";
import type { GNode } from "../utils/networkModel";

function setup(provider: GNode["provider"]) {
  const n: GNode = { id: "a", label: "a", provider, providerName: provider, model: null, status: "IN_PROGRESS", reported: "running", task: null, active: true, stale: false, phase: 0, pinned: false, x: 100, y: 100, ox: 3, oy: 2 };
  const select = vi.fn(), end = vi.fn((node: GNode) => { node.pinned = true; node.fx = node.x; node.fy = node.y; });
  const fg = { current: { screen2GraphCoords: (x: number, y: number) => ({ x, y }) } } as never;
  const { result } = renderHook(() => useNetworkPointer({ fg, nodes: [n], onSelect: select, onHover: vi.fn(), onDragEnd: end, onDragging: vi.fn() }));
  const target = document.createElement("canvas");
  const host = { getBoundingClientRect: () => ({ left: 0, top: 0 }), setPointerCapture: vi.fn(), hasPointerCapture: () => true, releasePointerCapture: vi.fn() };
  const event = (x: number, y: number) => ({ button: 0, clientX: x, clientY: y, pointerId: 1, target, currentTarget: host, preventDefault: vi.fn(), stopPropagation: vi.fn() }) as unknown as React.PointerEvent<HTMLDivElement>;
  return { n, select, end, result, event };
}

describe("network pointer", () => {
  it("double-click releases a pin and consumes the camera zoom gesture", () => {
    const { n, result, event } = setup("claude");
    n.pinned = true; n.fx = 100; n.fy = 100;
    const click = event(100, 100);
    result.current.onDoubleClickCapture(click);
    expect([n.pinned, n.fx, n.fy]).toEqual([false, undefined, undefined]);
    expect(click.preventDefault).toHaveBeenCalled();
    expect(click.stopPropagation).toHaveBeenCalled();
  });
  it.each(["claude", "codex"] as const)("pins the visible %s position and does not click/pan after drag", provider => {
    const { n, result, event, select, end } = setup(provider);
    const down = event(103, 102);
    result.current.onPointerDownCapture(down);
    expect(down.preventDefault).toHaveBeenCalled();
    expect([n.x, n.y, n.fx, n.fy]).toEqual([103, 102, 103, 102]);
    n.active = false; n.status = "DONE"; // status poll during drag must not change its anchor
    result.current.onPointerMoveCapture(event(150, 160));
    result.current.onPointerUpCapture(event(150, 160));
    expect([n.x, n.y, n.fx, n.fy, n.pinned]).toEqual([150, 160, 150, 160, true]);
    expect(select).not.toHaveBeenCalled();
    expect(end).toHaveBeenCalledTimes(1);
  });

  it("treats under-five-pixel movement as click and restores the prior pin", () => {
    const { n, result, event, select, end } = setup("codex");
    result.current.onPointerDownCapture(event(103, 102));
    result.current.onPointerMoveCapture(event(105, 104));
    result.current.onPointerUpCapture(event(105, 104));
    expect(select).toHaveBeenCalledWith("a");
    expect(end).not.toHaveBeenCalled();
    expect(n.fx).toBeUndefined();
    expect(n.dragging).toBe(false);
    expect([n.x, n.y, n.ox, n.oy]).toEqual([100, 100, 3, 2]);
  });

  it("ignores controls and hexagon corner space", () => {
    const { n, result, event } = setup("codex");
    result.current.onPointerDownCapture(event(133, 132));
    expect(n.dragging).toBeUndefined();
    const control = event(103, 102);
    Object.defineProperty(control, "target", { value: document.createElement("button") });
    result.current.onPointerDownCapture(control);
    expect(n.dragging).toBeUndefined();
  });
});
