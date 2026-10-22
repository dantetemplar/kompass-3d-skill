"""Render AST-derived native stubs and attach native SDK documentation.

When a native KsAPI page omits semantic sections, matching COM/Automation prose
(return meaning, notes, description) is merged — never COM/Automation syntax.
"""
from __future__ import annotations

import ast
import hashlib
import io
import json
import os
import re
import tokenize
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from native import Method, NativeModel, dotted, effective, nodes_in_function

NATIVE_SECTION = "API интерфейсов. KsAPI"
CONSTANTS_SECTION = "Константы API"
# Prose-only COM sections safe to borrow when the native page is silent.
# Never take parameter tables: COM names/signatures disagree with ksapi.
COM_FALLBACK_CANONICAL = (
    "Возвращаемое значение:",
    "Примечание:",
    "Описание:",
    "Значение свойства:",
)
_COM_HEADING_ALIASES = {
    "возвращаемое значение": "Возвращаемое значение:",
    "возвращаемое значения": "Возвращаемое значение:",
    "возвращается": "Возвращаемое значение:",
    "примечание": "Примечание:",
    "примечания": "Примечание:",
    "описание": "Описание:",
    "значение свойства": "Значение свойства:",
}


def constant_rows(content: str):
    """Read named integer values and descriptions from SDK constant tables."""
    for line in content.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", line.strip())[1:-1]]
        if len(cells) < 3:
            continue
        # WebHelp may split OR operands across cells; the first is not a value.
        if any(re.fullmatch(r"[+-]?(?:0[xX][0-9a-fA-F]+|\d+)", cell.strip("` ")) for cell in cells[2:-1]):
            continue
        name = cells[0].strip("` ")
        value = cells[1].strip("` ").replace("−", "-")
        if not re.fullmatch(r"[A-Za-z_]\w*", name) or not re.fullmatch(r"[+-]?(?:0[xX][0-9a-fA-F]+|\d+)", value):
            continue
        description = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", cells[2])
        description = description.replace(r"\|", "|").strip()
        if description:
            yield name, int(value, 16 if "x" in value.lower() else 10), description


