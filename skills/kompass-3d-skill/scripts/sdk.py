#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["ty==0.0.90"]
# ///
"""Search native KsAPI sources/docs, query types/docstrings, and check macros offline."""
from __future__ import annotations

import argparse
import ast
import json
import keyword
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_BIN = Path("/opt/ascon/kompas3d-v25/Bin")
DEFAULT_DOCS = SKILL_DIR / ".cache/kompas-sdk-docs"
DEFAULT_STUBS = SKILL_DIR / ".cache/kompas-stubs"
MODULES = ("ksapi", "constants", "constants3d")
FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
SECTIONS = {
    "ksapi": "API интерфейсов. KsAPI",
    "api7": "API интерфейсов. Версия 7",
    "api5": "API интерфейсов. Версия 5",
}


class Documentation:
    """Read-only access to the prepared SDK index."""

    def __init__(self, path: Path):
        self.path = path if path.is_file() else path / "index.sqlite3"
        if not self.path.is_file():
            raise FileNotFoundError(
                f"SDK index not found: {self.path}. "
                "Run uv run --script scripts/prepare/prepare_docs.py with the installed KsAPI environment."
            )
        self.connection = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)
        self.connection.row_factory = sqlite3.Row
        try:
            metadata = dict(self.connection.execute("SELECT key, value FROM meta"))
            if metadata.get("schema_version") != "1":
                raise ValueError("Unsupported SDK index schema; rebuild with scripts/prepare/prepare_docs.py")
            manifest_path = self.path.parent / "llm/manifest.json"
            if manifest_path.is_file():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if manifest.get("source", {}).get("sha256") != metadata.get("source_sha256"):
                    raise ValueError("Stale SDK index does not match manifest; rebuild with scripts/prepare/prepare_docs.py")
        except (sqlite3.Error, ValueError):
            self.connection.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.connection.close()

    @staticmethod
    def record(row) -> dict:
        page = dict(row)
        page["title_path"] = json.loads(page["title_path"])
        return page

    def resolve(self, identifier: str, section: str = "ksapi") -> dict:
        # Explicit canonical keys always win over aliases. Short IDs can be ambiguous.
        rows = self.connection.execute("SELECT * FROM pages WHERE key = ?", (identifier,)).fetchall()
        if not rows:
            rows = self.connection.execute(
                "SELECT * FROM pages WHERE source_html = ? OR id = ?", (identifier, identifier)
            ).fetchall()
        if not rows:
            condition = "" if section == "any" else " AND s.section = ?"
            params = (identifier,) if section == "any" else (identifier, SECTIONS[section])
            rows = self.connection.execute(
                "SELECT DISTINCT p.* FROM symbols s JOIN pages p ON p.key = s.page_key "
                "WHERE s.symbol = ?" + condition + " ORDER BY p.key", params
            ).fetchall()
        if not rows:
            raise ValueError(f"Documentation page not found: {identifier}")
        if len(rows) > 1:
            choices = ", ".join(row["key"] for row in rows)
            raise ValueError(f"Ambiguous documentation id {identifier!r}; use canonical key: {choices}")
        return self.record(rows[0])

    def get_pages(self, identifiers: list[str], section: str = "ksapi") -> list[dict]:
        result = []
        for identifier in identifiers:
            try:
                result.append(self.resolve(identifier, section))
            except ValueError as error:
                result.append({"requested": identifier, "error": str(error)})
        return result

    def search(self, query: str, section: str, limit: int, offset: int = 0) -> dict:
        # Treat input as text, never FTS syntax; prefix matching supports partial names.
        tokens = re.findall(r"\w+", query, re.UNICODE)
        if not tokens:
            return {"total": 0, "next_offset": None, "results": []}
        expression = " AND ".join('"' + token.replace('"', '""') + '"*' for token in tokens)
        where = "pages_fts MATCH ?"
        params: list = [expression]
        if section != "any":
            where += " AND p.section = ?"
            params.append(SECTIONS[section])
        base = " FROM pages_fts JOIN pages p ON p.key = pages_fts.key WHERE " + where
        total = self.connection.execute("SELECT count(*)" + base, params).fetchone()[0]
        rows = self.connection.execute(
            "SELECT p.*, bm25(pages_fts, 0, 8, 1, 12) AS rank" + base
            + " ORDER BY rank, p.key LIMIT ? OFFSET ?", [*params, limit, offset]
        ).fetchall()
        results = []
        for row in rows:
            page = self.record(row)
            content = page.pop("content")
            positions = [content.casefold().find(token.casefold()) for token in tokens]
            start = max(0, min((pos for pos in positions if pos >= 0), default=0) - 100)
            page["excerpt"] = content[start:start + 700]
            results.append(page)
        return {
            "total": total, "next_offset": offset + limit if offset + limit < total else None,
            "results": results,
        }

    def toc(self, identifier: str | None, section: str, limit: int, offset: int) -> dict:
        params: list = []
        if identifier is not None:
            page = self.resolve(identifier, section)
            sql = "SELECT p.* FROM toc t JOIN pages p ON p.key = t.child WHERE t.parent = ?"
            params.append(page["key"])
            order = " ORDER BY t.position, p.key"
        else:
            page = None
            sql = (
                "SELECT p.* FROM pages p WHERE p.key NOT IN "
                "(SELECT child FROM toc WHERE parent IS NOT NULL AND child IS NOT NULL)"
            )
            order = " ORDER BY p.key"
        if section != "any":
            sql += " AND p.section = ?"
            params.append(SECTIONS[section])
        total = self.connection.execute("SELECT count(*) FROM (" + sql + ")", params).fetchone()[0]
        rows = self.connection.execute(sql + order + " LIMIT ? OFFSET ?", [*params, limit, offset])
        result = {
            "total": total, "next_offset": offset + limit if offset + limit < total else None,
            "results": [self.summary(self.record(row)) for row in rows],
        }
        if page:
            result["page"] = self.summary(page)
            result["parents"] = [
                self.summary(self.record(row)) for row in self.connection.execute(
                    "SELECT p.* FROM toc t JOIN pages p ON p.key = t.parent "
                    "WHERE t.child = ? ORDER BY p.key", (page["key"],)
                )
            ]
        return result

    @staticmethod
    def summary(page: dict) -> dict:
        return {key: page[key] for key in ("key", "id", "title", "section", "symbol", "source_html")}

    def links(self, identifier: str, section: str, limit: int, offset: int) -> dict:
        page = self.resolve(identifier, section)
        total = self.connection.execute(
            "SELECT count(*) FROM links WHERE source = ?", (page["key"],)
        ).fetchone()[0]
        rows = self.connection.execute(
            "SELECT l.target, l.fragment, l.label, p.title, p.symbol "
            "FROM links l LEFT JOIN pages p ON p.key = l.target WHERE l.source = ? "
            "ORDER BY l.target, l.fragment, l.label LIMIT ? OFFSET ?", (page["key"], limit, offset)
        )
        return {
            "page": self.summary(page), "total": total,
            "next_offset": offset + limit if offset + limit < total else None,
            "results": [dict(row) for row in rows],
        }


