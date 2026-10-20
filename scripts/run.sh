#!/usr/bin/env bash
# Run a Python macro with the native Linux KsAPI libraries and modules.
set -euo pipefail
BIN="${KOMPAS_BIN:-/opt/ascon/kompas3d-v25/Bin}"
SCRIPT="${1:?Usage: bash run.sh /path/to/macro.py [arguments...]}"
shift
if [[ ! -f "$SCRIPT" ]]; then
  printf 'Macro not found: %s\n' "$SCRIPT" >&2
  exit 1
fi
export LD_LIBRARY_PATH="$BIN${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PYTHONPATH="$BIN${PYTHONPATH:+:$PYTHONPATH}"
exec uv run --script "$SCRIPT" "$@"
