#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Prepare installed SDK WebHelp for local browsing and SQLite FTS5 search."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from docs import prepare_docs
from environment import validate_environment, validate_output

DEFAULT_INSTALL = Path("/opt/ascon/kompas3d-v25")
DEFAULT_OUT = Path(__file__).resolve().parents[2] / ".cache" / "kompas-sdk-docs"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", type=Path, default=DEFAULT_INSTALL, help="KOMPAS installation directory")
    parser.add_argument("--sdk-help-zip", type=Path, help="Override the installed SDK Help archive")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Documentation cache directory (existing unrelated files are preserved)")
    args = parser.parse_args(argv)
    source = args.sdk_help_zip or args.install / "SDK" / "Help" / "KOMPAS_SDK_ru-RU.zip"
    if not source.is_file():
        parser.error(f"SDK help ZIP not found: {source}")
    try:
        validate_environment(args.install)
        validate_output(args.out, args.install)
        summary = prepare_docs(source, args.out, args.install)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return int(bool(summary["errors"]))


if __name__ == "__main__":
    raise SystemExit(main())
