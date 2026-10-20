# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Audit full generated documentation identities, local links and every Any annotation."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
from collections import Counter
from urllib.parse import unquote

SKILL_DIR = Path(__file__).resolve().parents[2]


def audit(docs: Path, stubs: Path) -> dict:
    pages = [json.loads(line) for line in (docs / "llm/pages.jsonl").read_text(encoding="utf-8").splitlines() if line]
    native = {page["source_html"]: page for page in pages if page["section"] == "API интерфейсов. KsAPI"}
    errors = []
    unknowns = []
    class_nodes: dict[str, ast.ClassDef] = {}
    counts = {"pages": len(pages), "native_pages": len(native), "docstrings_with_native_pages": 0,
              "local_links_checked": 0, "annotations_checked": 0, "markdown_links_checked": 0}
    cache = {}

    def text(path: Path) -> str:
        if path not in cache:
            cache[path] = path.read_text(encoding="utf-8")
        return cache[path]

    def check_link(base: Path, href: str, symbol: str):
        if href.startswith(("https:", "http:", "mailto:", "webhelp:")):
            return
        target, _, fragment = unquote(href).partition("#")
        path = (base.parent / target).resolve() if target else base.resolve()
        if not path.is_file():
            errors.append({"symbol": symbol, "error": "missing local link", "target": href})
        elif fragment and f'id="{fragment}"' not in text(path):
            errors.append({"symbol": symbol, "error": "missing local anchor", "target": href})

    def visit(body, owner, path):
        for node in body:
            name = getattr(node, "name", "")
            symbol = f"{owner}.{name}" if owner and name else name or owner
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node) or ""
                matched = re.search(r"Native documentation: (\S+) \(id:", doc)
                if matched:
                    counts["docstrings_with_native_pages"] += 1
                    source = matched.group(1)
                    page = native.get(source)
                    if page is None:
                        errors.append({"symbol": symbol, "error": "non-native or absent documentation", "source": source})
                    elif page.get("symbol") and page["symbol"] != symbol:
                        expected = page["symbol"]
                        cls = class_nodes.get(owner)
                        seen = set()
                        inherited = False
                        pending = list(cls.bases) if cls else []
                        while pending:
                            base = ast.unparse(pending.pop())
                            if base in seen:
                                continue
                            seen.add(base)
                            if expected == base + "." + name:
                                inherited = True
                                break
                            if base in class_nodes:
                                pending.extend(class_nodes[base].bases)
                        if not inherited:
                            errors.append({"symbol": symbol, "error": "documentation belongs to another symbol", "page_symbol": expected})
                for href in re.findall(r"Local documentation: \[.*?\]\(([^\n]+)\)", doc):
                    counts["local_links_checked"] += 1
                    check_link(path, href, symbol)
            annotations = []
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                annotations = [(a.arg, a.annotation) for a in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]]
                if node.args.vararg:
                    annotations.append(("*" + node.args.vararg.arg, node.args.vararg.annotation))
                if node.args.kwarg:
                    annotations.append(("**" + node.args.kwarg.arg, node.args.kwarg.annotation))
                annotations.append(("return", node.returns))
            elif isinstance(node, ast.AnnAssign):
                annotations.append((ast.unparse(node.target), node.annotation))
            for field, annotation in annotations:
                if annotation is not None:
                    counts["annotations_checked"] += 1
                    if any(isinstance(item, ast.Name) and item.id == "Any" for item in ast.walk(annotation)):
                        unknowns.append({"file": path.name, "symbol": symbol, "field": field,
                                         "annotation": ast.unparse(annotation), "line": node.lineno})
            if isinstance(node, ast.ClassDef):
                visit(node.body, symbol, path)

    for path in sorted(stubs.glob("*.pyi")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        class_nodes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
        visit(tree.body, "", path)
    manifest = json.loads((docs / "llm/manifest.json").read_text(encoding="utf-8"))
    for relative in manifest["generated_files"]:
        if relative.endswith(".md"):
            path = docs / relative
            for href in re.findall(r"\]\(<([^>]+)>\)", text(path.resolve())):
                counts["markdown_links_checked"] += 1
                check_link(path, href, relative)
    generator_path = stubs / "report.json"
    if generator_path.is_file():
        generator = json.loads(generator_path.read_text(encoding="utf-8"))
        fields = ("file", "symbol", "field", "annotation", "line")
        reported = Counter(tuple(item.get(field) for field in fields) for item in generator.get("unknown_annotations", []))
        observed = Counter(tuple(item.get(field) for field in fields) for item in unknowns)
        if reported != observed:
            errors.append({"error": "generator unknown-type inventory differs from independent AST audit"})
        for identity in generator.get("input_identities", []):
            source = Path(identity["path"])
            if source.is_file() and hashlib.sha256(source.read_bytes()).hexdigest() != identity["sha256"]:
                errors.append({"error": "stale generated stubs", "source": str(source)})
    return {"independent": True, "ok": not errors, "counts": counts, "errors": errors,
            "unknown_annotations": unknowns, "unknown_count": len(unknowns),
            "source_unresolved_links": manifest["unresolved_links"],
            "sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(stubs.glob("*.pyi"))}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docs", type=Path, default=SKILL_DIR / ".cache/kompas-sdk-docs")
    parser.add_argument("--stubs", type=Path, default=SKILL_DIR / ".cache/kompas-stubs")
    args = parser.parse_args()
    report = audit(args.docs, args.stubs)
    destination = args.stubs / "artifact-audit.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("ok", "counts", "unknown_count")}, ensure_ascii=False, indent=2))
    return int(not report["ok"])


if __name__ == "__main__":
    raise SystemExit(main())