def integer_expression(node: ast.AST | None, known: dict[str, int]) -> int | None:
    """Evaluate only integer constants and installed constant expressions; never eval."""
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return node.value
    if isinstance(node, ast.Name):
        return known.get(node.id)
    if isinstance(node, ast.UnaryOp):
        value = integer_expression(node.operand, known)
        if value is not None:
            if isinstance(node.op, ast.USub):
                return -value
            if isinstance(node.op, ast.UAdd):
                return value
            if isinstance(node.op, ast.Invert):
                return ~value
    if isinstance(node, ast.BinOp):
        left, right = integer_expression(node.left, known), integer_expression(node.right, known)
        if left is None or right is None:
            return None
        operations = {ast.BitOr: int.__or__, ast.BitAnd: int.__and__, ast.BitXor: int.__xor__,
                      ast.Add: int.__add__, ast.Sub: int.__sub__, ast.Mult: int.__mul__}
        operation = operations.get(type(node.op))
        if operation:
            return operation(left, right)
        if isinstance(node.op, (ast.LShift, ast.RShift)) and 0 <= right <= 64:
            return left << right if isinstance(node.op, ast.LShift) else left >> right
    return None


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
        self.com_pages: list[dict[str, Any]] = []
        self.com_index: dict[str, list[int]] = defaultdict(list)
        self.stats: Counter[str] = Counter()
        self.matches: dict[str, dict[str, Any]] = {}
        self.constant_matches: dict[str, dict[str, Any]] = {}
        self.constants: dict[tuple[str, int], dict[str, dict[str, Any]]] = defaultdict(dict)
        self.enum_pages: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.enums: dict[str, dict[str, Any]] = {}
        self.enum_bindings: list[dict[str, str]] = []
        self.enum_rejections: dict[str, str] = {}
        self.enum_usage: dict[str, list[str]] = defaultdict(list)
        self.unmatched: list[str] = []
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            page = json.loads(line)
            content = str(page.get("content", ""))
            for enum_name in set(re.findall(r"\[([A-Za-z_]\w*)\]\(<webhelp:", content)):
                self.enum_usage[enum_name].append(content)
            section = page.get("section")
            if section == CONSTANTS_SECTION:
                rows = list(constant_rows(str(page.get("content", ""))))
                title = re.match(r"^([A-Za-z_]\w*)\s*(?:[-—–]|$)", str(page.get("title", "")))
                if title:
                    self.enum_pages[title.group(1)].append(page)
                for name, value, description in rows:
                    self.constants[name, value].setdefault(description, page)
            if section != NATIVE_SECTION:
                self.stats["excluded_non_native_pages"] += 1
                if section != CONSTANTS_SECTION:
                    self._index_com_page(page)
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

    def _index_com_page(self, page: dict[str, Any]) -> None:
        """Index COM/Automation pages for prose fallback; never for type binding."""
        source = str(page.get("source_html", ""))
        filename = Path(urlparse(source).path).name.lower()
        if filename.startswith("ksapi_"):
            return
        identities = [str(page.get("symbol") or ""), str(page.get("title") or ""), str(page.get("key") or "")]
        title_path = page.get("title_path") or []
        if isinstance(title_path, list):
            owners = [str(p) for p in title_path if re.fullmatch(r"I[A-Za-z0-9_]+", str(p))]
            if owners and identities[1]:
                identities.append(owners[-1] + "." + identities[1])
        stem = filename.removesuffix(".html").removesuffix(".htm")
        if stem:
            identities.append(stem)
        index = len(self.com_pages)
        self.com_pages.append(page)
        for identity in identities:
            key = self.normalize(identity)
            if key and index not in self.com_index[key]:
                self.com_index[key].append(index)

    def prepare_enums(self, model: NativeModel) -> None:
        """Build documented aliases; narrow only explicit, directly forwarded inputs."""
        if self.enums:
            return
        inventories: dict[str, dict[str, int]] = {}
        reserved = set(model.classes) | set(model.functions) | set(model.callbacks)
        for module in ("constants", "constants3d"):
            tree = ast.parse((model.source.parent / (module + ".py")).read_text(encoding="utf-8-sig"))
            inventory = {}
            for node in ast.walk(tree):
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    integer = integer_expression(node.value, inventory)
                    if integer is not None:
                        inventory.update({target.id: integer for target in targets if isinstance(target, ast.Name)})
            inventories[module] = inventory
            reserved.update(inventory)
        for name, pages in sorted(self.enum_pages.items()):
            if len(pages) != 1 or name in reserved:
                continue
            page = pages[0]
            rows = list(constant_rows(page["content"]))
            by_name: dict[str, set[tuple[int, str]]] = defaultdict(set)
            for member, value, description in rows:
                by_name[member].add((value, description))
            if any(len(values) != 1 for values in by_name.values()):
                self.enum_rejections[name] = "conflicting SDK member rows"
                continue
            named_rows = [line for line in page["content"].splitlines()
                          if re.match(r"^\|\s*`?[A-Za-z_]\w*`?\s*\|", line)
                          and not re.match(r"^\|\s*(?:Column\b|Name\b)", line)]
            anonymous_values = any(re.match(r"^\|\s*\|\s*[+-]?(?:0[xX][0-9a-fA-F]+|\d+)\s*\|", line)
                                   for line in page["content"].splitlines())
            multi_column = any(len(re.split(r"(?<!\\)\|", line.strip())[1:-1]) != 3 for line in named_rows)
            if len(named_rows) != len(rows) or anonymous_values or multi_column:
                self.enum_rejections[name] = "incomplete or multi-column SDK value table"
                continue
            scores = {module: sum(inventory.get(member) == value for member, value, _ in rows)
                      for module, inventory in inventories.items()}
            if not rows or not max(scores.values()):
                self.enum_rejections[name] = "no matching installed constants"
                continue
            module = max(scores, key=scores.get)
            if any(inventories[module].get(member) != value for member, value, _ in rows):
                self.enum_rejections[name] = "SDK members disagree with installed constants"
                continue
            values = sorted({value for _, value, _ in rows})
            # Named bitsets and sparse power-of-two domains are not closed choices.
            evidence = page["title"] + "\n" + page["content"] + "\n" + "\n".join(self.enum_usage[name])
            flags = bool(re.search(r"flag|mask|флаг|маск|побитов|битов|комбинац|сочетан|логическ.{0,25}(?:или|or)", evidence, re.I))
            positive = [value for value in values if value > 0]
            flags |= len(positive) >= 3 and all(value & (value - 1) == 0 for value in positive)
            open_domain = bool(re.search(r"произвольн|пользовательск.{0,35}(?:значени|тип|код)|и\s+выше|и\s+более", evidence, re.I))
            closed = not (flags or open_domain)
            self.enums[name] = {"module": module, "page": page, "rows": rows,
                                "values": values, "closed": closed}
        for method in model.methods.values():
            reassigned = {node.id for node in nodes_in_function(method.node)
                          if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)}
            for node in nodes_in_function(method.node):
                if not isinstance(node, ast.Call) or not dotted(node.func).startswith("ksapi."):
                    continue
                native = dotted(node.func)[6:]
                parameters = model.signature(native).metadata.get("parameters", [])
                offset = len(node.args) - len(parameters)
                if offset < 0:
                    continue
                for parameter, argument in zip(parameters, node.args[offset:]):
                    enum = str(parameter.get("type_cpp", ""))
                    if (enum not in self.enums or not self.enums[enum]["closed"]
                            or parameter.get("in") not in (True, "True", "true")
                            or not isinstance(argument, ast.Name) or argument.id in reassigned
                            or method.arguments.get(argument.id) != "int"):
                        continue
                    # All direct native uses must agree on this argument's domain.
                    uses = [(model.signature(dotted(call.func)[6:]).metadata.get("parameters", []), call.args)
                            for call in nodes_in_function(method.node)
                            if isinstance(call, ast.Call) and dotted(call.func).startswith("ksapi.")]
                    domains = [param.get("type_cpp") for params, args in uses
                               for param, arg in zip(params, args[len(args) - len(params):])
                               if isinstance(arg, ast.Name) and arg.id == argument.id]
                    if set(domains) != {enum}:
                        continue
                    method.arguments[argument.id] = enum
                    self.enum_bindings.append({"symbol": method.symbol, "parameter": argument.id,
                                               "enum": enum, "native": native})
        methods_by_enum: dict[str, set[str]] = defaultdict(set)
        for binding in self.enum_bindings:
            methods_by_enum[binding["enum"]].add(binding["symbol"])
        for name, enum in self.enums.items():
            enum["inline"] = len(methods_by_enum[name]) == 1
        for binding in self.enum_bindings:
            enum = self.enums[binding["enum"]]
            if enum["inline"]:
                model.methods[binding["symbol"]].arguments[binding["parameter"]] = (
                    "Literal[" + ", ".join(map(str, enum["values"])) + "]")
        self.stats["enum_aliases"] = sum(not enum["inline"] for enum in self.enums.values())
        self.stats["enum_closed_aliases"] = sum(enum["closed"] and not enum["inline"] for enum in self.enums.values())
        self.stats["enum_inline_domains"] = sum(enum["inline"] for enum in self.enums.values())
        self.stats["enum_input_parameters"] = len(self.enum_bindings)

    def constant_text(self, symbol: str, value: ast.AST | None, comment: str) -> str:
        integer = None
        if isinstance(value, ast.Constant) and type(value.value) is int:
            integer = value.value
        elif (isinstance(value, ast.UnaryOp) and isinstance(value.op, (ast.USub, ast.UAdd))
              and isinstance(value.operand, ast.Constant) and type(value.operand.value) is int):
            integer = -value.operand.value if isinstance(value.op, ast.USub) else value.operand.value
        candidates = self.constants.get((symbol.rsplit(".", 1)[-1], integer), {})
        if len(candidates) == 1:
            description, page = next(iter(candidates.items()))
            self.constant_matches[symbol] = page
            self.stats["constants_from_sdk"] += 1
            return description
        if len(candidates) > 1:
            self.stats["ambiguous_constant_docs"] += 1
        if comment:
            self.stats["constants_from_wrapper_comments"] += 1
        else:
            self.stats["constants_without_docs"] += 1
        return comment

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

    def find_com(self, symbol: str) -> dict[str, Any] | None:
        """Resolve a unique COM/Automation page for semantic fallback."""
        matches = self.com_index.get(self.normalize(symbol), [])
        expected = symbol.replace(".", "_").casefold()
        filenames = [
            i for i in matches
            if Path(urlparse(str(self.com_pages[i].get("source_html", ""))).path).stem.casefold() == expected
        ]
        if len(filenames) == 1:
            matches = filenames
        if len(matches) != 1:
            return None
        return self.com_pages[matches[0]]

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
            title = str(page.get("title") or symbol)
            # The signature already identifies the member; keep its description.
            title = re.sub(r"^" + re.escape(symbol.rsplit(".", 1)[-1]) + r"\s+[-—–]\s+", "", title)
            parts.append(title)
            com = self.find_com(symbol)
            if com is None and page.get("symbol") and page.get("symbol") != symbol:
                com = self.find_com(str(page["symbol"]))
            content, borrowed = merge_com_fallback(
                str(page.get("content", "")),
                str(com.get("content", "")) if com else None,
            )
            if borrowed:
                self.stats["com_fallback_symbols"] += 1
                self.stats["com_fallback_sections"] += len(borrowed)
            if content and content != title:
                parts.append(content)
        if method:
            for binding in self.enum_bindings:
                enum = self.enums[binding["enum"]]
                if binding["symbol"] == method.symbol and enum["inline"]:
                    mapping = "\n".join(f"{value} — {member}: {meaning}" for member, value, meaning in enum["rows"])
                    parts.append(f"Допустимые значения {binding['parameter']} ({binding['enum']}):\n" + mapping)
            notes = python_argument_documentation(method, model)
            if notes:
                parts.append(notes)
            for diagnostic in model.diagnostics:
                if diagnostic["symbol"] == method.symbol and diagnostic.get("category"):
                    parts.append("Marshalling discrepancy: " + diagnostic["explanation"] + f" SDK: {diagnostic.get('sdk_spelling')}; ctypes: {diagnostic.get('ctypes_restype')}; Python: {diagnostic.get('python_type')}.")
        return "\n\n".join(parts)

    def class_sources(self, owner: str, output: Path, *, constants: bool = False) -> str:
        """Attribute used Markdown documents once per class, not once per page."""
        documents: dict[Path, str] = {}
        matches = self.constant_matches if constants else self.matches
        for symbol, page in matches.items():
            if symbol != owner and not symbol.startswith(owner + "."):
                continue
            path = self.markdown_path(page)
            page_owner = "Константы API" if constants else str(page.get("symbol") or owner).split(".")[0]
            documents.setdefault(path, page_owner)
        if not constants:
            for binding in self.enum_bindings:
                if binding["symbol"].startswith(owner + ".") and self.enums[binding["enum"]]["inline"]:
                    documents.setdefault(self.markdown_path(self.enums[binding["enum"]]["page"]), "Константы API")
        if not documents:
            return ""
        links = [f"- [{label}]({os.path.relpath(path, output.parent)})"
                 for path, label in sorted(documents.items(), key=lambda item: str(item[0]))]
        return "Источники SDK:\n" + "\n".join(links)


