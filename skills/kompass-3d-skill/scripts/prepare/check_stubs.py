# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Independently verify installed native wrappers against generated stubs, offline.

No generator modules or installed CAD modules are imported. Exit 0 means all
required checks passed, 1 means verification failed, and 2 means bad CLI input.
The report is always separate from the generator's report.json.
"""
from __future__ import annotations

import argparse
import ast
import builtins
import hashlib
import json
import os
import operator
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

SKILL_DIR = Path(__file__).resolve().parents[2]
DEFAULT_INSTALL = Path("/opt/ascon/kompas3d-v25")
DEFAULT_MYPY = "mypy"
CONTROL_TYPES = {
    "GetKompas": {"return": "IApplication | None"},
    "IApplication.GetDocuments": {"return": "IDocuments | None"},
    "ISketch.BeginEdit": {"readOnly": "bool", "return": "IFragmentDocument | None"},
    "ISketch.GetPoint3D": {"xIn": "float", "yIn": "float", "xOut": "float", "yOut": "float", "zOut": "float", "return": "tuple[bool, float, float, float]"},
    "IFace.GetLoops": {"return": "list[ILoop]"},
    "IExtrusion.SetProfiles": {"return": "None"},
}
FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)


def expression(node: ast.AST | None) -> str:
    return ast.unparse(node) if node is not None else "<missing>"


def canonical(node: ast.AST | None) -> str:
    """Compare expressions, not whitespace; retain exact literal types/values."""
    if node is None:
        return "<missing>"
    return ast.dump(node, include_attributes=False)


def effective(body: list[ast.stmt], kind: tuple | type) -> dict[str, ast.AST]:
    # In particular, the SECOND __init__ in installed wrappers is the only
    # callable constructor. This is not an overload declaration.
    return {node.name: node for node in body if isinstance(node, kind)}


def declarations(body: list[ast.stmt]) -> dict[str, ast.AST | None]:
    result = {}
    for node in body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    result[target.id] = node.value
    return result


def parameters(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[tuple]:
    args = node.args
    positional = [*args.posonlyargs, *args.args]
    defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    fields = [(a.arg, "positional_only" if i < len(args.posonlyargs) else "positional_or_keyword", canonical(default))
              for i, (a, default) in enumerate(zip(positional, defaults))]
    if args.vararg:
        fields.append((args.vararg.arg, "variadic_positional", "<missing>"))
    fields.extend((a.arg, "keyword_only", canonical(default)) for a, default in zip(args.kwonlyargs, args.kw_defaults))
    if args.kwarg:
        fields.append((args.kwarg.arg, "variadic_keyword", "<missing>"))
    return fields


def inventory(tree: ast.Module) -> tuple[dict, dict]:
    classes = effective(tree.body, ast.ClassDef)
    functions = effective(tree.body, FUNCTIONS)
    for cls in classes.values():
        functions.update({f"{cls.name}.{name}": node for name, node in effective(cls.body, FUNCTIONS).items()})
    return classes, functions


def issue(errors: list, code: str, symbol: str, detail: str) -> None:
    errors.append({"code": code, "symbol": symbol, "detail": detail})


def compare_surface(source: ast.Module, stub: ast.Module, module: str, errors: list, warnings: list) -> dict:
    source_classes, source_functions = inventory(source)
    stub_classes, stub_functions = inventory(stub)
    for name in sorted(source_classes.keys() ^ stub_classes.keys()):
        issue(errors, "class_inventory", f"{module}.{name}", "missing" if name in source_classes else "unexpected")
    for name in sorted(source_classes.keys() & stub_classes.keys()):
        actual, expected = stub_classes[name], source_classes[name]
        if [canonical(b) for b in actual.bases] != [canonical(b) for b in expected.bases]:
            issue(errors, "class_bases", f"{module}.{name}", f"expected {[expression(b) for b in expected.bases]}, got {[expression(b) for b in actual.bases]}")
        if [canonical(d) for d in actual.decorator_list] != [canonical(d) for d in expected.decorator_list]:
            issue(errors, "decorators", f"{module}.{name}", "class decorators differ")
        expected_constants, actual_constants = declarations(expected.body), declarations(actual.body)
        # Generated instance annotations have no initializer; these are not
        # additional runtime class constants.
        actual_values = {n: v for n, v in actual_constants.items() if v is not None}
        for member in sorted(expected_constants.keys() - actual_constants.keys()):
            issue(errors, "constant_missing", f"{module}.{name}.{member}", "class member missing")
        for member in sorted(actual_values.keys() - expected_constants.keys()):
            issue(errors, "constant_extra", f"{module}.{name}.{member}", "unexpected initialized class member")
        for member in sorted(expected_constants.keys() & actual_constants.keys()):
            if canonical(expected_constants[member]) != canonical(actual_constants[member]):
                issue(errors, "constant_value", f"{module}.{name}.{member}", f"expected {expression(expected_constants[member])}, got {expression(actual_constants[member])}")
    private_missing = []
    for name in sorted(source_functions.keys() - stub_functions.keys()):
        leaf = name.rsplit(".", 1)[-1]
        if leaf.startswith("_") and not (leaf.startswith("__") and leaf.endswith("__")):
            private_missing.append(name)
        else:
            issue(errors, "method_missing", f"{module}.{name}", "public function/method (including dunders) missing")
    callback_factories = {name: value for name, value in declarations(source.body).items()
                          if isinstance(value, ast.Call) and expression(value.func) == "ctypes.CFUNCTYPE"}
    for name in sorted(stub_functions.keys() - source_functions.keys() - callback_factories.keys()):
        issue(errors, "method_extra", f"{module}.{name}", "function/method has no native Python declaration")
    for name, value in callback_factories.items():
        if name not in stub_functions:
            issue(errors, "callback_missing", f"{module}.{name}", "native CFUNCTYPE factory is missing")
            continue
        node = stub_functions[name]
        if len(node.args.args) != 1 or node.args.defaults or node.args.vararg or node.args.kwarg:
            issue(errors, "callback_signature", f"{module}.{name}", "CFUNCTYPE factory must accept one required callback")
        # The assignment constructs a callable factory at runtime, so a def
        # declaration is legitimate here, unlike an invented wrapper method.
        scalar = {"c_bool": "bool", "c_double": "float", "c_float": "float", "c_wchar_p": "str", "c_char_p": "bytes", "c_void_p": "int | None"}
        def ctype_type(arg):
            name = expression(arg).removeprefix("ctypes.")
            if name in scalar:
                return scalar[name]
            if re.fullmatch(r"c_(?:u?int\d*|u?long(?:long)?|u?short|u?byte|size_t|ssize_t)", name):
                return "int"
            return None
        types = [ctype_type(arg) for arg in value.args]
        if types and all(types) and node.args.args:
            expected_callback = f"Callable[[{', '.join(types[1:])}], {types[0]}]"
            if canonical(node.args.args[0].annotation) != canonical(ast.parse(expected_callback, mode="eval").body):
                issue(errors, "callback_type", f"{module}.{name}", f"expected {expected_callback}")
    if private_missing:
        warnings.append({"code": "internal_functions_excluded", "module": module, "symbols": private_missing})
    for name in sorted(source_functions.keys() & stub_functions.keys()):
        expected, actual = source_functions[name], stub_functions[name]
        if type(expected) is not type(actual):
            issue(errors, "function_kind", f"{module}.{name}", "sync/async differs")
        if parameters(expected) != parameters(actual):
            issue(errors, "signature", f"{module}.{name}", f"expected {parameters(expected)!r}, got {parameters(actual)!r}")
        if [canonical(d) for d in expected.decorator_list] != [canonical(d) for d in actual.decorator_list]:
            issue(errors, "decorators", f"{module}.{name}", "function decorators differ")
    private = [n for n in source_functions if n.rsplit(".", 1)[-1].startswith("_") and not n.rsplit(".", 1)[-1].endswith("__")]
    return {"source_classes": len(source_classes), "stub_classes": len(stub_classes), "source_functions_methods": len(source_functions),
            "stub_functions_methods": len(stub_functions) - len(callback_factories.keys() & stub_functions.keys()), "callback_factories": len(callback_factories), "internal_functions": len(private), "internal_functions_excluded": len(private_missing),
            "source_class_constants": sum(len(declarations(c.body)) for c in source_classes.values()),
            "effective_duplicate_definitions": sum(Counter(n.name for n in body if isinstance(n, FUNCTIONS))[name] - 1
                for body in [source.body, *[c.body for c in source_classes.values()]] for name in effective(body, FUNCTIONS))}


def bound_names(body: list[ast.stmt]) -> set[str]:
    result = set(declarations(body))
    for node in body:
        if isinstance(node, (ast.ClassDef, *FUNCTIONS)):
            result.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            result.update(alias.asname or alias.name.split(".")[0] for alias in node.names if alias.name != "*")
    return result


def annotation_names(node: ast.AST) -> set[str]:
    """Forward refs are expressions too; Literal strings are values, not names."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return annotation_names(ast.parse(node.value, mode="eval").body)
    if isinstance(node, ast.Subscript):
        head = expression(node.value).rsplit(".", 1)[-1]
        result = annotation_names(node.value)
        if head == "Literal":
            return result | {n.id for n in ast.walk(node.slice) if isinstance(n, ast.Name)}
        if head == "Annotated":
            first = node.slice.elts[0] if isinstance(node.slice, ast.Tuple) else node.slice
            return result | annotation_names(first)
    if isinstance(node, ast.Name):
        return {node.id}
    result = set()
    for child in ast.iter_child_nodes(node):
        result.update(annotation_names(child))
    return result