def qualified_symbol(symbol: str) -> str:
    parts = symbol.split(".")
    if not all(part.isidentifier() and not keyword.iskeyword(part) for part in parts):
        raise ValueError(f"Expected a dotted Python symbol, got {symbol!r}")
    return symbol if parts[0] in MODULES else "ksapi." + symbol


def is_docstring(node: ast.AST) -> bool:
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)


def declared_names(node: ast.AST) -> list[str]:
    if isinstance(node, (ast.ClassDef, *FUNCTIONS)):
        return [node.name]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id]
    if isinstance(node, ast.Assign):
        return [target.id for target in node.targets if isinstance(target, ast.Name)]
    return []


class Stub:
    def __init__(self, path: Path):
        self.path = path
        self.source = path.read_text(encoding="utf-8")
        self.lines = self.source.splitlines()
        self.tree = ast.parse(self.source, filename=str(path))

    def excerpt(self, node: ast.stmt) -> str:
        start = node.lineno
        if isinstance(node, (ast.ClassDef, *FUNCTIONS)):
            start = min([start, *(item.lineno for item in node.decorator_list)])
        while start > 1 and self.lines[start - 2].lstrip().startswith("#"):
            start -= 1
        return textwrap.dedent("\n".join(self.lines[start - 1:node.end_lineno]))

    def class_intro(self, node: ast.ClassDef) -> str:
        bases = [ast.unparse(base) for base in node.bases]
        bases += [ast.unparse(item) for item in node.keywords]
        header = f"class {node.name}" + (f"({', '.join(bases)})" if bases else "") + ":"
        decorators = ["@" + ast.unparse(item) for item in node.decorator_list]
        result = "\n".join([*decorators, header])
        if node.body and is_docstring(node.body[0]):
            result += "\n" + textwrap.indent(self.excerpt(node.body[0]), "    ")
        return result

    def render(self, node: ast.stmt, body: list[ast.stmt]) -> str:
        if isinstance(node, ast.ClassDef):
            # Class queries list declarations, not every method's long docstring.
            declarations = []
            for item in node.body:
                if isinstance(item, FUNCTIONS):
                    signature = ast.unparse(item).split("\n", 1 + len(item.decorator_list))
                    declarations.append("\n".join(signature[:1 + len(item.decorator_list)]) + " ...")
                elif isinstance(item, ast.ClassDef):
                    declarations.append(self.class_intro(item).split("\n")[0] + " ...")
                elif declared_names(item):
                    declarations.append(self.excerpt(item))
            content = "\n".join(declarations) or "..."
            return self.class_intro(node) + "\n\n" + textwrap.indent(content, "    ")
        result = self.excerpt(node)
        index = body.index(node)
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and index + 1 < len(body) and is_docstring(body[index + 1]):
            result += "\n" + self.excerpt(body[index + 1])
        return result

    def wrap(self, owner: ast.ClassDef, selected: list[ast.stmt], content: str) -> str:
        first, last = owner.body.index(selected[0]), owner.body.index(selected[-1])
        above = [item.name for item in owner.body[:first] if isinstance(item, FUNCTIONS)]
        below = [item.name for item in owner.body[last + 1:] if isinstance(item, FUNCTIONS)]
        parts = [self.class_intro(owner)]
        if above:
            names = ", ".join(reversed(above[-3:])) + (", ..." if len(above) > 3 else "")
            parts.append(f"    # {len(above)} methods above: {names}")
        parts.append(textwrap.indent(content, "    "))
        if below:
            names = ", ".join(below[:3]) + (", ..." if len(below) > 3 else "")
            parts.append(f"    # {len(below)} methods below: {names}")
        return "\n\n".join(parts)