def _normalize_doc_heading(line: str) -> str | None:
    """Map a lone heading line to a canonical SDK section name, if known."""
    stripped = re.sub(r"\s+:", ":", line.strip())
    if not stripped.endswith(":"):
        return None
    key = stripped[:-1].strip().casefold()
    return _COM_HEADING_ALIASES.get(key)


def documentation_sections(content: str) -> dict[str, str]:
    """Split page body into canonical section name → body (raw, unfiltered)."""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    fence: str | None = None
    for line in content.splitlines():
        stripped = line.strip()
        marker = re.match(r"^(`{3,}|~{3,})", stripped)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            if current is not None:
                sections.setdefault(current, []).append(line)
            continue
        if fence is None:
            canonical = _normalize_doc_heading(stripped)
            if canonical is not None:
                current = canonical
                sections.setdefault(current, [])
                continue
            # Any other lone Title: heading ends the current fallback section.
            if current is not None and re.fullmatch(r"[\w][\w ()/.-]*:", stripped):
                current = None
                continue
        if current is not None:
            sections.setdefault(current, []).append(line)
    return {name: "\n".join(body).strip() for name, body in sections.items() if "\n".join(body).strip()}


def merge_com_fallback(native_content: str, com_content: str | None) -> tuple[str, list[str]]:
    """Append missing semantic sections from COM prose; return (text, borrowed headings)."""
    native = semantic_documentation(native_content)
    if not com_content:
        return native, []
    present = documentation_sections(native_content)
    borrowed: list[str] = []
    extras: list[str] = []
    com_sections = documentation_sections(com_content)
    for heading in COM_FALLBACK_CANONICAL:
        if present.get(heading):
            continue
        body = com_sections.get(heading, "").strip()
        if not body:
            continue
        extras.append(f"{heading}\n\n{body}")
        borrowed.append(heading)
    if not extras:
        return native, []
    merged = native + ("\n\n" if native else "") + "\n\n".join(extras)
    return merged.strip(), borrowed