def validate_type_names(tree: ast.Module, module: str, errors: list) -> int:
    global_names = bound_names(tree.body) | set(vars(builtins))
    variable_factories = {"TypeVar", "ParamSpec", "TypeVarTuple"}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module in {"typing", "typing_extensions"}:
            variable_factories.update(alias.asname or alias.name for alias in node.names if alias.name in variable_factories)
    typevars = {name for name, value in declarations(tree.body).items()
                if isinstance(value, ast.Call) and expression(value.func).rsplit(".", 1)[-1] in variable_factories}
    count = 0

    def check(node: ast.AST, scope: set[str], symbol: str, bound_vars: set[str]) -> None:
        nonlocal count
        count += 1
        try:
            names = annotation_names(node)
        except SyntaxError as exc:
            issue(errors, "annotation_syntax", f"{module}.{symbol}", str(exc))
            return
        for name in sorted(names - scope):
            issue(errors, "undefined_type", f"{module}.{symbol}", f"{name} in {expression(node)}")
        for name in sorted((names & typevars) - bound_vars):
            issue(errors, "unbound_typevar", f"{module}.{symbol}", f"{name} is not bound by this class/function")

    def walk(body: list[ast.stmt], scope: set[str], owner: str = "", class_vars: set[str] | None = None) -> None:
        class_vars = class_vars or set()
        for node in body:
            if isinstance(node, ast.ClassDef):
                local_vars = set().union(*(annotation_names(b) & typevars for b in node.bases)) if node.bases else set()
                for base in node.bases:
                    check(base, scope, owner + node.name, local_vars)
                walk(node.body, scope | bound_names(node.body), owner + node.name + ".", local_vars)
            elif isinstance(node, FUNCTIONS):
                args = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
                args += [a for a in (node.args.vararg, node.args.kwarg) if a]
                annotations = [a.annotation for a in args if a.annotation]
                function_vars = class_vars | set().union(*(annotation_names(a) & typevars for a in annotations))
                for annotation in [*annotations, *([node.returns] if node.returns else [])]:
                    check(annotation, scope, owner + node.name, function_vars)
            elif isinstance(node, ast.AnnAssign):
                check(node.annotation, scope, owner + expression(node.target), class_vars)
                if expression(node.annotation).rsplit(".", 1)[-1] == "TypeAlias" and node.value:
                    check(node.value, scope, owner + expression(node.target), typevars)
    walk(tree.body, global_names)
    return count