class StubDocs:
    """Parse each queried module once per batch; follow local bases and re-exports."""

    def __init__(self, directory: Path, bin_dir: Path | None = None):
        self.directory = directory
        self.bin_dir = bin_dir
        self.modules: dict[str, Stub] = {}
        self.sources: dict[str, Stub] = {}

    def load(self, module: str) -> Stub:
        if module not in self.modules:
            path = self.directory / f"{module}.pyi"
            if not path.is_file():
                raise FileNotFoundError(f"Missing {path}; run scripts/prepare/prepare_stubs.py")
            self.modules[module] = Stub(path)
        return self.modules[module]

    def resolve(self, module: str, parts: list[str], seen: set[tuple[str, ...]]):
        key = (module, *parts)
        if key in seen:
            raise ValueError(f"Cyclic stub reference: {'.'.join(key)}")
        seen = seen | {key}
        stub = self.load(module)
        body = stub.tree.body
        owners = []
        for index, name in enumerate(parts):
            nodes = [item for item in body if name in declared_names(item)]
            if not nodes:
                if owners:
                    for base in owners[-1].bases:
                        try:
                            return self.resolve(module, ast.unparse(base).split(".") + parts[index:], seen)
                        except ValueError:
                            continue
                else:
                    for item in body:
                        if isinstance(item, ast.ImportFrom) and item.module in MODULES:
                            for alias in item.names:
                                if (alias.asname or alias.name) == name:
                                    return self.resolve(item.module, [alias.name, *parts[index + 1:]], seen)
                raise ValueError(f"Symbol not found in stubs: {module}.{'.'.join(parts)}")
            if index == len(parts) - 1:
                return stub, owners, body, nodes
            node = nodes[-1]
            if not isinstance(node, ast.ClassDef):
                raise ValueError(f"Not a class in stubs: {name}")  # noqa: TRY004 - invalid symbol path, not an argument type.
            owners.append(node)
            body = node.body
        raise ValueError("Expected a symbol after the module name")

    def doc(self, symbol: str) -> str:
        module, *parts = qualified_symbol(symbol).split(".")
        stub, owners, body, nodes = self.resolve(module, parts, set())
        content = "\n\n".join(stub.render(node, body) for node in nodes)
        selected = nodes
        for owner in reversed(owners):
            content = stub.wrap(owner, selected, content)
            selected = [owner]
        start = min([nodes[0].lineno, *(item.lineno for item in getattr(nodes[0], "decorator_list", []))])
        header = f"# {symbol} — {stub.path}:{start}"
        if self.bin_dir is not None:
            path = self.bin_dir / f"{stub.path.stem}.py"
            if path.is_file():
                module = stub.path.stem
                if module not in self.sources:
                    self.sources[module] = Stub(path)
                source_body = self.sources[module].tree.body
                names = [owner.name for owner in owners] + declared_names(nodes[0])[:1]
                for index, name in enumerate(names):
                    matches = [item for item in source_body if name in declared_names(item)]
                    if not matches:
                        header += f"\n# Python binding: {path} — declaration not found: {'.'.join(names)}"
                        break
                    source_node = matches[-1]
                    if index == len(names) - 1:
                        header += f"\n# Python binding: {path}:{source_node.lineno}"
                    elif isinstance(source_node, ast.ClassDef):
                        source_body = source_node.body
                    else:
                        header += f"\n# Python binding: {path} — not a class: {name}"
                        break
            else:
                header += f"\n# Python binding: {path} — file not found"
        return f"{header}\n{content}"


