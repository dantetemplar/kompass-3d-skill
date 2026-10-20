#!/usr/bin/env bash
# Запуск Python-макроса КОМПАС-3D v25 (Linux / KsAPI).
set -euo pipefail

BIN=/opt/ascon/kompas3d-v25/Bin
MACRO_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="${1:?укажи файл макроса, например hello_box.py}"

export LD_LIBRARY_PATH="$BIN${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PYTHONPATH="$BIN${PYTHONPATH:+:$PYTHONPATH}"
shift
exec uv run --script "$MACRO_DIR/$SCRIPT" "$@"