def check_controls(tree: ast.Module, errors: list) -> int:
    _, methods = inventory(tree)
    checked = 0
    for symbol, expected in CONTROL_TYPES.items():
        node = methods.get(symbol)
        if node is None:
            issue(errors, "control_missing", symbol, "required golden symbol missing")
            continue
        annotations = {a.arg: a.annotation for a in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]}
        annotations["return"] = node.returns
        for name, typ in expected.items():
            if canonical(annotations.get(name)) != canonical(ast.parse(typ, mode="eval").body):
                issue(errors, "control_type", symbol, f"{name}: expected {typ}, got {expression(annotations.get(name))}")
            checked += 1
        if symbol == "ISketch.GetPoint3D":
            expected_names = ["self", "xIn", "yIn", "xOut", "yOut", "zOut"]
            if [a.arg for a in node.args.args] != expected_names or node.args.defaults or node.args.kw_defaults:
                issue(errors, "control_required_outputs", symbol, "all five wrapper arguments must be required and in native order")
    return checked


def check_enum_aliases(trees: dict, docs: Path, metadata: Path, errors: list) -> dict:
    """Validate SDK aliases and inline Literals using tables, constants and C++ inputs."""
    pages = [json.loads(line) for line in docs.read_text(encoding="utf-8").splitlines() if line.strip()]
    enum_pages = {}
    usage = {}
    for page in pages:
        for name in set(re.findall(r"\[([A-Za-z_]\w*)\]\(<webhelp:", page.get("content", ""))):
            usage.setdefault(name, []).append(page.get("content", ""))
        if page.get("section") != "Константы API":
            continue
        match = re.match(r"^([A-Za-z_]\w*)\s*(?:[-—–]|$)", page.get("title", ""))
        if match:
            enum_pages.setdefault(match.group(1), []).append(page)
    aliases = {}
    installed_modules = {}
    for module in ("constants", "constants3d"):
        if module not in trees:
            continue
        installed = {}
        binary = {ast.BitOr: operator.or_, ast.BitAnd: operator.and_, ast.BitXor: operator.xor,
                  ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
                  ast.LShift: operator.lshift, ast.RShift: operator.rshift}
        unary = {ast.USub: operator.neg, ast.UAdd: operator.pos, ast.Invert: operator.invert}
        def evaluate_constant(value):
            if isinstance(value, ast.Constant) and type(value.value) is int:
                return value.value
            if isinstance(value, ast.Name):
                return installed.get(value.id)
            if isinstance(value, ast.UnaryOp) and type(value.op) in unary:
                operand = evaluate_constant(value.operand)
                return unary[type(value.op)](operand) if operand is not None else None
            if isinstance(value, ast.BinOp) and type(value.op) in binary:
                left, right = evaluate_constant(value.left), evaluate_constant(value.right)
                if left is not None and right is not None:
                    if isinstance(value.op, (ast.LShift, ast.RShift)) and not 0 <= right <= 64:
                        return None
                    return binary[type(value.op)](left, right)
            return None
        for assignment in ast.walk(trees[module][0]):
            if isinstance(assignment, (ast.Assign, ast.AnnAssign)):
                value = evaluate_constant(assignment.value)
                targets = assignment.targets if isinstance(assignment, ast.Assign) else [assignment.target]
                if value is not None:
                    installed.update({target.id: value for target in targets if isinstance(target, ast.Name)})
        installed_modules[module] = installed

    tables = {}
    def table(name, module=None):
        key = module, name
        if key in tables:
            return tables[key]
        matches = enum_pages.get(name, [])
        if len(matches) != 1:
            issue(errors, "enum_identity", name, "must identify one exact SDK enum table")
            tables[key] = None
            return None
        rows = []
        descriptions = {}
        malformed = False
        for line in matches[0]["content"].splitlines():
            cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", line.strip())[1:-1]]
            if not line.lstrip().startswith("|"):
                continue
            if cells and re.fullmatch(r"`?[A-Za-z_]\w*`?", cells[0]) and cells[0] not in ("Name", "Column"):
                if len(cells) != 3:
                    malformed = True
                    continue
                number = cells[1].strip("` ").replace("−", "-")
                if not re.fullmatch(r"[+-]?(?:0[xX][0-9a-fA-F]+|\d+)", number) or not cells[2]:
                    malformed = True
                    continue
                member = cells[0].strip("`")
                if member in descriptions and descriptions[member] != cells[2]:
                    malformed = True
                descriptions[member] = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", cells[2]).replace(r"\|", "|").strip()
                rows.append((member, int(number, 16 if "x" in number.lower() else 10)))
            elif len(cells) > 1 and not cells[0] and re.fullmatch(r"[+-]?(?:0[xX][0-9a-fA-F]+|\d+)", cells[1]):
                malformed = True
        if malformed or not rows or len(dict(rows)) != len(set(rows)):
            issue(errors, "enum_table", name, "incomplete, conflicting or multi-column SDK table")
        evidence = matches[0].get("title", "") + "\n" + matches[0]["content"]
        evidence += "\n" + "\n".join(usage.get(name, []))
        values = [value for _, value in rows if value > 0]
        unsafe = bool(re.search(r"flag|mask|флаг|маск|побитов|битов|комбинац|сочетан|логическ.{0,25}(?:или|or)|произвольн|пользовательск.{0,35}(?:значени|тип|код)|и\s+выше|и\s+более", evidence, re.I))
        unsafe |= len(set(values)) >= 3 and all(value & (value - 1) == 0 for value in values)
        candidates = [installed_modules[module]] if module else installed_modules.values()
        if not any(all(installed.get(member) == value for member, value in rows) for installed in candidates):
            issue(errors, "enum_installed_values", name, "SDK table disagrees with installed constant values")
        tables[key] = rows, descriptions, unsafe
        return tables[key]

    def validate(name, annotation, text, module=None, parameter=None):
        data = table(name, module)
        if data is None:
            return
        rows, descriptions, unsafe = data
        if expression(annotation) != "int":
            if unsafe:
                issue(errors, "enum_domain", name, "flags or open domains must retain int")
            expected = sorted({value for _, value in rows})
            expected_ast = ast.parse("Literal[" + ", ".join(map(str, expected)) + "]", mode="eval").body if expected else None
            if not expected or canonical(annotation) != canonical(expected_ast):
                issue(errors, "enum_values", name, "Literal values differ from the SDK table")
        mapping = "\n".join(f"{value} — {member}: {descriptions[member]}" for member, value in rows)
        if parameter is not None:
            header = f"Допустимые значения {parameter} ({name}):\n"
            blocks = re.findall(r"(?m)^" + re.escape(header) + r"((?:[^\n]+\n?)+)", text)
            correct_mapping = blocks == [mapping] or blocks == [mapping + "\n"]
        else:
            correct_mapping = all(line in text.splitlines() for line in mapping.splitlines())
        if not correct_mapping:
            issue(errors, "enum_mapping", name, f"missing or incorrect SDK mapping for {parameter or name}")

    for module in installed_modules:
        body = trees[module][1].body
        for index, node in enumerate(body):
            if not isinstance(node, ast.AnnAssign) or expression(node.annotation) != "TypeAlias":
                continue
            name = expression(node.target)
            doc = body[index + 1] if index + 1 < len(body) else None
            text = doc.value.value if isinstance(doc, ast.Expr) and isinstance(doc.value, ast.Constant) and isinstance(doc.value.value, str) else ""
            validate(name, node.value, text, module)
            aliases[module, name] = node.value
    if "ksapi" not in trees:
        return {"aliases": len(aliases), "input_parameters": 0, "inline_input_parameters": 0}
    cpp = {}
    def collect(value):
        if isinstance(value, dict):
            if "name_c" in value:
                cpp[value["name_c"]] = value
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)
    collect(json.loads(metadata.read_text(encoding="utf-8-sig")))
    source, stub = trees["ksapi"]
    _, source_methods = inventory(source)
    _, stub_methods = inventory(stub)
    imported = {alias.asname or alias.name: (node.module, alias.name)
                for node in stub.body if isinstance(node, ast.ImportFrom)
                for alias in node.names if (node.module, alias.name) in aliases}
    checked = inline_checked = 0
    for symbol, method in stub_methods.items():
        native_method = source_methods.get(symbol)
        if native_method is None:
            continue
        for argument in [*method.args.posonlyargs, *method.args.args, *method.args.kwonlyargs]:
            name = expression(argument.annotation)
            inline = isinstance(argument.annotation, ast.Subscript) and expression(argument.annotation.value) == "Literal"
            if name not in imported and not inline:
                continue
            enum = imported[name][1] if not inline else None
            if not inline and expression(aliases[imported[name]]) == "int":
                issue(errors, "enum_binding", symbol, "open/flag aliases must not narrow parameters")
            evidence = []
            reassigned = any(isinstance(node, ast.Name) and node.id == argument.arg
                             and isinstance(node.ctx, (ast.Store, ast.Del)) for node in ast.walk(native_method))
            for call in ast.walk(native_method):
                if not isinstance(call, ast.Call) or not expression(call.func).startswith("ksapi."):
                    continue
                parameters_cpp = cpp.get(expression(call.func)[6:], {}).get("parameters", [])
                offset = len(call.args) - len(parameters_cpp)
                for index, value in enumerate(call.args):
                    if not any(isinstance(node, ast.Name) and node.id == argument.arg for node in ast.walk(value)):
                        continue
                    parameter = parameters_cpp[index - offset] if offset >= 0 and offset <= index < len(call.args) else {}
                    direct = isinstance(value, ast.Name) and value.id == argument.arg
                    input_cpp = parameter.get("in") in (True, "True", "true")
                    evidence.append(parameter.get("type_cpp") if direct and input_cpp and not reassigned else None)
                if any(isinstance(node, ast.Name) and node.id == argument.arg for keyword in call.keywords for node in ast.walk(keyword.value)):
                    evidence.append(None)
            if inline:
                # Identity comes ONLY from direct C++ input metadata, never the
                # method mapping, matching integer values, or generator reports.
                enum = evidence[0] if evidence else None
                inline_checked += 1
            if not enum or (inline and enum not in enum_pages) or not evidence or any(value != enum for value in evidence):
                issue(errors, "enum_binding", symbol, f"{argument.arg}: no consistent direct SDK input evidence for {enum or 'an enum'}")
            elif inline:
                validate(enum, argument.annotation, ast.get_docstring(method) or "", parameter=argument.arg)
            checked += 1
    return {"aliases": len(aliases), "input_parameters": checked, "inline_input_parameters": inline_checked}


