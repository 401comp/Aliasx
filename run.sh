#!/bin/bash
# Run Aliasx from source (no build). Pass --selftest for the checks.
set -euo pipefail
cd "$(dirname "$0")"

if [ -x venv/bin/python ]; then
  PY="venv/bin/python"
elif [ -x /usr/local/opt/python@3.14/bin/python3 ]; then
  PY="/usr/local/opt/python@3.14/bin/python3"
elif [ -x /opt/homebrew/opt/python@3.14/bin/python3 ]; then
  PY="/opt/homebrew/opt/python@3.14/bin/python3"
else
  PY="python3"
fi

exec "$PY" aliasx.py "$@"
