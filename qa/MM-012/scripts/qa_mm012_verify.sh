#!/usr/bin/env bash
# Independent QA harness for MM-012 (PR #14). Read-only vs product tree.
# Usage (from a checkout of the PR head):
#   ./qa/MM-012/scripts/qa_mm012_verify.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
OUT="${QA_OUT:-$ROOT/qa/MM-012/logs/$(git -C "$ROOT" rev-parse --short HEAD)}"
mkdir -p "$OUT"

echo "ROOT=$ROOT"
echo "HEAD=$(git -C "$ROOT" rev-parse HEAD)" | tee "$OUT/HEAD.txt"
export PATH="${HOME}/.local/bin:${PATH}"

(
  cd "$ROOT"
  python3 -m pytest -q | tee "$OUT/pytest.txt"
  npm run typecheck | tee "$OUT/typecheck-root.txt"
  (cd web && npm run typecheck) | tee "$OUT/typecheck-web.txt"
  (cd web && npm test) | tee "$OUT/vitest.txt"
  (cd web && npm run build) | tee "$OUT/build.txt"
  make refresh-demo | tee "$OUT/refresh-demo.txt"
)

echo "Automated checks complete → $OUT"
echo "Start UI: cd web && npm run dev"
echo "Then: NODE_PATH=/path/to/playwright node qa/MM-012/scripts/qa_mm012_playwright.mjs"