def check_documentation(tree: ast.Module, docs: Path, errors: list) -> int:
    if not docs.is_file():
        issue(errors, "docs_missing", str(docs), "run scripts/prepare/prepare_docs.py first")
        return 0
    pages = [json.loads(line) for line in docs.read_text(encoding="utf-8").splitlines() if line.strip()]
    classes, methods = inventory(tree)
    checked = 0
    for symbol in CONTROL_TYPES:
        # GetKompas is an exported global helper, not a native interface page.
        if "." not in symbol:
            continue
        identity = "ksapi_" + symbol.replace(".", "_").lower()
        matches = [p for p in pages if Path(urlparse(str(p.get("source_html", ""))).path).stem.lower() == identity
                   and p.get("section") == "API интерфейсов. KsAPI"]
        if len(matches) != 1:
            issue(errors, "docs_identity", symbol, f"expected one exact native page {identity}, found {len(matches)}")
            continue
        node = methods.get(symbol)
        text = ast.get_docstring(node) or "" if node else ""
        page = matches[0]
        content = page.get("content", "")
        owner = symbol.split(".")[0]
        class_text = ast.get_docstring(classes[owner]) or "" if owner in classes else ""
        links = re.findall(r"(?m)^- \[[^\]]+\]\(([^\n)]+)\)", class_text)
        if "Источники SDK:" not in class_text or not links:
            issue(errors, "docs_mismatch", symbol, "missing class-level SDK sources")
        elif page.get("markdown_path"):
            expected = Path(str(page["markdown_path"]))
            if not any(Path(href.split("#", 1)[0]).name == expected.name for href in links):
                issue(errors, "docs_mismatch", symbol, "class sources omit the native SDK document")
        if "Источник SDK:" in text or "Источники SDK:" in text:
            issue(errors, "docs_mismatch", symbol, "SDK sources must be listed on the class, not the method")
        if isinstance(content, str):
            # The stub intentionally omits C++ declarations and WebHelp menus.
            # Independently check the remaining SDK paragraphs, not byte-for-byte
            # inclusion of the full page or imports from the rendering code.
            sections = re.split(r"(?m)^(Синтаксис KsAPI:|Иерархия:|Подразделы:|Входные параметры:|Возвращаемое значение:|Примечание:|Определенные типы:|Описание:|Значение свойства:)\s*$", content)
            retained = [sections[0]]
            retained.extend(sections[i] + "\n\n" + sections[i + 1] for i in range(1, len(sections), 2)
                            if sections[i] not in {"Синтаксис KsAPI:", "Иерархия:", "Подразделы:"})
            paragraphs = [paragraph.strip() for section in retained
                          for paragraph in re.split(r"\n\s*\n", section)
                          if paragraph.strip() and not re.fullmatch(r"\[Интерфейс\.{3}\]\(<[^>]+>\)", paragraph.strip())]
            if any(paragraph not in text for paragraph in paragraphs):
                issue(errors, "docs_mismatch", symbol, "native SDK explanation is missing from the method docstring")
        checked += 1
    return checked


