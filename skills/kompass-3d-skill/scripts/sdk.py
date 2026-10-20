#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Search SDK documentation and inspect native KsAPI bindings without importing ksapi."""
from __future__ import annotations

import argparse
import ast
import json
import os
from pathlib import Path
import sys
import sqlite3

from sdk_index import Documentation, SECTIONS


SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_BIN = Path("/opt/ascon/kompas3d-v25/Bin")
DEFAULT_DOCS = SKILL_DIR / ".cache/kompas-sdk-docs"

class Binding:
    def __init__(self, path: Path):
        self.path = path
        self.source = path.read_text(encoding="utf-8")
        self.lines = self.source.splitlines()
        tree = ast.parse(self.source, filename=str(path))
        self.classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
        self.functions = {
            node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)
        }

    def members(self, name: str) -> dict[str, tuple[str, ast.FunctionDef]]:
        node = self.classes[name]
        result = {}
        for base in node.bases:
            if isinstance(base, ast.Name) and base.id in self.classes:
                result.update(self.members(base.id))
        for member in node.body:
            if isinstance(member, ast.FunctionDef) and not member.name.startswith("_"):
                result[member.name] = (name, member)
        return result

    def method_info(self, owner: str, node: ast.FunctionDef, source: bool) -> dict:
        result = {
            "symbol": f"{owner}.{node.name}" if owner else node.name,
            "signature": f"{node.name}({ast.unparse(node.args)})",
            "path": str(self.path),
            "line": node.lineno,
            "end_line": node.end_lineno,
        }
        # Wrapper constructors reveal concrete returned interfaces. Native scalar
        # results remain unknown; documentation and the function body define them.
        wrappers = sorted({
            call.func.id
            for call in ast.walk(node)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id in self.classes
            and any(isinstance(item, ast.Return) for item in ast.walk(node))
        })
        result["constructed_interfaces"] = wrappers
        result["returns_value"] = any(
            isinstance(item, ast.Return) and item.value is not None for item in ast.walk(node)
        )
        if source:
            result["source"] = "\n".join(self.lines[node.lineno - 1:node.end_lineno])
        return result

    def inspect(self, symbol: str, source: bool = False, match: str = "") -> dict:
        owner, separator, member = symbol.partition(".")
        if separator:
            if owner not in self.classes:
                raise ValueError(f"Interface not found in local binding: {owner}")
            members = self.members(owner)
            if member not in members:
                raise ValueError(f"Member not found in local binding: {symbol}")
            defined_on, node = members[member]
            return {"requested": symbol, **self.method_info(defined_on, node, source)}
        if owner in self.functions:
            return self.method_info("", self.functions[owner], source)
        if owner not in self.classes:
            raise ValueError(f"Symbol not found in local binding: {symbol}")
        class_node = self.classes[owner]
        return {
            "symbol": owner,
            "bases": [ast.unparse(base) for base in class_node.bases],
            "path": str(self.path),
            "line": class_node.lineno,
            "members": [
                self.method_info(defined_on, method, True) if source else {
                    "symbol": f"{defined_on}.{method.name}",
                    "signature": f"{method.name}({ast.unparse(method.args)})",
                    "line": method.lineno,
                }
                for name, (defined_on, method) in sorted(self.members(owner).items())
                if all(token in name.casefold() for token in match.casefold().split())
            ],
        }

    def search(self, query: str, limit: int, offset: int = 0) -> dict:
        tokens = query.casefold().split()
        matches = []
        for name in sorted(self.classes):
            if all(token in name.casefold() for token in tokens):
                matches.append({"symbol": name, "line": self.classes[name].lineno})
            # Search declarations only, not inherited duplicates or native ctypes setup.
            for node in self.classes[name].body:
                if isinstance(node, ast.FunctionDef):
                    symbol = f"{name}.{node.name}"
                    if all(token in symbol.casefold() for token in tokens):
                        matches.append({"symbol": symbol, "line": node.lineno})
        for name, node in sorted(self.functions.items()):
            if all(token in name.casefold() for token in tokens):
                matches.append({"symbol": name, "line": node.lineno})
        return {
            "path": str(self.path), "total": len(matches),
            "next_offset": offset + limit if offset + limit < len(matches) else None,
            "results": matches[offset:offset + limit],
        }


def search_docs(docs: Path, query: str, section: str, limit: int, offset: int = 0) -> dict:
    with Documentation(docs) as index:
        return index.search(query, section, limit, offset)


def get_pages(docs: Path, page_ids: list[str], section: str = "ksapi") -> list[dict]:
    with Documentation(docs) as index:
        return index.get_pages(page_ids, section)


def get_page(docs: Path, page_id: str) -> dict:
    result = get_pages(docs, [page_id])[0]
    if "error" in result:
        raise ValueError(result["error"])
    return result


