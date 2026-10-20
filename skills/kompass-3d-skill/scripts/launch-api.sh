#!/usr/bin/env bash
# Start a KOMPAS API session in the foreground; no document is opened.
set -euo pipefail
BIN="${KOMPAS_BIN:-/opt/ascon/kompas3d-v25/Bin}"
PORT="${1:-10500}"
if (( $# > 0 )); then
  shift
fi
if [[ ! "$PORT" =~ ^[0-9]{1,5}$ ]] || (( 10#$PORT < 1 || 10#$PORT > 65535 )); then
  printf 'Invalid API port: %s\n' "$PORT" >&2
  exit 1
fi
PORT=$((10#$PORT))
export LD_LIBRARY_PATH="$BIN${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export LC_ALL="${LC_ALL:-C.UTF-8}"
exec "$BIN/kKompas" -APIServer="$PORT" "$@"