def native_review(source: ast.Module, stub: ast.Module, metadata_path: Path) -> list[dict]:
    """Record independently selected wrapper/C++ evidence for each marshal family."""
    data = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
    cpp = {}
    def collect(value):
        if isinstance(value, dict):
            if "name_c" in value:
                cpp[value["name_c"]] = value
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)
    collect(data)
    aliases = {}
    abi = {}
    for assignment in ast.walk(source):
        if not isinstance(assignment, ast.Assign):
            continue
        for target in assignment.targets:
            value = expression(assignment.value)
            if isinstance(target, ast.Name) and value.startswith("ksapi.") and value.count(".") == 1:
                aliases[target.id] = value.removeprefix("ksapi.")
            elif isinstance(target, ast.Attribute) and target.attr in {"restype", "argtypes"}:
                owner = expression(target.value)
                name = owner.removeprefix("ksapi.") if owner.startswith("ksapi.") else aliases.get(owner, owner)
                abi.setdefault(name, {})[target.attr] = value
    _, functions = inventory(source)
    _, stubs = inventory(stub)
    patterns = {
        "nullable_interface": ("IApplication.GetDocuments", "A native ObjectReference is wrapped as IDocuments and zero becomes None."),
        "scalar_boolean": ("ISketch.BeginEdit", "The native bool readOnly is a required Python bool input, not an API7 default."),
        "output_reference_tuple": ("ISketch.GetPoint3D", "The wrapper requires output initializers and returns status followed by three c_double.value fields."),
        "object_vector_output": ("IFace.GetLoops", "FromObjectReferenceVector constructs ILoop elements; the Python return is a list, not the C pointer."),
        "object_vector_input_void": ("IExtrusion.SetProfiles", "ToObjectReferenceVector marshals the input; the wrapper has no return expression, regardless of native ctypes restype."),
        "encoded_string": ("IAPIObject.QueryInterface", "The Python id string is explicitly encoded as UTF-8. This low-level method is absent from the C++ JSON; use the installed ctypes argtypes as ABI evidence instead."),
    }
    dynamic = {
        "encoded_string": (lambda t: ".encode(" in t, "Python str is encoded before the C char pointer call."),
        "ref_string": (lambda t: "RefString(" in t and ".value" in t, "RefString owns a native string pointer; the returned .value is Python str."),
        "callback": (lambda t: bool(re.search(r"\b\w+Handler\(", t)), "The wrapper constructs a CFUNCTYPE callback; its signature comes from the declaration and native metadata."),
        "scalar_return": (lambda t: bool(re.search(r"return res\b", t)) and not any(x in t for x in ("From", "Ptr", "res if", "_ref", "RefString")), "The scalar return is checked against the configured native restype and C++ declaration."),
        "primitive_vector": (lambda t: bool(re.search(r"From(?:Double|Int|Uint|String|Bool)\w*Vector\(", t)), "A primitive vector conversion returns a Python list rather than an opaque native pointer."),
        "nested_vector": (lambda t: bool(re.search(r"From\w*(?:VectorVector|Vector2d)\(", t)), "Nested vector helpers preserve nested Python list shape."),
    }
    for pattern, (predicate, rationale) in dynamic.items():
        for symbol, node in functions.items():
            text = expression(node)
            calls = [expression(n.func).removeprefix("ksapi.") for n in ast.walk(node) if isinstance(n, ast.Call) and expression(n.func).startswith("ksapi.")]
            if predicate(text) and any(call in cpp for call in calls):
                patterns[pattern] = (symbol, rationale)
                break
    result = []
    for pattern, (symbol, rationale) in patterns.items():
        node = functions.get(symbol)
        if node is None:
            continue
        calls = [expression(n.func).removeprefix("ksapi.") for n in ast.walk(node) if isinstance(n, ast.Call) and expression(n.func).startswith("ksapi.")]
        declarations_cpp = [{"symbol": name, "return": cpp[name].get("return_value"), "parameters": cpp[name].get("parameters")} for name in calls if name in cpp]
        stub_node = stubs.get(symbol)
        classifications = []
        if not declarations_cpp:
            classifications.append("cpp_metadata_absent")
        if pattern == "nullable_interface":
            classifications.append("native_reference_wrapped_nullable_interface")
        if pattern == "output_reference_tuple":
            classifications.append("native_output_parameters_promoted_to_python_tuple")
        if pattern in {"object_vector_output", "primitive_vector", "nested_vector"}:
            classifications.append("native_vector_pointer_converted_to_python_list")
        if pattern == "encoded_string":
            classifications.append("python_string_encoded_for_native_abi")
        if pattern == "ref_string":
            classifications.append("native_string_pointer_dereferenced_to_python_string")
        if pattern == "callback":
            classifications.append("python_callable_marshaled_as_ctypes_callback")
        returns_value = any(isinstance(item, ast.Return) and item.value is not None for item in ast.walk(node))
        if not returns_value:
            classifications.append("native_result_discarded_python_returns_none")
        for name in calls:
            cpp_return = cpp.get(name, {}).get("return_value", {}).get("type_cpp")
            restype = abi.get(name, {}).get("restype")
            if cpp_return == "void" and restype is None:
                classifications.append("cpp_void_but_ctypes_restype_unconfigured_defaults_to_int")
        result.append({"pattern": pattern, "symbol": symbol, "source_line": node.lineno,
                       "wrapper": expression(node), "cpp": declarations_cpp,
                       "ctypes_abi": {name: abi[name] for name in calls if name in abi},
                       "stub_return": expression(stub_node.returns) if stub_node else None,
                       "stub_parameters": {a.arg: expression(a.annotation) for a in stub_node.args.args} if stub_node else {},
                       "reconciliation": {"classifications": sorted(set(classifications)),
                                          "python_contract_authority": "wrapper return expression and conversions; ctypes ABI for direct native results",
                                          "cpp_role": "semantic evidence, not a replacement for wrapper runtime behavior",
                                          "runtime_validated": False},
                       "review": rationale})
    return result


