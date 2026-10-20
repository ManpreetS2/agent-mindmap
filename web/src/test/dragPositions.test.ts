import { afterEach, describe, expect, it } from "vitest";
import {
  DRAG_POSITIONS_KEY,
  applyDragPositions,
  loadDragPositions,
  saveDragPositions,
} from "../utils/dragPositions";

describe("dragPositions (QA-MM020g-3)", () => {
  afterEach(() => {
    localStorage.removeItem(DRAG_POSITIONS_KEY);
  });

  it("round-trips positions through localStorage", () => {
    saveDragPositions({ director: { x: 188, y: 313 } });
    expect(loadDragPositions()).toEqual({ director: { x: 188, y: 313 } });
  });

  it("ignores corrupt storage", () => {
    localStorage.setItem(DRAG_POSITIONS_KEY, "{not-json");
    expect(loadDragPositions()).toEqual({});
  });

  it("applies persisted coords onto agent nodes only", () => {
    const nodes = [
      { id: "group:build", type: "groupAnchor", position: { x: 0, y: 0 } },
      { id: "director", type: "agent", position: { x: 10, y: 10 } },
    ];
    const next = applyDragPositions(nodes, { director: { x: 99, y: 77 } });
    expect(next[0].position).toEqual({ x: 0, y: 0 });
    expect(next[1].position).toEqual({ x: 99, y: 77 });
  });
});
