import type { Observability } from "@shared/observability";
import demo from "../../../fixtures/observability/demo.json";
import liveMixed from "../../../fixtures/observability/live-mixed.json";
import liveAllUnknown from "../../../fixtures/observability/live-all-unknown.json";
import liveCollectorDown from "../../../fixtures/observability/live-collector-down.json";
import readerOtherOwner from "../../../fixtures/observability/reader-other-owner.json";

export const FIXTURE_NAMES = [
  "demo",
  "live-mixed",
  "live-all-unknown",
  "live-collector-down",
  "reader-other-owner",
] as const;

const FIXTURES: Record<(typeof FIXTURE_NAMES)[number], Observability> = {
  demo: demo as Observability,
  "live-mixed": liveMixed as Observability,
  "live-all-unknown": liveAllUnknown as Observability,
  "live-collector-down": liveCollectorDown as Observability,
  "reader-other-owner": readerOtherOwner as Observability,
};

export function loadFixture(name: string): Observability {
  const doc = FIXTURES[name as keyof typeof FIXTURES];
  if (!doc) throw new Error(`Unknown observability fixture: ${name}`);
  return structuredClone(doc);
}