POSITIVE_PROGRAM = '''from typing import assert_type
from ksapi import GetKompas, IApplication, IDocuments, ISketch, IFragmentDocument, IFace, ILoop, IExtrusion
assert_type(GetKompas(), IApplication | None)
def check(app: IApplication, sketch: ISketch, face: IFace, extrusion: IExtrusion) -> None:
    assert_type(app.GetReference(), int)
    assert_type(IApplication(1234), IApplication)
    assert_type(app.GetDocuments(), IDocuments | None)
    assert_type(sketch.BeginEdit(True), IFragmentDocument | None)
    assert_type(sketch.GetPoint3D(1.0, 2.0, 0.0, 0.0, 0.0), tuple[bool, float, float, float])
    assert_type(face.GetLoops(), list[ILoop])
    assert_type(extrusion.SetProfiles([]), None)
'''
NEGATIVE_CASES = {
    "begin_edit_type": "sketch.BeginEdit('not bool')",
    "required_output_initializers": "sketch.GetPoint3D(1.0, 2.0)",
    "point_input_type": "sketch.GetPoint3D('wrong', 2.0, 0.0, 0.0, 0.0)",
    "loop_element_type": "loops: list[int] = face.GetLoops()",
    "nullable_application": "app: IApplication = GetKompas()",
    "void_set_profiles": "answer: int = extrusion.SetProfiles([])",
    "unknown_method": "sketch.ThisMethodDoesNotExist()",
}


