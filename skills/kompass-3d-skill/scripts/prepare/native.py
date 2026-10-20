"""Read native Python wrappers and SDK metadata without executing either input."""
from __future__ import annotations

import ast
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def dotted(node: ast.AST | None) -> str:
    return ast.unparse(node) if node is not None else ""


def union(*types: str) -> str:
    parts: list[str] = []
    for typ in types:
        # Split only top-level unions (Callable/list parameters can contain unions).
        depth = 0
        start = 0
        for index, char in enumerate(typ + "|"):
            depth += char in "[("
            depth -= char in "])"
            if char == "|" and depth == 0:
                part = typ[start:index].strip()
                if part and part not in parts:
                    parts.append(part)
                start = index + 1
    if "Any" in parts:
        return "Any"
    if "list[Any]" in parts and any(p.startswith("list[") and p != "list[Any]" for p in parts):
        parts.remove("list[Any]")
    return " | ".join(parts) or "Any"


def effective(body: list[ast.stmt]) -> list[ast.stmt]:
    """Python overwrites previous definitions, including generated constructors."""
    last = {node.name: i for i, node in enumerate(body) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    return [node for i, node in enumerate(body)
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            or last[node.name] == i
            or any(dotted(d) == "property" or dotted(d).endswith((".setter", ".deleter")) for d in getattr(node, "decorator_list", []))]


def nodes_in_function(node: ast.FunctionDef):
    def visit(item: ast.AST):
        yield item
        for child in ast.iter_child_nodes(item):
            if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                yield from visit(child)
    yield from visit(node)


@dataclass
class NativeSignature:
    name: str
    result: ast.AST | None = None
    configured: bool = False
    arguments: list[ast.AST] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Method:
    owner: str
    node: ast.FunctionDef
    arguments: dict[str, str]
    result: str
    native_calls: list[str]
    attributes: dict[str, str]

    @property
    def symbol(self) -> str:
        return f"{self.owner}.{self.node.name}" if self.owner else self.node.name


class NativeModel:
    def __init__(self, source: Path, metadata: Path):
        self.source = source
        self.tree = ast.parse(source.read_text(encoding="utf-8-sig"), filename=str(source))
        self.classes = {n.name: n for n in effective(self.tree.body) if isinstance(n, ast.ClassDef)}
        self.functions = {n.name: n for n in effective(self.tree.body) if isinstance(n, ast.FunctionDef)}
        self.signatures: dict[str, NativeSignature] = {}
        self.callbacks: dict[str, str] = {}
        self.diagnostics: list[dict[str, Any]] = []
        self._diagnostic_keys: set[tuple[str, str, str]] = set()
        self.methods: dict[str, Method] = {}
        self.stats: Counter[str] = Counter()
        self._read_metadata(json.loads(metadata.read_text(encoding="utf-8-sig")))
        self._read_ctypes()
        for node in self.tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and dotted(node.value.func) == "ctypes.CFUNCTYPE":
                args = node.value.args
                result = self.ctype(args[0]) if args else "Any"
                # c_void_p callback declarations are actual pointer returns, not void.
                params = ", ".join(self.ctype(a, pointer=True) for a in args[1:])
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self.callbacks[target.id] = f"Callable[[{params}], {result}]"

    def signature(self, name: str) -> NativeSignature:
        return self.signatures.setdefault(name, NativeSignature(name))

    def diagnostic(self, symbol: str, argument: str, reason: str, **extra: Any) -> None:
        key = (symbol, argument, reason)
        if key not in self._diagnostic_keys:
            self._diagnostic_keys.add(key)
            self.diagnostics.append({"symbol": symbol, "argument": argument, "reason": reason, **extra})

    def _read_metadata(self, data: Any) -> None:
        if isinstance(data, dict):
            if "name_c" in data:
                self.signature(data["name_c"]).metadata = data
                self.stats["metadata_methods"] += 1
                for param in data.get("parameters", []):
                    direction = param.get("in")
                    if direction in (True, "True", "true"):
                        self.stats["metadata_input_parameters"] += 1
                    elif direction in (False, "False", "false"):
                        self.stats["metadata_output_parameters"] += 1
            for value in data.values():
                self._read_metadata(value)
        elif isinstance(data, list):
            for value in data:
                self._read_metadata(value)

    def _read_ctypes(self) -> None:
        aliases: dict[str, str] = {}
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Assign):
                continue
            value_name = dotted(node.value)
            for target in node.targets:
                if isinstance(target, ast.Name) and value_name.startswith("ksapi.") and value_name.count(".") == 1:
                    aliases[target.id] = value_name.split(".")[1]
                if isinstance(target, ast.Attribute) and target.attr in {"restype", "argtypes"}:
                    owner = dotted(target.value)
                    name = owner[6:] if owner.startswith("ksapi.") else aliases.get(owner, owner)
                    sig = self.signature(name)
                    if target.attr == "restype":
                        sig.result, sig.configured = node.value, True
                    elif isinstance(node.value, (ast.List, ast.Tuple)):
                        sig.arguments = list(node.value.elts)

    def ctype(self, node: ast.AST | None, pointer: bool = False) -> str:
        if isinstance(node, ast.Constant) and node.value is None:
            return "None"
        name = dotted(node).removeprefix("ctypes.")
        if name in self.callbacks:
            return self.callbacks[name]
        if name in {"c_bool"}:
            return "bool"
        if name in {"c_float", "c_double", "c_longdouble"}:
            return "float"
        if name == "c_wchar_p" or name == "c_wchar":
            return "str"
        if name == "c_char_p" or name == "c_char":
            return "bytes"
        if name == "c_void_p":
            return "int | None"
        if re.fullmatch(r"c_(u?int\d*|u?long(long)?|u?short|u?byte|size_t|ssize_t)", name):
            return "int"
        if isinstance(node, ast.Call) and dotted(node.func) == "ctypes.POINTER" and node.args:
            if pointer:
                return f"ctypes._Pointer[{self.ctypes_class(node.args[0])}]"
            return self.ctype(node.args[0])
        return "Any"

    @staticmethod
    def ctypes_class(node: ast.AST) -> str:
        name = dotted(node)
        return name if name.startswith("ctypes.c_") else "ctypes.c_void_p"

    def cpp_type(self, spelling: str) -> str:
        text = re.sub(r"\bconst\b|\bvolatile\b", "", spelling).strip().rstrip(" &").strip()
        match = re.fullmatch(r"(?:std::)?vector\s*<(.+)>", text)
        if match:
            return f"list[{self.cpp_type(match.group(1))}]"
        if text in {"void"}:
            return "None"
        if text in {"std::wstring", "std::string", "wstring", "string", "wchar_t *", "const wchar_t *"}:
            return "str"
        if text in {"bool", "bool_t"}:
            return "bool"
        if text in {"double", "float", "long double"}:
            return "float"
        if re.fullmatch(r"(?:(?:unsigned|signed)\s+)?(?:char|short|int|long|long long)(?:\s+int)?|u?int\d+_t|size_t|COLORREF|Color|ObjectReference", text):
            return "int"
        if text in self.classes:
            return text
        if text.endswith("Ptr") and text[:-3] in self.classes:
            return text[:-3] + " | None"
        if text == "ISelfPtr":
            return "IAPIObject | None" if "IAPIObject" in self.classes else "Any"
        return "Any"

    def native_result(self, name: str, symbol: str) -> str:
        sig = self.signature(name)
        if not sig.configured:
            self.diagnostic(symbol, "return", "native restype is unconfigured; ctypes returns c_int", native=name)
            return "int"
        result = self.ctype(sig.result)
        cpp = self.cpp_type(sig.metadata.get("return_value", {}).get("type_cpp", ""))
        # SDK types identify interfaces/vectors, but only wrapper conversions turn
        # their integer handles into Python objects. Never leak C++ return shape.
        if cpp in {"str", "bool", "int", "float", "None"} and result != "Any":
            expected = "bytes" if cpp == "str" and dotted(sig.result) == "ctypes.c_char_p" else cpp
            if expected != result:
                spelling = sig.metadata.get("return_value", {}).get("type_cpp", "")
                pointer_scalar = dotted(sig.result) == "ctypes.c_void_p" and cpp == "int"
                category = "color_scalar_configured_as_pointer" if pointer_scalar and spelling == "Color" else "integer_scalar_configured_as_pointer" if pointer_scalar else "scalar_marshalling_mismatch"
                explanation = (
                    "The installed wrapper configures a C++ scalar as c_void_p: ctypes returns an integer address value, or None for zero; no Python conversion restores the SDK scalar."
                    if pointer_scalar else
                    "The installed ctypes restype, not the C++ declaration, determines the returned Python scalar."
                )
                self.diagnostic(symbol, "return", "SDK return type differs from configured Python ctypes result", native=name, sdk_type=cpp, sdk_spelling=spelling, ctypes_restype=dotted(sig.result), python_type=result, category=category, explanation=explanation)
        if result == "Any":
            self.diagnostic(symbol, "return", "unsupported ctypes restype", native=name, expression=dotted(sig.result))
        return result

    def vector_type(self, helper: str, call: ast.Call | None = None) -> str:
        stem = helper.removeprefix("From").removeprefix("To")
        if stem == "ObjectReferenceVector":
            element = dotted(call.args[2]) if call and len(call.args) > 2 else "IAPIObject"
            if element not in self.classes:
                element = "Any"
            return f"list[{element}]"
        if stem == "ObjectReferenceVectorVector":
            return "list[list[IAPIObject]]" if "IAPIObject" in self.classes else "list[list[Any]]"
        if stem.endswith("Vector2d"):
            return f"list[{self.vector_type('From' + stem[:-2])}]"
        if stem.endswith("VectorVector"):
            return f"list[{self.vector_type('From' + stem[:-6])}]"
        item = stem.removesuffix("Vector")
        if item in self.classes:
            return f"list[{item}]"
        if item in {"String", "Wstring"}:
            return "list[str]"
        if item == "Bool":
            return "list[bool]"
        if item in {"Double", "Float", "Date"}:
            return "list[float]"
        if item == "NumericId":
            return "list[int]"
        if re.fullmatch(r"U?int\d+|Int\d+|Uint\d+|Long|Ulong|Enum|Color", item):
            return "list[int]"
        return "Any"

    def analyze(self, owner: str, node: ast.FunctionDef) -> Method:
        symbol = f"{owner}.{node.name}" if owner else node.name
        args = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
        parameters = {a.arg: "Any" for a in args if a.arg not in {"self", "cls"}}
        env: dict[str, str] = {"self": owner, "cls": f"type[{owner}]"}
        attrs: dict[str, str] = {}
        calls: list[str] = []
        body_nodes = list(nodes_in_function(node))
        assignments = {target.id: item.value for item in body_nodes if isinstance(item, ast.Assign)
                       for target in item.targets if isinstance(target, ast.Name)}

        def propose(name: str, typ: str, *, authoritative: bool = False) -> None:
            if name not in parameters or typ == "Any":
                return
            old = parameters[name]
            generic_vectors = {"list[IAPIObject]", "list[IAPIObject | None]", "list[Any]", "list[list[IAPIObject]]", "list[list[Any]]"}
            if old == "Any" or authoritative or (old in generic_vectors and typ.startswith("list[")):
                parameters[name] = typ
            elif typ in generic_vectors and old.startswith("list["):
                return
            elif old != typ and old not in typ.split(" | "):
                # Conflicts are retained instead of silently losing evidence.
                self.diagnostic(symbol, name, "conflicting parameter evidence", previous=old, inferred=typ)
                parameters[name] = union(old, typ)

        def input_root(expr: ast.AST, typ: str) -> None:
            if isinstance(expr, ast.Name):
                if expr.id in parameters:
                    propose(expr.id, typ)
                elif expr.id in assignments:
                    input_root(assignments[expr.id], typ)
            elif isinstance(expr, ast.Call):
                helper = dotted(expr.func)
                if helper == "GetReference" and expr.args:
                    input_root(expr.args[0], typ if typ != "int" else "IAPIObject | None")
                elif helper.startswith("To") and "Vector" in helper and expr.args:
                    vec = typ if typ.startswith("list[") else self.vector_type(helper)
                    input_root(expr.args[-1], vec)
                elif helper in self.callbacks and expr.args:
                    input_root(expr.args[0], self.callbacks[helper])
                elif helper.startswith("ctypes.c_") and expr.args:
                    input_root(expr.args[0], self.ctype(expr.func))
                elif helper == "ctypes.byref" and expr.args:
                    input_root(expr.args[0], typ)
            elif isinstance(expr, ast.Attribute):
                if expr.attr == "reference":
                    input_root(expr.value, typ if typ in self.classes else "IAPIObject")
                elif expr.attr in {"ptr", "ptr_ptr"}:
                    input_root(expr.value, "str")
                elif expr.attr == "value":
                    input_root(expr.value, typ)

        # SDK parameter identities give precise interfaces/enums; follow actual marshal expressions.
        for item in body_nodes:
            if not isinstance(item, ast.Call):
                continue
            name = dotted(item.func)
            if name.startswith("ksapi."):
                native = name[6:]
                calls.append(native)
                sig = self.signature(native)
                meta_params = sig.metadata.get("parameters", [])
                offset = len(item.args) - len(meta_params)
                for index, expr in enumerate(item.args):
                    meta_index = index - offset
                    meta = meta_params[meta_index] if 0 <= meta_index < len(meta_params) else {}
                    typ = self.cpp_type(meta.get("type_cpp", ""))
                    if meta.get("name") == "self":
                        continue
                    if typ == "Any" and index < len(sig.arguments):
                        typ = self.ctype(sig.arguments[index])
                        if typ == "bytes" and isinstance(expr, ast.Call) and dotted(expr.func).endswith(".encode"):
                            typ = "str"
                    input_root(expr, typ)
            if name.endswith(".encode") and isinstance(item.func, ast.Attribute):
                input_root(item.func.value, "str")
            if name.startswith("ctypes.c_") and item.args:
                input_root(item.args[0], self.ctype(item.func))
            if name == "RefString" and item.args:
                input_root(item.args[0], "str")
            if name.startswith("To") and "Vector" in name and item.args:
                root = item.args[-1]
                if isinstance(root, ast.Name) and parameters.get(root.id, "Any") == "Any":
                    input_root(root, self.vector_type(name))
            if name in self.callbacks and item.args:
                input_root(item.args[0], self.callbacks[name])

        for arg in args:
            if arg.annotation and arg.arg in parameters:
                annotation = self.clean_annotation(arg.annotation)
                if annotation != "Any":
                    parameters[arg.arg] = annotation
        positional_args = [*node.args.posonlyargs, *node.args.args]
        defaults = list(zip(positional_args[-len(node.args.defaults):], node.args.defaults)) if node.args.defaults else []
        defaults += [(a, d) for a, d in zip(node.args.kwonlyargs, node.args.kw_defaults) if d is not None]
        for arg, default in defaults:
            if isinstance(default, ast.Constant):
                if default.value is None and parameters.get(arg.arg) != "Any":
                    parameters[arg.arg] = union(parameters[arg.arg], "None")
                elif default.value is not None:
                    propose(arg.arg, type(default.value).__name__)
        if owner and node.name == "__init__":
            if "kompasApp" in parameters and "IApplication" in self.classes and owner != "IApplication":
                parameters["kompasApp"] = "IApplication | None"
            for name in ("reference", "initObject"):
                if name in parameters and owner.startswith("I"):
                    parameters[name] = "int | IAPIObject" if "IAPIObject" in self.classes else "int"
            if owner in {"StorageValue", "PropertyValue", "AttributeValue"} and "initObject" in parameters:
                options = [owner, "None"]
                if owner == "AttributeValue":
                    options += ["PropertyValue", "list[PropertyValue]"]
                else:
                    options += ["int", "float", "bool", "str"]
                    if owner == "StorageValue":
                        options += ["list[int]", "list[float]", "list[bool]", "list[str]"]
                parameters["initObject"] = union(*options)
        if node.name == "CopyValue" and "other" in parameters:
            parameters["other"] = owner
        if node.name == "from_reference" and "reference" in parameters:
            parameters["reference"] = "int"
        if not owner and node.name.startswith(("From", "To")) and "Vector" in node.name:
            for name in parameters:
                if name == "kompasApp":
                    parameters[name] = "IApplication"
                elif name in {"vectorPtr", "data"}:
                    parameters[name] = "int"
                elif name == "li":
                    parameters[name] = self.vector_type(node.name)
                elif name == "wrapper_constructor":
                    parameters[name] = "Callable[[int, IApplication], IAPIObject | None]"
        if node.name == "__exit__":
            parameters.update({k: v for k, v in {"exc_type": "type[BaseException] | None", "exc_val": "BaseException | None", "exc_tb": "TracebackType | None"}.items() if k in parameters})
        if not owner and node.name == "GetReference" and "obj" in parameters:
            parameters["obj"] = "IAPIObject | IApplication | None"
        if not owner and node.name in {"SetKompasPath", "_initialize"}:
            parameters = {k: "str" for k in parameters}
        env.update(parameters)
        returns: list[str] = []

        def infer(expr: ast.AST | None) -> str:
            if expr is None:
                return "None"
            if isinstance(expr, ast.Constant):
                return "None" if expr.value is None else type(expr.value).__name__
            if isinstance(expr, ast.Name):
                return env.get(expr.id, expr.id if expr.id in self.classes else "Any")
            if isinstance(expr, (ast.Tuple, ast.List)):
                members = [infer(e) for e in expr.elts]
                return f"tuple[{', '.join(members)}]" if isinstance(expr, ast.Tuple) else f"list[{union(*members)}]"
            if isinstance(expr, ast.IfExp):
                return union(infer(expr.body), infer(expr.orelse))
            if isinstance(expr, (ast.Compare, ast.BoolOp)):
                return "bool" if isinstance(expr, ast.Compare) else union(*(infer(v) for v in expr.values))
            if isinstance(expr, ast.UnaryOp):
                return "bool" if isinstance(expr.op, ast.Not) else infer(expr.operand)
            if isinstance(expr, ast.BinOp):
                return union(infer(expr.left), infer(expr.right))
            if isinstance(expr, ast.Subscript):
                value = infer(expr.value)
                return value[5:-1] if value.startswith("list[") else "Any"
            if isinstance(expr, ast.Attribute):
                text = dotted(expr)
                if text in attrs:
                    return attrs[text]
                if expr.attr == "value":
                    if isinstance(expr.value, ast.Name) and expr.value.id in assignments:
                        assignment = assignments[expr.value.id]
                        if isinstance(assignment, ast.Call) and dotted(assignment.func).startswith("ctypes.c_"):
                            return self.ctype(assignment.func)
                    if infer(expr.value) == "RefString":
                        return "str"
                    return infer(expr.value)
                if expr.attr == "reference":
                    return "int"
                if expr.attr == "kompasApp":
                    return "int" if owner == "IApplication" and isinstance(expr.value, ast.Name) and expr.value.id == "self" else "IApplication"
                if text.startswith("constants."):
                    return "int"
                return "Any"
            if isinstance(expr, ast.Call):
                name = dotted(expr.func)
                if name.startswith("ksapi."):
                    return self.native_result(name[6:], symbol)
                if name in self.classes:
                    return name
                if name in {"bool", "str", "int", "float", "bytes"}:
                    return name
                if name == "len":
                    return "int"
                if name == "Finalize":
                    return "Finalize"
                if name == "set" and owner == "IApplication":
                    return "set[WeakRef[IAPIObject]]" if "IAPIObject" in self.classes else "set[object]"
                if name.startswith("From") and "Vector" in name:
                    return self.vector_type(name, expr)
                if name.startswith("To") and "Vector" in name:
                    return "int"
                if name == "GetReference":
                    return "int"
                if name.startswith("ctypes.c_"):
                    return self.ctype(expr.func)
                if name in {"ctypes.wstring_at"}:
                    return "str"
                if name == "ctypes.string_at":
                    return "bytes"
                if name == "ctypes.cast" and len(expr.args) > 1:
                    return dotted(expr.args[1])
                if name == "ctypes.byref":
                    return "Any"
                if name.endswith(".encode"):
                    return "bytes"
                if name.endswith(".from_reference"):
                    return name.split(".")[0]
                if name == "cls.__new__":
                    return owner
                if isinstance(expr.func, ast.Attribute):
                    target = infer(expr.func.value).split(" | ")[0]
                    other = self.methods.get(f"{target}.{expr.func.attr}")
                    if other:
                        return other.result
                    if target == "int" and expr.func.attr == "QueryInterface" and owner == "IAPIObject":
                        # Constructor input is an interface-or-handle union; this call
                        # occurs only on the interface branch and returns an integer handle.
                        return "int"
                return "Any"
            return "Any"

        def walk(statements: list[ast.stmt]) -> None:
            for item in statements:
                if isinstance(item, (ast.Assign, ast.AnnAssign)):
                    value = infer(item.value)
                    targets = item.targets if isinstance(item, ast.Assign) else [item.target]
                    for target in targets:
                        if isinstance(target, ast.Name):
                            env[target.id] = value
                        elif isinstance(target, ast.Attribute) and dotted(target).startswith("self."):
                            attrs[dotted(target)] = value
                elif isinstance(item, ast.Return):
                    returns.append(infer(item.value))
                elif isinstance(item, ast.If):
                    before = env.copy()
                    walk(item.body)
                    left = env.copy()
                    env.clear()
                    env.update(before)
                    walk(item.orelse)
                    for key, val in left.items():
                        env[key] = union(val, env.get(key, val))
                elif isinstance(item, (ast.For, ast.While, ast.With, ast.Try)):
                    walk(item.body)
                    if hasattr(item, "orelse"):
                        walk(item.orelse)
        walk(node.body)
        result = union(*returns) if returns else "None"
        if node.name == "__init__":
            result = "None"
        if node.name == "from_reference":
            result = owner
        if not owner and node.name.startswith("From") and "Vector" in node.name:
            result = self.vector_type(node.name)
        if owner == "RefString":
            if node.name == "ptr":
                result = "ctypes.c_wchar_p | None"
            elif node.name == "ptr_ptr":
                # byref returns an opaque CArgObject, not a typed _Pointer.
                result = "Any"
        if node.returns:
            declared = self.clean_annotation(node.returns)
            if declared != "Any" and "T" not in declared:
                result = declared
        for name, typ in parameters.items():
            if "Any" in typ:
                self.diagnostic(symbol, name, "no precise input type from SDK, ctypes or Python marshalling")
        if "Any" in result:
            self.diagnostic(symbol, "return", "unresolved Python return expression", expressions=[dotted(n.value) for n in body_nodes if isinstance(n, ast.Return)])
        for name, typ in attrs.items():
            if "Any" in typ:
                self.diagnostic(symbol, name, "unresolved instance attribute from Python assignment")
        method = Method(owner, node, parameters, result, list(dict.fromkeys(calls)), attrs)
        storage_key = symbol
        if any(dotted(d).endswith((".setter", ".deleter")) for d in node.decorator_list):
            storage_key += "@" + dotted(node.decorator_list[0]).rsplit(".", 1)[-1]
        self.methods[storage_key] = method
        return method

    def clean_annotation(self, node: ast.AST) -> str:
        text = dotted(node)
        text = re.sub(r"\bList\b", "list", text)
        text = re.sub(r"\bOptional\[(\w+)\]", r"\1 | None", text)
        allowed = set(self.classes) | {"Any", "Callable", "None", "str", "int", "float", "bool", "bytes", "list", "tuple", "type", "BaseException", "TracebackType"}
        names = {n.id for n in ast.walk(ast.parse(text, mode="eval")) if isinstance(n, ast.Name)}
        return text if names <= allowed else "Any"

    def analyze_all(self) -> None:
        for owner, cls in self.classes.items():
            for node in effective(cls.body):
                if isinstance(node, ast.FunctionDef):
                    self.analyze(owner, node)
        for name, node in self.functions.items():
            self.analyze("", node)