def semantic_documentation(content: str) -> str:
    """Keep SDK explanations verbatim, excluding signature and WebHelp navigation.

    Full C++ declarations, hierarchy and navigation remain in the linked SDK
    page. Unknown headings, code examples, tables and notes are not discarded.
    """
    headings = {"Синтаксис KsAPI:", "Иерархия:", "Подразделы:",
                "Входные параметры:", "Возвращаемое значение:", "Примечание:",
                "Определенные типы:", "Описание:", "Значение свойства:"}
    navigation = {"Синтаксис KsAPI:", "Иерархия:", "Подразделы:"}
    lines: list[str] = []
    skipping = False
    fence: str | None = None
    for line in content.splitlines():
        stripped = line.strip()
        marker = re.match(r"^(`{3,}|~{3,})", stripped)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            if not skipping:
                lines.append(line)
            continue
        if fence is None:
            if stripped in headings:
                skipping = stripped in navigation
            elif skipping and re.fullmatch(r"[\w][\w ()/-]*:", stripped):
                skipping = False
            if re.fullmatch(r"\[Интерфейс\.{3}\]\(<[^>]+>\)", stripped):
                continue
        if not skipping:
            lines.append(line)
    return "\n".join(lines).strip()


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
                    add(expr, "initial value for an SDK output parameter; the caller must supply it")
        elif name == "GetReference" and node.args:
            add(node.args[0], "None is passed as native handle 0 (not necessarily valid for this operation)")
        elif name == "RefString" and node.args:
            add(node.args[0], "initial text for a native string buffer")
        elif name == "ToObjectReferenceVector" and node.args:
            helper = model.functions.get(name)
            if helper is not None:
                skips_none = any(isinstance(test, ast.Compare) and any(isinstance(op, (ast.NotEq, ast.IsNot)) for op in test.ops) and any(isinstance(value, ast.Constant) and value.value is None for value in test.comparators) for test in ast.walk(helper))
                if skips_none:
                    add(node.args[-1], "None elements are skipped, not passed as null handles")
        elif name.endswith(".encode") and isinstance(node.func, ast.Attribute):
            encoding = dotted(node.args[0]) if node.args else "the default encoding"
            add(node.func.value, f"encoded to bytes with {encoding} before the native call")

    # Group identical conversion notes; types/defaults already live in the stub
    # signature. Ordinary scalar arguments and return locals add no information.
    grouped: dict[str, list[str]] = {}
    for name, details in notes.items():
        for detail in details:
            grouped.setdefault(detail, []).append(name)
    lines = [f"- {', '.join(names)}: {detail}." for detail, names in grouped.items()]
    tuples = [node.value for node in nodes if isinstance(node, ast.Return) and isinstance(node.value, ast.Tuple)]
    layouts: list[str] = []
    for value in tuples:
        labels = []
        for index, item in enumerate(value.elts):
            origins = roots(item)
            if len(origins) == 1:
                labels.append(next(iter(origins)))
            elif index == 0 and method.result.startswith("tuple[bool,"):
                labels.append("status")
            else:
                labels.append(dotted(item))
        layout = "Returns: (" + ", ".join(labels) + ")."
        if layout not in layouts:
            layouts.append(layout)
    if layouts:
        lines.extend(layouts)
    return "Python binding:\n" + "\n".join(lines) if lines else ""