def run_mypy(stubs: Path, executable: Path | str, errors: list, warnings: list) -> dict:
    requested = str(executable)
    resolved = shutil.which(requested)
    if resolved is None:
        issue(errors, "mypy_missing", requested, "mypy executable unavailable; install it on PATH or pass --mypy /path/to/mypy; verifier never accesses the network")
        return {"available": False, "requested_executable": requested}
    # Resolve relative overrides before subprocess switches to a temporary cwd.
    executable = Path(resolved).resolve()
    env = dict(os.environ, MYPYPATH=str(stubs.resolve()))
    env.pop("PYTHONPATH", None)
    with tempfile.TemporaryDirectory(prefix="kompas-stub-verification-") as directory:
        temp = Path(directory)
        config = temp / "mypy.ini"
        config.write_text("[mypy]\npython_version = 3.11\nfollow_imports = normal\nshow_error_codes = True\n", encoding="utf-8")
        base = [str(executable), "--config-file", str(config), "--no-incremental", "--cache-dir", str(temp / "cache"), "--no-error-summary", "--show-column-numbers"]
        def run(targets: list[str], extra: list[str] | None = None) -> dict:
            completed = subprocess.run([*base, *(extra or []), *targets], env=env, cwd=temp, text=True, capture_output=True, timeout=180)
            return {"exit_code": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr}
        full = run([str(p.resolve()) for p in sorted(stubs.glob("*.pyi"))])
        if full["exit_code"]:
            issue(errors, "mypy_stubs", "*.pyi", "full stub validation failed; see mypy.full in verification.json")
        positive = temp / "positive.py"
        positive.write_text(POSITIVE_PROGRAM, encoding="utf-8")
        # Imported SDK declaration defects are already captured by the full
        # validation. Isolate client contracts from those unrelated defects.
        client_config = temp / "client-mypy.ini"
        client_config.write_text(config.read_text(encoding="utf-8") + "follow_imports_for_stubs = True\n", encoding="utf-8")
        client_options = ["--config-file", str(client_config), "--follow-imports=silent"]
        positive_result = run([str(positive)], client_options)
        if positive_result["exit_code"]:
            issue(errors, "mypy_positive", "control clients", "valid control program failed type checking")
        negatives = {}
        for name, statement in NEGATIVE_CASES.items():
            target = temp / f"negative_{name}.py"
            target.write_text("from ksapi import GetKompas, IApplication, ISketch, IFace, IExtrusion\n"
                              "def check(sketch: ISketch, face: IFace, extrusion: IExtrusion) -> None:\n    " + statement + "\n", encoding="utf-8")
            outcome = run([str(target)], client_options)
            rejected = outcome["exit_code"] == 1 and f"{target.name}:3:" in outcome["stdout"]
            negatives[name] = {**outcome, "rejected_at_client": rejected}
            if not rejected:
                issue(errors, "mypy_negative", name, "invalid program was not rejected at its own offending statement")
        enum_clients = {}
        ksapi_path = stubs / "ksapi.pyi"
        if ksapi_path.is_file():
            _, methods = inventory(ast.parse(ksapi_path.read_text(encoding="utf-8")))
            add = methods.get("IDocuments.Add")
            if add and any(a.arg == "documentType" and (expression(a.annotation) == "DocumentTypeEnum"
                           or isinstance(a.annotation, ast.Subscript) and expression(a.annotation.value) == "Literal")
                           for a in add.args.args):
                for name, value, valid in (("named_constant", "constants.ksDocumentPart", True),
                                           ("numeric_literal", "4", True), ("invalid_value", "12345", False)):
                    client = temp / f"enum_{name}.py"
                    client.write_text("from constants import constants\nfrom ksapi import IDocuments\n"
                                      "def check(documents: IDocuments) -> None:\n"
                                      f"    documents.Add({value}, True)\n", encoding="utf-8")
                    outcome = run([str(client)], client_options)
                    accepted = outcome["exit_code"] == 0
                    rejected = outcome["exit_code"] == 1 and f"{client.name}:4:" in outcome["stdout"]
                    enum_clients[name] = outcome
                    if (valid and not accepted) or (not valid and not rejected):
                        issue(errors, "mypy_enum", name, "enum client contract check failed")
        return {"available": True, "executable": str(executable), "full": full,
                "positive": positive_result, "negative": negatives, "enum_clients": enum_clients}


def file_fingerprint(path: Path) -> dict:
    """Hash exact bytes without importing any input or trusting generator hashes."""
    record = {"path": str(path.resolve()), "exists": path.is_file()}
    if record["exists"]:
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
                size += len(block)
        record.update(sha256=digest.hexdigest(), bytes=size)
    return record