def search_constants(bin_dir: Path, query: str, limit: int) -> dict:
    tokens = query.casefold().split()
    results = []
    for module in ("constants", "constants3d"):
        path = bin_dir / f"{module}.py"
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines()
        for node in ast.walk(ast.parse(source, filename=str(path))):
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name):
                continue
            line = lines[node.lineno - 1].strip()
            if all(token in line.casefold() for token in tokens):
                results.append({
                    "symbol": f"{module}.constants.{target.id}",
                    "expression": ast.unparse(node.value), "declaration": line,
                    "path": str(path), "line": node.lineno,
                })
    return {"total": len(results), "results": results[:limit]}


def positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bin", type=Path, default=Path(os.environ.get("KOMPAS_BIN", DEFAULT_BIN)))
    parser.add_argument("--docs", type=Path, default=Path(os.environ.get("KOMPAS_SDK_DOCS", DEFAULT_DOCS)))
    commands = parser.add_subparsers(dest="command", required=True)

    search = commands.add_parser("search", help="Indexed documentation search; all words must match")
    search.add_argument("query")
    search.add_argument("--section", choices=[*SECTIONS, "any"], default="ksapi")
    search.add_argument("--limit", type=positive, default=8)
    search.add_argument("--offset", type=int, default=0)
    page = commands.add_parser("page", help="Read pages by canonical key, unique ID, path or symbol")
    page.add_argument("ids", nargs="+")
    page.add_argument("--section", choices=[*SECTIONS, "any"], default="ksapi")
    toc = commands.add_parser("toc", help="List root topics or children and parents of a page")
    toc.add_argument("id", nargs="?")
    links = commands.add_parser("links", help="List a page's outgoing documentation links")
    links.add_argument("id")
    for navigation in (toc, links):
        navigation.add_argument("--section", choices=[*SECTIONS, "any"], default="ksapi")
        navigation.add_argument("--limit", type=positive, default=20)
        navigation.add_argument("--offset", type=int, default=0)
    local = commands.add_parser("local", help="Find interface and method names in the local binding")
    local.add_argument("query")
    local.add_argument("--limit", type=positive, default=30)
    local.add_argument("--offset", type=int, default=0)
    inspect = commands.add_parser("inspect", help="Inspect symbols in one AST pass; classes list compact signatures")
    inspect.add_argument("symbols", nargs="+")
    inspect.add_argument("--source", action="store_true")
    inspect.add_argument("--match", default="", help="Filter class members by name (all words must match)")
    constants = commands.add_parser("constants", help="Find local constants by name or Russian comment")
    constants.add_argument("query")
    constants.add_argument("--limit", type=positive, default=20)
    verify = commands.add_parser("verify", help="Check explicit symbols exist; not a code/runtime validator")
    verify.add_argument("symbols", nargs="+")
    verify.add_argument("--brief", action="store_true", help="Only counts and missing symbols, no binding dump")
    args = parser.parse_args(argv)
    if getattr(args, "offset", 0) < 0:
        parser.error("--offset must be nonnegative")

    code = 0
    try:
        if args.command == "search":
            result = search_docs(args.docs, args.query, args.section, args.limit, args.offset)
        elif args.command == "page":
            results = get_pages(args.docs, args.ids, args.section)
            code = int(any("error" in item for item in results))
            result = results[0] if len(results) == 1 else {"results": results}
        elif args.command in ("toc", "links"):
            with Documentation(args.docs) as index:
                navigate = index.toc if args.command == "toc" else index.links
                result = navigate(args.id, args.section, args.limit, args.offset)
        elif args.command == "constants":
            result = search_constants(args.bin, args.query, args.limit)
        else:
            binding = Binding(args.bin / "ksapi.py")
            if args.command == "local":
                result = binding.search(args.query, args.limit, args.offset)
            elif args.command == "inspect":
                results = []
                for symbol in args.symbols:
                    try:
                        results.append(binding.inspect(symbol, args.source, args.match))
                    except ValueError as error:
                        results.append({"requested": symbol, "error": str(error)})
                code = int(any("error" in item for item in results))
                result = results[0] if len(results) == 1 else {"results": results}
            else:
                results = []
                for symbol in args.symbols:
                    try:
                        info = binding.inspect(symbol)
                    except ValueError as error:
                        results.append({"symbol": symbol, "found": False, "error": str(error)})
                    else:
                        results.append({"symbol": symbol, "found": True, "binding": info})
                ok = all(item["found"] for item in results)
                result = {
                    "ok": ok, "scope": "symbol existence only; signatures and runtime not validated",
                }
                if args.brief:
                    result.update(checked=len(results), missing=[
                        {"symbol": item["symbol"], "error": item["error"]}
                        for item in results if not item["found"]
                    ])
                else:
                    result["results"] = results
                code = 0 if ok else 1
    except (OSError, ValueError, SyntaxError, sqlite3.Error) as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
