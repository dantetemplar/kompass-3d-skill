"""Render AST-derived native stubs and attach exact, native-only documentation."""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from native import Method, NativeModel, dotted, effective, nodes_in_function

NATIVE_SECTION = "API интерфейсов. KsAPI"


class Documentation:
    def __init__(self, path: Path):
        if not path.is_file():
            raise FileNotFoundError(
                f"Documentation index is missing: {path}\n"
                "Generate it first: uv run --script scripts/prepare/prepare_docs.py"
            )
        self.path = path
        self.pages: list[dict[str, Any]] = []
        self.index: dict[str, list[int]] = defaultdict(list)
        self.stats: Counter[str] = Counter()
        self.matches: dict[str, dict[str, Any]] = {}
        self.unmatched: list[str] = []
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            page = json.loads(line)
            if page.get("section") != NATIVE_SECTION:
                self.stats["excluded_non_native_pages"] += 1
                continue
            self.stats["native_pages"] += 1
            source = str(page.get("source_html", ""))
            filename = Path(urlparse(source).path).name.lower()
            identities = [str(page.get("symbol") or ""), str(page.get("title") or ""), str(page.get("key") or "")]
            title_path = page.get("title_path") or []
            if isinstance(title_path, list):
                # Combine owner and leaf title, never use a bare method title.
                owners = [str(p) for p in title_path if re.fullmatch(r"I[A-Za-z0-9_]+", str(p))]
                if owners and identities[1]:
                    identities.append(owners[-1] + "." + identities[1])
            if filename.startswith("ksapi_"):
                identities.append(filename.removesuffix(".html").removesuffix(".htm").removeprefix("ksapi_"))
            index = len(self.pages)
            self.pages.append(page)
            for identity in identities:
                key = self.normalize(identity)
                if key and index not in self.index[key]:
                    self.index[key].append(index)

    @staticmethod
    def normalize(value: str) -> str:
        value = unquote(value).strip()
        value = re.sub(r"\([^)]*\)", "", value)
        value = value.replace("::", ".").replace("_", ".")
        value = re.sub(r"\s*[—–-]\s*.*$", "", value)
        return value.strip(" .").casefold()

    def find(self, symbol: str, model: NativeModel) -> dict[str, Any] | None:
        matches = self.index.get(self.normalize(symbol), [])
        # Interface method-index pages may reuse the owner's symbol. Prefer the
        # unique exact native filename, not a title-based ranking heuristic.
        expected = "ksapi_" + symbol.replace(".", "_").casefold()
        filenames = [i for i in matches if Path(urlparse(str(self.pages[i].get("source_html", ""))).path).stem.casefold() == expected]
        if len(filenames) == 1:
            matches = filenames
        if len(matches) == 1:
            page = self.pages[matches[0]]
            self.matches[symbol] = page
            self.stats["direct_matches"] += 1
            return page
        if len(matches) > 1:
            self.stats["ambiguous_symbols"] += 1
            model.diagnostic(symbol, "documentation", "multiple exact native documentation matches", pages=[self.pages[i].get("id") for i in matches])
            return None
        if "." in symbol:
            owner, method = symbol.rsplit(".", 1)
            seen: set[str] = set()
            def inherited(name: str) -> dict[str, Any] | None:
                if name in seen:
                    return None
                seen.add(name)
                cls = model.classes.get(name)
                if cls is None:
                    return None
                for base in cls.bases:
                    base_name = dotted(base)
                    candidates = self.index.get(self.normalize(base_name + "." + method), [])
                    if len(candidates) == 1:
                        return self.pages[candidates[0]]
                    result = inherited(base_name)
                    if result:
                        return result
                return None
            inherited_page = inherited(owner)
            if inherited_page:
                self.matches[symbol] = inherited_page
                self.stats["inherited_matches"] += 1
                return inherited_page
        self.stats["unmatched_symbols"] += 1
        self.unmatched.append(symbol)
        return None

    def markdown_path(self, page: dict[str, Any]) -> Path:
        # The docs generator may supply an explicit relative Markdown identity.
        for name in ("markdown_path", "markdown", "output_markdown"):
            if page.get(name):
                path = Path(str(page[name]))
                return path if path.is_absolute() else self.path.parent.parent / path
        # Match docs.write_markdown's stable section/owner grouping and page anchors.
        def safe_name(value: str) -> str:
            value = re.sub(r"[^\w.-]+", "_", value, flags=re.UNICODE).strip("._")
            return value[:70].encode("utf-8")[:160].decode("utf-8", "ignore").strip("._") or "unnamed"
        def digest(value: str) -> str:
            return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
        section = str(page["section"])
        symbol = page.get("symbol")
        owner = str(symbol).split(".")[0] if symbol else "_other"
        directory = safe_name(section) + "__" + digest(section)
        filename = safe_name(owner) + "__" + digest(owner) + ".md"
        return self.path.parent / "api_objects" / directory / filename

    def text(self, symbol: str, model: NativeModel, output: Path, method: Method | None = None) -> str:
        page = self.find(symbol, model)
        parts: list[str] = []
        if page:
            parts.append(str(page.get("title") or symbol))
            content = page.get("content", "")
            if isinstance(content, str) and content.strip():
                parts.append("SDK documentation (native C++ KsAPI syntax; not the Python call signature):\n" + content.strip())
            elif content:
                parts.append(json.dumps(content, ensure_ascii=False))
            md = self.markdown_path(page)
            key = str(page.get("key") or "webhelp:" + str(page.get("source_html", "")))
            anchor = str(page.get("markdown_fragment") or "page-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16])
            parts.append(f"Local documentation: [{page.get('title') or symbol}]({os.path.relpath(md, output.parent)}#{anchor})")
            parts.append(f"Native documentation: {page.get('source_html', '')} (id: {page.get('id', page.get('key', ''))})")
        if method:
            parts.append(python_argument_documentation(method, model))
            parts.append(f"Python return: {method.result}. Wrapper arguments (including output initializers) are preserved.")
            for diagnostic in model.diagnostics:
                if diagnostic["symbol"] == method.symbol and diagnostic.get("category"):
                    parts.append("Marshalling discrepancy: " + diagnostic["explanation"] + f" SDK: {diagnostic.get('sdk_spelling')}; ctypes: {diagnostic.get('ctypes_restype')}; Python: {diagnostic.get('python_type')}.")
            if method.native_calls:
                parts.append("Native symbols: " + ", ".join(method.native_calls))
            parts.append(f"Python source: {model.source}:{method.node.lineno}")
            if method.result.startswith("tuple["):
                parts.append("Tuple order follows the Python return expression; ctypes reference arguments contribute their .value results.")
            content = str(page.get("content", "")) if page else ""
            unit_lines = [line.strip() for line in content.splitlines() if re.search(r"\b(?:mm|мм|rad|radians?|degrees?)\b|радиан|градус|единиц", line, re.I)]
            if unit_lines:
                parts.append("Units (native documentation): " + " ".join(unit_lines))
            else:
                parts.append("Units: not specified on the matched native page; consult the SDK contract rather than inferring units from Python scalar types.")
        return "\n\n".join(parts)


def python_argument_documentation(method: Method, model: NativeModel) -> str:
    """Describe observed Python arguments, not a rewritten C++ signature."""
    nodes = list(nodes_in_function(method.node))
    assignments = {target.id: item.value for item in nodes if isinstance(item, ast.Assign)
                   for target in item.targets if isinstance(target, ast.Name)}
    notes: dict[str, list[str]] = {name: [] for name in method.arguments}

    def roots(expr: ast.AST, seen: frozenset[str] = frozenset()) -> set[str]:
        if isinstance(expr, ast.Name):
            if expr.id in notes:
                return {expr.id}
            if expr.id in assignments and expr.id not in seen:
                return roots(assignments[expr.id], seen | {expr.id})
            return set()
        if isinstance(expr, ast.Call):
            return set().union(*(roots(arg, seen) for arg in expr.args)) if expr.args else set()
        if isinstance(expr, ast.Attribute):
            return roots(expr.value, seen)
        return set()

    def add(expr: ast.AST, text: str) -> None:
        for name in roots(expr):
            if text not in notes[name]:
                notes[name].append(text)

    for node in nodes:
        if not isinstance(node, ast.Call):
            continue
        name = dotted(node.func)
        if name.startswith("ksapi."):
            signature = model.signature(name[6:])
            parameters = signature.metadata.get("parameters", [])
            offset = len(node.args) - len(parameters)
            for index, expr in enumerate(node.args):
                meta_index = index - offset
                if not 0 <= meta_index < len(parameters):
                    continue
                parameter = parameters[meta_index]
                if parameter.get("name") == "self":
                    continue
                if parameter.get("in") in (False, "False", "false"):
                    add(expr, f"SDK output parameter {parameter.get('name')}; its Python argument is still an initializer supplied by the caller")
        elif name == "GetReference" and node.args:
            add(node.args[0], "GetReference converts None to native handle 0; other values must expose .reference")
        elif name == "RefString" and node.args:
            add(node.args[0], "initial text copied into RefString; returned .value is a Python str")
        elif name.startswith("ctypes.c_") and node.args:
            add(node.args[0], f"initial value copied into {name}; .value is read after the native call when returned")
        elif name.startswith("To") and "Vector" in name and node.args:
            add(node.args[-1], f"converted by {name}; the annotation does not establish which elements the native API considers semantically valid")
            helper = model.functions.get(name)
            if name == "ToObjectReferenceVector" and helper is not None:
                skips_none = any(isinstance(test, ast.Compare) and any(isinstance(op, (ast.NotEq, ast.IsNot)) for op in test.ops) and any(isinstance(value, ast.Constant) and value.value is None for value in test.comparators) for test in ast.walk(helper))
                if skips_none:
                    add(node.args[-1], "the installed ToObjectReferenceVector helper skips None elements rather than inserting null handles")
        elif name.endswith(".encode") and isinstance(node.func, ast.Attribute):
            encoding = dotted(node.args[0]) if node.args else "the default encoding"
            add(node.func.value, f"encoded to bytes with {encoding} before the native call")

    positional = [*method.node.args.posonlyargs, *method.node.args.args]
    defaults = dict(zip([arg.arg for arg in positional[-len(method.node.args.defaults):]], method.node.args.defaults)) if method.node.args.defaults else {}
    defaults.update({arg.arg: default for arg, default in zip(method.node.args.kwonlyargs, method.node.args.kw_defaults) if default is not None})
    lines = ["Python arguments:"]
    if not notes:
        lines.append("- No explicit arguments beyond self/cls.")
    for name, typ in method.arguments.items():
        default = f"; default {dotted(defaults[name])}" if name in defaults else "; required"
        detail = "; ".join(notes[name]) or "passed according to the Python wrapper body; native semantics follow the SDK documentation"
        lines.append(f"- {name}: {typ}{default}. {detail}.")
        if "None" in typ and not any("GetReference converts None" in note for note in notes[name]):
            lines.append("  Nullability describes SDK/type evidence only: acceptance of None depends on the actual conversion above; the generator does not infer semantic validity.")
    returns = [dotted(node.value) for node in nodes if isinstance(node, ast.Return)]
    if returns:
        lines.append("Python return expression(s): " + "; ".join(returns))
    return "\n".join(lines)


def doc_literal(text: str, indent: str) -> list[str]:
    if not text:
        return []
    # A real multiline docstring, escaped without changing documentation content.
    text = text.replace("\\", "\\\\").replace('"""', '\\"\\"\\"').replace("\x00", "\\x00")
    return [indent + '\"\"\"' + text.splitlines()[0], *[indent + s for s in text.splitlines()[1:]], indent + '\"\"\"']


def default_expression(node: ast.AST, known: set[str]) -> str:
    names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
    return dotted(node) if names <= known else "..."


def method_signature(method: Method, known: set[str]) -> str:
    node = method.node
    args = node.args
    positional = [*args.posonlyargs, *args.args]
    defaults: dict[str, ast.AST] = dict(zip([a.arg for a in positional[-len(args.defaults):]], args.defaults)) if args.defaults else {}
    defaults.update({a.arg: d for a, d in zip(args.kwonlyargs, args.kw_defaults) if d is not None})
    def argument(arg: ast.arg, prefix: str = "") -> str:
        annotation = "" if arg.arg in {"self", "cls"} else ": " + method.arguments.get(arg.arg, "Any")
        value = " = " + default_expression(defaults[arg.arg], known) if arg.arg in defaults else ""
        return prefix + arg.arg + annotation + value
    fields: list[str] = []
    for index, arg in enumerate(positional):
        fields.append(argument(arg))
        if args.posonlyargs and index == len(args.posonlyargs) - 1:
            fields.append("/")
    if args.vararg:
        fields.append(argument(args.vararg, "*"))
    elif args.kwonlyargs:
        fields.append("*")
    fields.extend(argument(a) for a in args.kwonlyargs)
    if args.kwarg:
        fields.append(argument(args.kwarg, "**"))
    return f"def {node.name}({', '.join(fields)}) -> {method.result}:"


def constant_assignment(node: ast.Assign | ast.AnnAssign, indent: str = "", known_integers: set[str] | None = None) -> list[str]:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    value = node.value
    if value is None:
        return [indent + dotted(targets[0]) + ": Any"]
    if isinstance(value, ast.Constant) and isinstance(value.value, (str, int, float, bool, bytes, type(None))):
        typ = "None" if value.value is None else type(value.value).__name__
        is_interface_id = any(isinstance(target, ast.Name) and target.id == "_myId" for target in targets)
        annotation = f"Literal[{dotted(value)}]" if typ in {"str", "int", "bool", "bytes"} and not is_interface_id else typ
        return [indent + dotted(t) + ": " + annotation + " = " + dotted(value) for t in targets if isinstance(t, ast.Name)]
    if isinstance(value, ast.BinOp) and isinstance(value.op, (ast.BitOr, ast.BitAnd, ast.BitXor, ast.LShift, ast.RShift, ast.Add, ast.Sub, ast.Mult)):
        if all(isinstance(leaf, (ast.BinOp, ast.UnaryOp, ast.operator, ast.unaryop, ast.Constant, ast.Name, ast.Load)) and (not isinstance(leaf, ast.Constant) or type(leaf.value) is int) and (not isinstance(leaf, ast.Name) or leaf.id in (known_integers or set())) for leaf in ast.walk(value)):
            return [indent + dotted(t) + ": int = " + dotted(value) for t in targets if isinstance(t, ast.Name)]
    if isinstance(value, ast.UnaryOp) and isinstance(value.op, (ast.USub, ast.UAdd)) and isinstance(value.operand, ast.Constant) and type(value.operand.value) in {int, float}:
        typ = type(value.operand.value).__name__
        annotation = f"Literal[{dotted(value)}]" if typ == "int" and isinstance(value.op, ast.USub) else typ
        return [indent + dotted(t) + ": " + annotation + " = " + dotted(value) for t in targets if isinstance(t, ast.Name)]
    return [indent + dotted(t) + ": Any = " + dotted(value) for t in targets if isinstance(t, ast.Name) and isinstance(value, (ast.UnaryOp, ast.BinOp, ast.Name, ast.Attribute))]


def emit_constants(source: Path) -> str:
    tree = ast.parse(source.read_text(encoding="utf-8-sig"), filename=str(source))
    lines = ["# Generated from installed native Python; do not edit.", "from typing import Any, Literal", ""]
    for node in effective(tree.body):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            lines.append(dotted(node))
        elif isinstance(node, ast.ClassDef):
            lines.append(f"class {node.name}" + ("(" + ", ".join(dotted(b) for b in node.bases) + ")" if node.bases else "") + ":")
            known_integers: set[str] = set()
            members = []
            for item in node.body:
                if isinstance(item, (ast.Assign, ast.AnnAssign)):
                    rendered = constant_assignment(item, "    ", known_integers)
                    members.extend(rendered)
                    scalar_integer = isinstance(item.value, ast.Constant) and type(item.value.value) in {int, bool}
                    signed_integer = isinstance(item.value, ast.UnaryOp) and isinstance(item.value.operand, ast.Constant) and type(item.value.operand.value) is int
                    if rendered and (": int = " in rendered[0] or scalar_integer or signed_integer):
                        targets = item.targets if isinstance(item, ast.Assign) else [item.target]
                        known_integers.update(target.id for target in targets if isinstance(target, ast.Name))
            lines.extend(members or ["    ..."])
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            lines.extend(constant_assignment(node))
    text = "\n".join(lines) + "\n"
    ast.parse(text)
    return text


def emit_native(model: NativeModel, docs: Documentation, output: Path) -> str:
    model.analyze_all()
    lines = ["# Generated offline from installed native wrappers and structured SDK metadata.",
             "from __future__ import annotations", "import ctypes", "from _ctypes import CFuncPtr", "import os", "import pathlib",
             "from typing import Any, Callable, Literal, TypeAlias, TypeVar", "from types import TracebackType",
             "from weakref import ref as WeakRef, finalize as Finalize", "from constants import constants as constants", ""]
    known = set(model.classes) | set(model.functions) | set(model.callbacks) | {"constants", "ctypes", "os", "pathlib", "True", "False", "None"}
    # CFUNCTYPE exports are factories at runtime, not instantiable typing aliases.
    for name, typ in model.callbacks.items():
        lines.append(f"def {name}(callback: {typ}) -> CFuncPtr: ...")
    lines.append("")
    for item in effective(model.tree.body):
        if isinstance(item, ast.ClassDef):
            bases = "(" + ", ".join(dotted(base) for base in item.bases) + ")" if item.bases else ""
            for decorator in item.decorator_list:
                lines.append("@" + dotted(decorator))
            lines.append(f"class {item.name}{bases}:")
            lines.extend(doc_literal(docs.text(item.name, model, output), "    "))
            attr_names = {dotted(t) for n in item.body if isinstance(n, ast.Assign) for t in n.targets}
            properties = {n.name for n in item.body if isinstance(n, ast.FunctionDef) and any(dotted(d) == "property" for d in n.decorator_list)}
            instance_attrs: dict[str, str] = {}
            for method in model.methods.values():
                if method.owner == item.name:
                    instance_attrs.update(method.attributes)
            for name, typ in instance_attrs.items():
                name = name.removeprefix("self.")
                if "." not in name and name not in attr_names | properties:
                    lines.append(f"    {name}: {typ}")
            emitted = False
            for node in effective(item.body):
                if isinstance(node, ast.FunctionDef):
                    method_key = item.name + "." + node.name
                    if any(dotted(d).endswith((".setter", ".deleter")) for d in node.decorator_list):
                        method_key += "@" + dotted(node.decorator_list[0]).rsplit(".", 1)[-1]
                    method = model.methods[method_key]
                    for decorator in node.decorator_list:
                        lines.append("    @" + dotted(decorator))
                    lines.append("    " + method_signature(method, known))
                    text = docs.text(method.symbol, model, output, method)
                    source_doc = ast.get_docstring(node)
                    if source_doc:
                        text = source_doc + "\n\n" + text
                    lines.extend(doc_literal(text, "        "))
                    lines.append("        ...")
                    emitted = True
                elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                    lines.extend(constant_assignment(node, "    "))
                    emitted = True
            if not emitted:
                lines.append("    ...")
            lines.append("")
        elif isinstance(item, ast.FunctionDef):
            method = model.methods[item.name]
            for decorator in item.decorator_list:
                lines.append("@" + dotted(decorator))
            lines.append(method_signature(method, known))
            lines.extend(doc_literal(docs.text(item.name, model, output, method), "    "))
            lines.append("    ...")
            lines.append("")
        elif isinstance(item, (ast.Assign, ast.AnnAssign)):
            names = [t.id for t in item.targets if isinstance(t, ast.Name)] if isinstance(item, ast.Assign) else [dotted(item.target)]
            for name in names:
                if name not in model.callbacks:
                    if isinstance(item.value, ast.Call) and dotted(item.value.func) == "TypeVar":
                        lines.append(f"{name} = {dotted(item.value)}")
                    else:
                        rendered = constant_assignment(item)
                        lines.extend(rendered or [f"{name}: Any"])
    text = "\n".join(lines) + "\n"
    ast.parse(text, filename=str(output))
    validate_types(text, output)
    return text


def validate_types(text: str, output: Path) -> None:
    """Fail rather than emit dangling annotation names accepted by ast.parse."""
    tree = ast.parse(text, filename=str(output))
    known = {"int", "float", "str", "bytes", "bool", "list", "tuple", "dict", "set", "type", "object", "BaseException", "None"}
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
            known.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            known.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            known.update(t.id for t in targets if isinstance(t, ast.Name))
    for descendant in ast.walk(tree):
        annotation = descendant.annotation if isinstance(descendant, (ast.arg, ast.AnnAssign)) else descendant.returns if isinstance(descendant, ast.FunctionDef) else None
        if annotation:
            unknown = {n.id for n in ast.walk(annotation) if isinstance(n, ast.Name)} - known
            if unknown:
                raise ValueError(f"Undefined annotation names in {output}: {sorted(unknown)}")