def fingerprints(install: Path, stubs: Path, docs: Path, metadata: Path) -> dict:
    return {"inputs": {"wrappers": {path.name: file_fingerprint(path) for path in sorted((install / "Bin").glob("*.py"))},
                       "documentation": file_fingerprint(docs), "metadata": file_fingerprint(metadata),
                       "verifier": file_fingerprint(Path(__file__))},
            "outputs": {path.name: file_fingerprint(path) for path in sorted(stubs.glob("*.pyi"))}}


def verify(install: Path, stubs: Path, docs: Path, metadata: Path, mypy: Path | str | None = DEFAULT_MYPY) -> dict:
    errors, warnings = [], []
    before = fingerprints(install, stubs, docs, metadata)
    report = {"schema_version": 1, "independent": True, "offline": True,
              "inputs": {"install": str(install), "stubs": str(stubs), "docs": str(docs), "metadata": str(metadata)},
              "policy": {"public_and_dunder_functions": "exact effective declarations; last duplicate wins",
                         "internal_functions": "inventoried; exclusions explicitly reported",
                         "classes_and_bases": "exact, including internal classes", "sdk_runtime": "not imported or started"},
              "limitations": [
                  "No native module imports, CAD startup, DLL execution, network, or runtime behavior validation.",
                  "C++/ctypes/Python return reconciliation is representative by marshalling family, not an exhaustive manual review of all SDK returns.",
                  "Unconfigured ctypes restypes, pointer lifetime/ownership, nullability, callback lifetimes and SDK runtime defects are not proven safe by static checks.",
                  "Control documentation checks cover five native methods; exhaustive docstring-owner/local-link auditing is a separate artifact audit.",
                  "Hashes identify the exact verification inputs and stubs; regenerate and rerun verification after any recorded file changes.",
              ],
              "fingerprints": {"algorithm": "sha256", **before},
              "files": {}, "errors": errors, "warnings": warnings}
    trees = {}
    expected = {path.stem for path in (install / "Bin").glob("*.py")}
    actual = {path.stem for path in stubs.glob("*.pyi")}
    for name in sorted(expected - actual):
        issue(errors, "stub_missing", name, "installed Python wrapper has no generated stub")
    for name in sorted(actual - expected):
        issue(errors, "stub_unexpected", name, "generated stub has no installed Python source")
    for name in sorted(expected & actual):
        try:
            source = ast.parse((install / "Bin" / f"{name}.py").read_text(encoding="utf-8-sig"))
            stub = ast.parse((stubs / f"{name}.pyi").read_text(encoding="utf-8-sig"))
        except (SyntaxError, UnicodeError) as exc:
            issue(errors, "parse", name, str(exc))
            continue
        trees[name] = (source, stub)
        counts = compare_surface(source, stub, name, errors, warnings)
        counts["annotations_checked"] = validate_type_names(stub, name, errors)
        report["files"][f"{name}.pyi"] = counts
    if not expected:
        issue(errors, "install_missing", str(install / "Bin"), "no installed Python wrappers found")
    if "ksapi" in trees:
        source, stub = trees["ksapi"]
        report["control_annotations_checked"] = check_controls(stub, errors)
        report["control_documentation_checked"] = check_documentation(stub, docs, errors)
        if metadata.is_file():
            if docs.is_file():
                report["enum_checks"] = check_enum_aliases(trees, docs, metadata, errors)
            report["native_marshalling_review"] = native_review(source, stub, metadata)
        else:
            issue(errors, "metadata_missing", str(metadata), "native C++ evidence cannot be reviewed")
    if mypy is not None and actual:
        report["mypy"] = run_mypy(stubs, mypy, errors, warnings)
    after = fingerprints(install, stubs, docs, metadata)
    stable = before == after
    report["fingerprints"]["stable_during_verification"] = stable
    if not stable:
        report["fingerprints"]["after"] = after
        issue(errors, "artifacts_changed", "verification inputs/outputs", "files changed during verification; regenerate if needed and rerun before trusting this report")
    report["counts"] = {"files": len(report["files"]), "errors": len(errors), "warnings": len(warnings),
                        **{key: sum(value.get(key, 0) for value in report["files"].values())
                           for key in ("source_classes", "stub_classes", "source_functions_methods", "stub_functions_methods", "source_class_constants", "annotations_checked")}}
    report["error_counts"] = dict(Counter(error["code"] for error in errors))
    report["ok"] = not errors
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", "--kompas-root", type=Path, default=DEFAULT_INSTALL)
    parser.add_argument("--stubs", "--output", type=Path, default=SKILL_DIR / ".cache/kompas-stubs")
    parser.add_argument("--docs", type=Path, default=SKILL_DIR / ".cache/kompas-sdk-docs/llm/pages.jsonl")
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--mypy", default=DEFAULT_MYPY, help="mypy executable name on PATH or explicit executable path (default: mypy)")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    metadata = args.metadata or args.install / "SDK/KsAPIC/C/Include/KsAPIC.json"
    try:
        report = verify(args.install, args.stubs, args.docs, metadata, args.mypy)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        report = {"schema_version": 1, "independent": True, "offline": True, "ok": False,
                  "counts": {"errors": 1}, "errors": [{"code": "verification_input", "detail": str(exc)}]}
    destination = args.report or args.stubs / "verification.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "report": str(destination), "counts": report["counts"], "error_counts": report.get("error_counts", {})}, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