def doc_literal(text: str, indent: str) -> list[str]:
    if not text:
        return []
    if "\n" not in text:
        return [indent + json.dumps(text, ensure_ascii=False)]
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


def emit_constants(source: Path, docs: Documentation, output: Path) -> str:
    source_text = source.read_text(encoding="utf-8-sig")
    tree = ast.parse(source_text, filename=str(source))
    comments = {token.start[0]: token.string.removeprefix("#").strip()
                for token in tokenize.generate_tokens(io.StringIO(source_text).readline)
                if token.type == tokenize.COMMENT}

    def documented(node, owner, rendered):
        result = []
        for declaration in rendered:
            result.append(declaration)
            name = declaration.strip().split(":", 1)[0]
            description = docs.constant_text(owner + "." + name, node.value, comments.get(node.end_lineno, ""))
            if description:
                indent = declaration[:len(declaration) - len(declaration.lstrip())]
                result.append(indent + json.dumps(description, ensure_ascii=False))
        return result

    enums = {name: enum for name, enum in docs.enums.items()
             if enum["module"] == source.stem and not enum["inline"]}
    for name, enum in enums.items():
        docs.constant_matches[source.stem + ".constants." + name] = enum["page"]
    lines = ["# Generated from installed native Python and SDK documentation; do not edit.", "from typing import Any, Literal, TypeAlias", ""]
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
                    members.extend(documented(item, source.stem + "." + node.name, rendered))
                    scalar_integer = isinstance(item.value, ast.Constant) and type(item.value.value) in {int, bool}
                    signed_integer = isinstance(item.value, ast.UnaryOp) and isinstance(item.value.operand, ast.Constant) and type(item.value.operand.value) is int
                    if rendered and (": int = " in rendered[0] or scalar_integer or signed_integer):
                        targets = item.targets if isinstance(item, ast.Assign) else [item.target]
                        known_integers.update(target.id for target in targets if isinstance(target, ast.Name))
            sources = docs.class_sources(source.stem + "." + node.name, output, constants=True)
            lines.extend(doc_literal(sources, "    "))
            lines.extend(members or ["    ..."])
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            lines.extend(documented(node, source.stem, constant_assignment(node)))
    for name, enum in enums.items():
        target = "Literal[" + ", ".join(map(str, enum["values"])) + "]" if enum["closed"] else "int"
        ordered = sorted(enum["rows"], key=lambda row: (row[1], row[0]))
        first, last = ordered[0][0], ordered[-1][0]
        span = f"{source.stem}.constants.{first}" + (f" … {last}" if first != last else "")
        lines.extend(["", f"# {span}", f"{name}: TypeAlias = {target}"])
        description = re.sub(r"^" + re.escape(name) + r"\s*[-—–]\s*", "", enum["page"]["title"])
        mapping = [f"{value} — {member}: {meaning}" for member, value, meaning in enum["rows"]]
        lines.extend(doc_literal(description + "\n\n" + "\n".join(mapping), ""))
    text = "\n".join(lines) + "\n"
    ast.parse(text)
    return text


