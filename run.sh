#!/bin/bash
# Run Aliasx from source (no build). Pass --selftest for the checks.
set -euo pipefail
cd "$(dirname "$0")"

if [ -x venv/bin/python ]; then
  PY="venv/bin/python"
else
  PY="python3"
fi

exec "$PY" aliasx.py "$@"
