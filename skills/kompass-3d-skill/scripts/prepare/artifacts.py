"""Safe publication and exhaustive annotation accounting for generated artifacts."""
from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import tempfile


def file_identity(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}


def atomic_write(path: Path, text: str) -> None:
    if path.is_symlink():
        raise ValueError(f"Refusing generated output symlink: {path}")
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=path.parent, prefix=".kompas-stubs-", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    os.replace(temporary, path)


def validate_documentation(docs_path: Path, install: Path) -> None:
    """Reject cached docs from another installation or a changed local help archive."""
    manifest_path = docs_path.parent / "manifest.json"
    if not manifest_path.is_file():
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    package = manifest.get("package", {})
    if package.get("install") and Path(package["install"]).resolve() != install.resolve():
        raise ValueError("Documentation belongs to a different SDK installation; rebuild scripts/prepare/prepare_docs.py")
    source = manifest.get("source", {})
    source_path = Path(source.get("path", ""))
    if source_path.is_file() and file_identity(source_path)["sha256"] != source.get("sha256"):
        raise ValueError("SDK help archive changed since extraction; rebuild scripts/prepare/prepare_docs.py")


def unknown_annotations(files: dict[str, str]) -> list[dict]:
    """Inventory every explicit Any, including attributes, constants and helper types."""
    unknowns = []

    def visit(body: list[ast.stmt], owner: str, filename: str):
        for node in body:
            name = getattr(node, "name", "")
            symbol = (owner + "." + name if owner else name) if name else owner
            fields = []
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = node.args
                fields = [(a.arg, a.annotation) for a in [*args.posonlyargs, *args.args, *args.kwonlyargs]]
                if args.vararg:
                    fields.append(("*" + args.vararg.arg, args.vararg.annotation))
                if args.kwarg:
                    fields.append(("**" + args.kwarg.arg, args.kwarg.annotation))
                fields.append(("return", node.returns))
            elif isinstance(node, ast.AnnAssign):
                fields = [(ast.unparse(node.target), node.annotation)]
            for field, annotation in fields:
                if annotation is not None and any(isinstance(item, ast.Name) and item.id == "Any" for item in ast.walk(annotation)):
                    unknowns.append({"file": filename, "symbol": symbol, "field": field, "annotation": ast.unparse(annotation), "line": node.lineno})
            if isinstance(node, ast.ClassDef):
                visit(node.body, symbol, filename)
    for filename, content in sorted(files.items()):
        visit(ast.parse(content, filename=filename).body, "", filename)
    return unknowns
