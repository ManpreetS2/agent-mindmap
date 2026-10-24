import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { Observability } from "@shared/observability";

export const FIXTURE_NAMES = [
  "demo", "live-mixed", "live-all-unknown", "live-collector-down", "reader-other-owner",
] as const;

export function loadFixture(name: string): Observability {
  return JSON.parse(
    readFileSync(resolve(process.cwd(), "../fixtures/observability", `${name}.json`), "utf8"),
  );
}
