#!/usr/bin/env bash
# MM-020-OPS: one-command Mac startup for mindmap live (127.0.0.1).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PORT="${MINDMAP_PORT:-8787}"
REBUILD=false
DEMO_MODE=false

usage() {
  cat <<'EOF'
Usage: scripts/start-mac.sh [OPTIONS]

Start the MINDMAP live daemon on http://127.0.0.1:8787 (override with MINDMAP_PORT).

Options:
  --help      Show this help and exit.
  --rebuild   Force `npm ci` + `npm run build` in web/ even if web/dist exists.
  --demo      Demo mode (MM-020i) when ingest.live supports --demo.

Environment:
  MINDMAP_LEDGER          Path to task-ledger.md (if unset, ledger is read from gh:data/ledger).
  MINDMAP_PORT            Listen port (default 8787).
  MINDMAP_EVENTS_SOURCE   gh (default) or off — passed to ingest.live as --events-source.

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
      DEMO_MODE=true
      shift
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

venv_health_ok() {
  local py="$1"
  [[ -x "$py" ]] || return 1
  "$py" -c 'import sys
assert sys.version_info >= (3, 12)
import ingest, jsonschema
' 2>/dev/null
}

install_venv_deps() {
  local pip="$REPO_ROOT/.venv/bin/python"
  "$pip" -m pip install -q --require-hashes -r "$REPO_ROOT/requirements-dev.txt"
  "$pip" -m pip install -q --no-deps -e "$REPO_ROOT"
}

ensure_venv_python() {
  local py="$REPO_ROOT/.venv/bin/python"
  local bootstrap

  if venv_health_ok "$py"; then
    echo "$py"
    return 0
  fi

  if [[ -d "$REPO_ROOT/.venv" ]]; then
    echo "mindmap: .venv failed health check (import ingest/jsonschema); recreating" >&2
    rm -rf "$REPO_ROOT/.venv"
  fi

  if ! bootstrap="$(find_bootstrap_python)"; then
    echo "error: Python 3.12+ is required but python3.13/python3.12 was not found on PATH." >&2
    echo "Install with: brew install python@3.12" >&2
    exit 1
  fi

  "$bootstrap" -m venv "$REPO_ROOT/.venv"
  install_venv_deps

  py="$REPO_ROOT/.venv/bin/python"
  if ! venv_health_ok "$py"; then
    echo "error: venv install failed health check (import ingest/jsonschema on Python 3.12+)" >&2
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

port_listening() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1
    return $?
  fi
  local py="$REPO_ROOT/.venv/bin/python"
  "$py" -c "import socket, sys
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    s.bind(('127.0.0.1', int(sys.argv[1])))
except OSError:
    sys.exit(0)
finally:
    s.close()
sys.exit(1)
" "$PORT"
}

check_port_free() {
  if port_listening; then
    echo "mindmap: port ${PORT} is already in use; exiting (launchd ThrottleInterval limits restart churn)" >&2
    if command -v lsof >/dev/null 2>&1; then
      lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >&2 || true
    else
      echo "mindmap: install lsof for process details, or check listeners on 127.0.0.1:${PORT}" >&2
    fi
    exit 1
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

resolve_events_source() {
  local raw="${MINDMAP_EVENTS_SOURCE:-gh}"
  case "$raw" in
    gh | off) echo "$raw" ;;
    *)
      echo "error: MINDMAP_EVENTS_SOURCE must be 'gh' or 'off' (got: ${raw})" >&2
      exit 1
      ;;
  esac
}

# ----- MM-020i: explicit --demo passthrough (ingest.live --demo) -----
apply_demo_flag() {
  [[ "$DEMO_MODE" == true ]] || return 0
  LIVE_ARGS+=(--demo)
}
# ----- end MM-020i -----

PYTHON="$(ensure_venv_python)"
ensure_web_dist
check_port_free

EVENTS_SOURCE="$(resolve_events_source)"

LIVE_ARGS=(
  -m ingest.live
  --port "$PORT"
  --static-dir "$REPO_ROOT/web/dist"
)

if [[ "$DEMO_MODE" == true ]]; then
  LIVE_ARGS+=(--events-source off)
else
  LIVE_ARGS+=(--events-source "$EVENTS_SOURCE")
fi

if [[ -n "${MINDMAP_LEDGER:-}" ]]; then
  if [[ ! -f "$MINDMAP_LEDGER" ]]; then
    echo "error: MINDMAP_LEDGER file not found: $MINDMAP_LEDGER" >&2
    exit 1
  fi
  LIVE_ARGS+=(--ledger "$MINDMAP_LEDGER")
else
  LIVE_ARGS+=(--ledger-source gh)
fi

apply_demo_flag

if [[ "$DEMO_MODE" != true ]]; then
  # Live daemon polls GitHub PRs and data/events via gh (read-only).
  require_gh_auth
fi

exec "$PYTHON" "${LIVE_ARGS[@]}"