def run_typing(args: argparse.Namespace) -> int:
    try:
        stubs = args.stubs.expanduser().resolve()
        if args.command == "doc":
            docs = StubDocs(stubs, args.bin.expanduser().resolve())
            code = 0
            for index, symbol in enumerate(args.symbols):
                if index:
                    print()
                try:
                    print(docs.doc(symbol))
                except ValueError as exc:
                    print(f"sdk: {exc}", file=sys.stderr)
                    code = 1
            return code
        if args.timeout <= 0:
            raise ValueError("--timeout must be positive")
        for module in MODULES:
            if not (stubs / f"{module}.pyi").is_file():
                raise FileNotFoundError(f"Missing {stubs / (module + '.pyi')}; run scripts/prepare/prepare_stubs.py")
        executable = shutil.which("ty")
        if executable is None:
            raise FileNotFoundError("ty not found; run uv run --script scripts/sdk.py")
        project = args.project.expanduser().resolve() if args.project else None
        if project is not None and not project.is_dir():
            raise ValueError(f"Workspace directory does not exist: {project}")
        files = [str(path.expanduser().resolve(strict=True)) for path in args.files]
        # Kompas stubs mark almost every getter as T | None; recipe style is
        # require(model.GetSketchs().Add(), ...). ty folds Optional member access
        # and missing attributes into one rule — ignore it so chains type-check.
        command = [
            executable, "check",
            "--extra-search-path", str(stubs),
            "--ignore", "unresolved-attribute",
        ]
        if project:
            command += ["--project", str(project)]
        return subprocess.run([*command, *files], check=False, timeout=args.timeout).returncode
    except (OSError, ValueError, SyntaxError, subprocess.TimeoutExpired) as exc:
        print(f"sdk: {exc}", file=sys.stderr)
        return 2


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
    parser.add_argument("--stubs", type=Path, default=DEFAULT_STUBS)
    parser.add_argument("--project", type=Path, help="Workspace root for ty check")
    parser.add_argument("--timeout", type=float, default=30, help="ty check timeout in seconds")
    commands = parser.add_subparsers(dest="command", required=True)

    doc = commands.add_parser("doc", help="Read stub signatures/docstrings with class context; default module: ksapi")
    doc.add_argument("symbols", nargs="+")
    check = commands.add_parser("check", help="Check macro types with ty; never executes the macro")
    check.add_argument("files", nargs="+", type=Path)

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

    if args.command in ("doc", "check"):
        return run_typing(args)

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
