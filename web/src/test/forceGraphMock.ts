import { vi } from "vitest";

const chain = (): Record<string, unknown> => {
  const f: Record<string, unknown> = {};
  for (const k of ["strength", "distance", "distanceMax", "iterations"]) f[k] = () => f;
  return f;
};

/** Recorder for the mocked react-force-graph-2d (latest props + imperative calls). */
export const fgMock = {
  props: {} as Record<string, unknown>,
  renders: 0,
  methods: {
    d3Force: vi.fn(() => chain()),
    emitParticle: vi.fn(),
    zoomToFit: vi.fn(),
    d3ReheatSimulation: vi.fn(),
    centerAt: vi.fn(),
    zoom: vi.fn(),
  },
  reset() {
    this.props = {};
    this.renders = 0;
    for (const m of Object.values(this.methods)) (m as ReturnType<typeof vi.fn>).mockClear();
  },
};
