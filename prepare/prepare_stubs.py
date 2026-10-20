# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Generate native KOMPAS Python stubs offline, without importing native modules."""
from __future__ import annotations

import argparse
import ast
import json
from collections import Counter
from pathlib import Path

from emit import Documentation, emit_constants, emit_native
from native import NativeModel
from artifacts import atomic_write, file_identity, unknown_annotations, validate_documentation
from environment import validate_environment, validate_output

REPO = Path(__file__).resolve().parent.parent
DEFAULT_INSTALL = Path("/opt/ascon/kompas3d-v25")


def generate(install: Path, docs_path: Path, output: Path, metadata: Path | None = None) -> dict:
    validate_output(output, install)
    validate_documentation(docs_path, install)
    docs = Documentation(docs_path)
    bin_dir = install / "Bin"
    metadata = metadata or install / "SDK/KsAPIC/C/Include/KsAPIC.json"
    model = NativeModel(bin_dir / "ksapi.py", metadata)
    output.mkdir(parents=True, exist_ok=True)
    files = {"ksapi.pyi": emit_native(model, docs, output / "ksapi.pyi")}
    for name in ("constants", "constants3d"):
        files[name + ".pyi"] = emit_constants(bin_dir / (name + ".py"))
    for name, text in files.items():
        ast.parse(text, filename=name)
        atomic_write(output / name, text)
    reasons = Counter(d["reason"] for d in model.diagnostics)
    parameters = [typ for method in model.methods.values() for typ in method.arguments.values()]
    results = [method.result for method in model.methods.values()]
    identities = [file_identity(path) for path in [model.source, metadata, docs_path,
                  bin_dir / "constants.py", bin_dir / "constants3d.py"]]
    manifest_path = docs_path.parent / "manifest.json"
    if manifest_path.is_file():
        identities.append(file_identity(manifest_path))
    unknowns = unknown_annotations(files)
    report = {
        "schema_version": 1,
        "input_identities": identities,
        "unknown_annotations": unknowns,
        "unknown_annotation_count": len(unknowns),
        "inputs": {"wrapper": str(model.source), "metadata": str(metadata), "docs": str(docs_path)},
        "output": str(output),
        "counts": {"classes": len(model.classes), "functions": len(model.functions), "methods": sum(bool(m.owner) for m in model.methods.values()),
                   "parameters": len(parameters), "precise_parameters": sum("Any" not in p for p in parameters),
                   "returns": len(results), "precise_returns": sum("Any" not in r for r in results),
                   "unresolved_parameters": sum("Any" in p for p in parameters), "unresolved_returns": sum("Any" in r for r in results),
                   "diagnostics": len(model.diagnostics), **model.stats},
        "documentation": {**docs.stats, "matched_symbols": len(docs.matches), "native_filename_pages": sum(Path(str(p.get("source_html", ""))).name.startswith("ksapi_") for p in docs.pages)},
        "documentation_unmatched_symbols": docs.unmatched,
        "diagnostic_counts": dict(reasons),
        "type_conflict_categories": dict(Counter(d["category"] for d in model.diagnostics if "category" in d)),
        "diagnostics": model.diagnostics,
        "limitations": [
            "AST and SDK metadata only: no native module imports, CAD startup, network or runtime validation.",
            "Unconfigured native restypes retain ctypes' actual int default, even when C++ metadata declares void.",
            "Unresolved Python/dynamic pointer conversions are explicit Any with per-symbol diagnostics.",
            "Only exact native documentation identities and actual Python base chains are used; COM pages are excluded.",
            "No properties, overloads or inheritance are synthesized; output initializer arguments remain required.",
        ],
        "files": {name: {"lines": len(text.splitlines()), "bytes": len(text.encode())} for name, text in files.items()},
    }
    atomic_write(output / "report.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", "--kompas-root", type=Path, default=DEFAULT_INSTALL)
    parser.add_argument("--docs", type=Path, default=REPO / ".cache/kompas-sdk-docs/llm/pages.jsonl")
    parser.add_argument("--output", "--output-dir", type=Path, default=REPO / ".cache/kompas-stubs")
    parser.add_argument("--metadata", type=Path)
    args = parser.parse_args()
    try:
        validate_environment(args.install)
        report = generate(args.install, args.docs, args.output, args.metadata)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        parser.exit(2, f"{exc}\n")
    print(json.dumps({"output": report["output"], "counts": report["counts"], "documentation": report["documentation"], "diagnostic_counts": report["diagnostic_counts"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
