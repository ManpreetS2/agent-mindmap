#!/usr/bin/env bash
# MM-020-OPS: render com.manpreet.mindmap.plist for this machine (does not load launchd).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE="$REPO_ROOT/ops/com.manpreet.mindmap.plist"
RENDER="$REPO_ROOT/scripts/render_launchagent_plist.py"
LABEL="com.manpreet.mindmap"
LOG_DIR="${HOME}/Library/Logs/mindmap"
DEST="${HOME}/Library/LaunchAgents/${LABEL}.plist"

if [[ -z "${MINDMAP_LEDGER:-}" ]]; then
  echo "error: set MINDMAP_LEDGER to the absolute path of task-ledger.md before installing." >&2
  echo "  (Or customize the plist to use gh ledger mirror: unset MINDMAP_LEDGER and edit ProgramArguments.)" >&2
  exit 1
fi

if [[ ! -f "$MINDMAP_LEDGER" ]]; then
  echo "error: MINDMAP_LEDGER file not found: $MINDMAP_LEDGER" >&2
  exit 1
fi

mkdir -p "$LOG_DIR"
mkdir -p "${HOME}/Library/LaunchAgents"

python3 "$RENDER" \
  --template "$TEMPLATE" \
  --output "$DEST" \
  --repo-root "$REPO_ROOT" \
  --ledger "$MINDMAP_LEDGER" \
  --log-dir "$LOG_DIR"

if command -v plutil >/dev/null 2>&1; then
  plutil -lint "$DEST"
fi

echo "Wrote ${DEST}"
echo ""
echo "To load (not run automatically by this script):"
echo "  launchctl bootstrap gui/\$(id -u) \"${DEST}\""
echo ""
echo "To unload:"
echo "  launchctl bootout gui/\$(id -u)/${LABEL}"
