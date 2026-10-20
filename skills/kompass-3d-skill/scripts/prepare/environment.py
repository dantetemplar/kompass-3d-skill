"""Validate explicit preparation paths without importing the native binding."""
from __future__ import annotations

import os
from pathlib import Path


def validate_environment(install: Path) -> None:
    """Both preparation commands use the same selected SDK environment as macros."""
    bin_dir = (install / "Bin").resolve()
    for variable in ("PYTHONPATH", "LD_LIBRARY_PATH"):
        entries = [Path(item).resolve() for item in os.environ.get(variable, "").split(os.pathsep) if item]
        shadowing = next((entry for entry in entries if (entry / "ksapi.py").is_file()), None) if variable == "PYTHONPATH" else None
        if shadowing is not None and shadowing != bin_dir:
            raise ValueError(f"PYTHONPATH resolves ksapi from {shadowing}, not the selected {bin_dir}")
        if bin_dir not in entries:
            raise ValueError(
                f"{variable} does not contain the selected installation's Bin: {bin_dir}. "
                f"Export {variable}=\"{bin_dir}${{{variable}:+:${variable}}}\" before running preparation."
            )


def validate_output(output: Path, install: Path) -> None:
    """Never overwrite installed SDK sources or write through output symlinks."""
    resolved = output.resolve()
    installation = install.resolve()
    if resolved == installation or installation in resolved.parents:
        raise ValueError(f"Output must not be inside the SDK installation: {output}")
    if resolved == Path("/opt") or Path("/opt") in resolved.parents:
        raise ValueError(f"Preparation does not write to /opt: {output}")
    for parent in (output.absolute(), *output.absolute().parents):
        if parent.is_symlink():
            raise ValueError(f"Refusing output symlink: {parent}")
