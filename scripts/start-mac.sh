#!/usr/bin/env bash
# MM-020-OPS: one-command Mac startup for mindmap live (127.0.0.1).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PORT="${MINDMAP_PORT:-8787}"
REBUILD=false

usage() {
  cat <<'EOF'
Usage: scripts/start-mac.sh [OPTIONS]

Start the MINDMAP live daemon on http://127.0.0.1:8787 (override with MINDMAP_PORT).

Options:
  --help      Show this help and exit.
  --rebuild   Force `npm ci` + `npm run build` in web/ even if web/dist exists.
  --demo      Reserved (MM-020i); not implemented yet.

Environment:
  MINDMAP_LEDGER   Path to task-ledger.md (if unset, ledger is read from gh:data/ledger).
  MINDMAP_PORT     Listen port (default 8787).

Prerequisites: Python 3.12+, Node 20+ (when a web build is needed), and `gh` logged in
for live GitHub polling (this script never runs `gh auth login`).

Stop: Ctrl+C in the terminal, or `launchctl bootout` when using launchd.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --help | -h)
      usage
      exit 0
      ;;
    --rebuild)
      REBUILD=true
      shift
      ;;
    --demo)
      echo "not yet supported (MM-020i)" >&2
      exit 2
      ;;
    *)
      echo "error: unknown option: $1 (try --help)" >&2
      exit 2
      ;;
  esac
done

find_bootstrap_python() {
  local candidate
  for candidate in python3.13 python3.12; do
    if command -v "$candidate" >/dev/null 2>&1; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

ensure_venv_python() {
  local py bootstrap
  if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
    py="$REPO_ROOT/.venv/bin/python"
  else
    if ! bootstrap="$(find_bootstrap_python)"; then
      echo "error: Python 3.12+ is required but python3.13/python3.12 was not found on PATH." >&2
      echo "Install with: brew install python@3.12" >&2
      exit 1
    fi
    "$bootstrap" -m venv "$REPO_ROOT/.venv"
    "$REPO_ROOT/.venv/bin/pip" install -q -e '.[dev]'
    py="$REPO_ROOT/.venv/bin/python"
  fi

  local major minor
  major="$("$py" -c 'import sys; print(sys.version_info.major)')"
  minor="$("$py" -c 'import sys; print(sys.version_info.minor)')"
  if [[ "$major" -lt 3 ]] || [[ "$major" -eq 3 && "$minor" -lt 12 ]]; then
    echo "error: mindmap requires Python 3.12+ (interpreter reports ${major}.${minor})" >&2
    exit 1
  fi
  echo "$py"
}

ensure_web_dist() {
  if [[ "$REBUILD" == true ]] || [[ ! -f "$REPO_ROOT/web/dist/index.html" ]]; then
    if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
      echo "error: Node.js and npm are required to build web/dist (install Node 20+)." >&2
      exit 1
    fi
    (
      cd "$REPO_ROOT/web"
      npm ci
      npm run build
    )
  fi
}

check_port_free() {
  if command -v lsof >/dev/null 2>&1; then
    if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
      echo "error: port $PORT is already in use:" >&2
      lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >&2 || true
      exit 1
    fi
  fi
}

require_gh_auth() {
  if ! command -v gh >/dev/null 2>&1; then
    echo "error: GitHub CLI (gh) is required for live mode (brew install gh)." >&2
    exit 1
  fi
  if ! gh auth status >/dev/null 2>&1; then
    echo "error: gh is not authenticated. Run 'gh auth login' yourself (this script will not)." >&2
    exit 1
  fi
}

PYTHON="$(ensure_venv_python)"
ensure_web_dist
check_port_free

LIVE_ARGS=(
  -m ingest.live
  --port "$PORT"
  --static-dir "$REPO_ROOT/web/dist"
)

if [[ -n "${MINDMAP_LEDGER:-}" ]]; then
  if [[ ! -f "$MINDMAP_LEDGER" ]]; then
    echo "error: MINDMAP_LEDGER file not found: $MINDMAP_LEDGER" >&2
    exit 1
  fi
  LIVE_ARGS+=(--ledger "$MINDMAP_LEDGER")
else
  LIVE_ARGS+=(--ledger-source gh)
fi

# Live daemon polls GitHub PRs and data/events via gh (read-only).
require_gh_auth

exec "$PYTHON" "${LIVE_ARGS[@]}"
