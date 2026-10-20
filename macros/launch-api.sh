#!/usr/bin/env bash
# КОМПАС с APIServer — к нему цепляется GetKompas() / макросы.
set -euo pipefail
BIN=/opt/ascon/kompas3d-v25/Bin
PORT="${1:-10500}"
if (( $# > 0 )); then
  shift
fi
export LD_LIBRARY_PATH="$BIN${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export LC_ALL="${LC_ALL:-C.UTF-8}"
exec "$BIN/kKompas" -APIServer="$PORT" "$@"