def emit_native(model: NativeModel, docs: Documentation, output: Path) -> str:
    model.analyze_all()
    docs.prepare_enums(model)
    lines = ["# Generated offline from installed native wrappers and structured SDK metadata.",
             "from __future__ import annotations", "import ctypes", "from _ctypes import CFuncPtr", "import os", "import pathlib",
             "from typing import Any, Callable, Literal, TypeAlias, TypeVar", "from types import TracebackType",
             "from weakref import ref as WeakRef, finalize as Finalize", "from constants import constants as constants", ""]
    used_enums = {binding["enum"] for binding in docs.enum_bindings if not docs.enums[binding["enum"]]["inline"]}
    for module in ("constants", "constants3d"):
        names = sorted(name for name in used_enums if docs.enums[name]["module"] == module)
        if names:
            lines.append("from " + module + " import " + ", ".join(names))
    known = set(model.classes) | set(model.functions) | set(model.callbacks) | used_enums | {"constants", "ctypes", "os", "pathlib", "True", "False", "None"}
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
            class_text = docs.text(item.name, model, output)
            method_texts = {key: docs.text(method.symbol, model, output, method)
                            for key, method in model.methods.items() if method.owner == item.name}
            sources = docs.class_sources(item.name, output)
            lines.extend(doc_literal("\n\n".join(part for part in (class_text, sources) if part), "    "))
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
                    text = method_texts[method_key]
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
