#!/usr/bin/env bash
# Mirrors .github/workflows/python.yml "Run pytest" step
set -euo pipefail
collected="$(python -m pytest --collect-only -q "$@" 2>&1 | tee /dev/stderr | tail -n1)"
count="$(echo "$collected" | awk '/tests collected/ { print $1; exit }')"
if [ -z "${count:-}" ] || [ "$count" -lt 1 ]; then
  echo "Expected at least one test to be collected, got: ${count:-0}"
  exit 1
fi
echo "Collected $count tests"
python -m pytest -q "$@"
