"""Offline mutation fixtures for the independent verifier (no generator imports)."""
from __future__ import annotations

import skill_paths

import ast
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from check_stubs import (CONTROL_TYPES, DEFAULT_MYPY, check_controls, check_documentation, check_enum_aliases,
                         compare_surface, file_fingerprint, native_review, run_mypy,
                         validate_type_names, verify)

SOURCE = '''
raise RuntimeError("must never be imported")
class Base:
    pass
class Example(Base):
    VALUE = 42
    NAME = "native"
    def __init__(self): pass
    def __init__(self, required, default=None): pass
    def Method(self, first, /, second=42, *items, flag=True, **options): pass
    def __bool__(self): return True
    def _internal(self): pass
    @staticmethod
    def Factory(value="native"): pass
def Public(value=None): pass
def _initialize(): pass
'''
STUB = '''
from typing import Any, Literal
class Base: ...
class Example(Base):
    VALUE: Literal[42] = 42
    NAME: Literal["native"] = "native"
    def __init__(self, required: Any, default: Any = None) -> None: ...
    def Method(self, first: int, /, second: int = 42, *items: Any, flag: bool = True, **options: Any) -> int: ...
    def __bool__(self) -> bool: ...
    def _internal(self) -> None: ...
    @staticmethod
    def Factory(value: str = "native") -> str: ...
def Public(value: Any = None) -> None: ...
def _initialize() -> None: ...
'''
CONTROL_STUB = '''
class IApplication:
    def __init__(self, kompasApp: int) -> None: ...
    def GetReference(self) -> int: ...
    def GetDocuments(self) -> IDocuments | None: ...
class IDocuments: ...
class IFragmentDocument: ...
class ILoop: ...
class ISketch:
    def BeginEdit(self, readOnly: bool) -> IFragmentDocument | None: ...
    def GetPoint3D(self, xIn: float, yIn: float, xOut: float, yOut: float, zOut: float) -> tuple[bool, float, float, float]: ...
class IFace:
    def GetLoops(self) -> list[ILoop]: ...
class IExtrusion:
    def SetProfiles(self, profiles: list[ILoop | None]) -> None: ...
def GetKompas() -> IApplication | None: ...
'''


class SurfaceTests(unittest.TestCase):
    def compare(self, stub=STUB, source=SOURCE):
        errors, warnings = [], []
        counts = compare_surface(ast.parse(source), ast.parse(stub), "fixture", errors, warnings)
        return errors, warnings, counts

    def test_exact_surface_last_constructor_wins(self):
        errors, warnings, counts = self.compare()
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])
        self.assertEqual(counts["effective_duplicate_definitions"], 1)
        self.assertEqual(counts["source_functions_methods"], 7)

    def test_detect_missing_public_method_and_dunder(self):
        for line in ("    def __bool__(self) -> bool: ...\n", "def Public(value: Any = None) -> None: ...\n"):
            with self.subTest(line=line):
                self.assertIn("method_missing", [e["code"] for e in self.compare(STUB.replace(line, ""))[0]])

    def test_missing_internal_is_inventoried_not_hidden(self):
        errors, warnings, counts = self.compare(STUB.replace("def _initialize() -> None: ...\n", ""))
        self.assertEqual(errors, [])
        self.assertEqual(warnings[0]["symbols"], ["_initialize"])
        self.assertEqual(counts["internal_functions_excluded"], 1)

    def test_detect_wrong_default(self):
        for before, after in (("second: int = 42", "second: int = 43"), ("flag: bool = True", "flag: bool = 1"),
                              ("default: Any = None", "default: Any = ...")):
            with self.subTest(after=after):
                self.assertIn("signature", [e["code"] for e in self.compare(STUB.replace(before, after))[0]])

    def test_detect_argument_kinds_order_decorators(self):
        for before, after in (("first: int, /, second", "first: int, second"),
                              ("@staticmethod", "@classmethod"),
                              ("first: int, /, second: int = 42", "second: int, /, first: int = 42")):
            with self.subTest(after=after):
                errors = self.compare(STUB.replace(before, after))[0]
                self.assertTrue(any(e["code"] in {"signature", "decorators"} for e in errors))

    def test_detect_class_bases_and_constants(self):
        for before, after, code in (("class Example(Base)", "class Example", "class_bases"),
                                    ("VALUE: Literal[42] = 42", "VALUE: Literal[43] = 43", "constant_value"),
                                    ('    NAME: Literal["native"] = "native"\n', "", "constant_missing")):
            with self.subTest(code=code):
                self.assertIn(code, [e["code"] for e in self.compare(STUB.replace(before, after))[0]])

    def test_callback_factory_assignment_is_not_invented_function(self):
        source = "import ctypes\nHandler = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_int32)\n"
        stub = "import ctypes\nfrom typing import Callable\ndef Handler(callback: Callable[[int], bool]) -> ctypes._CFuncPtr: ...\n"
        errors, _, counts = self.compare(stub, source)
        self.assertEqual(errors, [])
        self.assertEqual(counts["callback_factories"], 1)
        errors = self.compare(stub.replace("[[int], bool]", "[[str], bool]"), source)[0]
        self.assertIn("callback_type", [e["code"] for e in errors])

    def test_no_fake_constructor_overload(self):
        bad = STUB.replace("required: Any, default: Any = None", "")
        self.assertIn("signature", [e["code"] for e in self.compare(bad)[0]])


class TypeTests(unittest.TestCase):
    def check(self, text):
        errors = []
        validate_type_names(ast.parse(text), "fixture", errors)
        return errors

    def test_resolves_aliases_forward_refs_builtins(self):
        self.assertEqual(self.check('''from typing import Any as Dynamic, Literal, Annotated
import ctypes as ct
class Later: ...
def read(value: "Later | None", other: Dynamic, code: Literal["not_a_type"]) -> list[ct.c_int]: ...
answer: Annotated[int, "metadata"]
'''), [])

    def test_detects_unresolved_and_forward_reference(self):
        for annotation in ("Missing", '"Missing | None"', "list[Missing]", "ghost.Type"):
            with self.subTest(annotation=annotation):
                errors = self.check(f"def read() -> {annotation}: ...")
                self.assertIn("undefined_type", [e["code"] for e in errors])

    def test_typevar_scopes(self):
        valid = '''from typing import Generic, TypeVar
T = TypeVar("T")
def identity(value: T) -> T: ...
class Box(Generic[T]):
    value: T
    def read(self) -> T: ...
'''
        self.assertEqual(self.check(valid), [])
        for extra in ("\nvalue: T\n", "\ndef unbound() -> T: ...\n", "\nclass NotGeneric:\n    value: T\n"):
            with self.subTest(extra=extra):
                self.assertIn("unbound_typevar", [e["code"] for e in self.check(valid + extra)])

    def test_aliased_typevar_factory_scope(self):
        errors = self.check('from typing import TypeVar as TV\nT = TV("T")\nvalue: T\n')
        self.assertIn("unbound_typevar", [e["code"] for e in errors])

    def test_control_goldens(self):
        errors = []
        self.assertEqual(check_controls(ast.parse(CONTROL_STUB), errors), 12)
        self.assertEqual(errors, [])

    def test_detect_wrong_type(self):
        for old, new in (("readOnly: bool", "readOnly: int"), ("list[ILoop]", "list[int]"),
                         ("tuple[bool, float, float, float]", "tuple[float, float, float, bool]"),
                         ("-> None", "-> int"), ("IApplication | None", "IApplication")):
            with self.subTest(new=new):
                errors = []
                check_controls(ast.parse(CONTROL_STUB.replace(old, new)), errors)
                self.assertIn("control_type", [e["code"] for e in errors])

    def test_output_arguments_must_be_required(self):
        errors = []
        check_controls(ast.parse(CONTROL_STUB.replace("zOut: float", "zOut: float = 0.0")), errors)
        self.assertIn("control_required_outputs", [e["code"] for e in errors])


class DocumentationTests(unittest.TestCase):
    def test_native_pages_attached_to_exact_method(self):
        with tempfile.TemporaryDirectory() as directory:
            docs = Path(directory) / "pages.jsonl"
            tree = ast.parse(CONTROL_STUB)
            classes = {c.name: c for c in tree.body if isinstance(c, ast.ClassDef)}
            methods = {f"{c.name}.{m.name}": m for c in classes.values()
                       for m in c.body if isinstance(m, ast.FunctionDef)}
            for cls in classes.values():
                cls.body.insert(0, ast.Expr(value=ast.Constant(value=f"Источники SDK:\n- [{cls.name}]({cls.name}.md)")))
            pages = []
            for symbol in CONTROL_TYPES:
                if "." not in symbol:
                    continue
                source = "ksapi_" + symbol.lower().replace(".", "_") + ".html"
                content = f"Native text for {symbol}"
                if symbol == "ISketch.GetPoint3D":
                    content = "Входные параметры:\n\n| xIn | input coordinate |\n\nВозвращаемое значение:\n\nSuccess status."
                pages.append({"section": "API интерфейсов. KsAPI", "source_html": source, "content": content,
                              "markdown_path": f"llm/{symbol.split('.')[0]}.md"})
                pages.append({"section": "API интерфейсов. Версия 7", "source_html": "api7_" + source, "content": "WRONG API7"})
                methods[symbol].body.insert(0, ast.Expr(value=ast.Constant(value=content)))
            docs.write_text("\n".join(json.dumps(p) for p in pages), encoding="utf-8")
            errors = []
            self.assertEqual(check_documentation(tree, docs, errors), 5)
            self.assertEqual(errors, [])
            methods["ISketch.BeginEdit"].body[0].value.value = "WRONG API7\nИсточник SDK: [api7_isketch_beginedit.html](wrong.md)"
            check_documentation(tree, docs, errors)
            self.assertIn("docs_mismatch", [e["code"] for e in errors])
            self.assertEqual(errors[0]["symbol"], "ISketch.BeginEdit")


class EnumVerificationTests(unittest.TestCase):
    def test_independent_enum_values_mapping_and_input_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            docs, metadata = root / "pages.jsonl", root / "metadata.json"
            docs.write_text(json.dumps({"section": "Константы API", "title": "KindEnum - Тип",
                                        "content": "| FIRST | 0 | Первый |\n| SECOND | 1 | Второй |"}))
            metadata.write_text(json.dumps({"name_c": "Client_Set", "parameters": [
                {"name": "self", "type_cpp": "ISelfPtr", "in": True},
                {"name": "value", "type_cpp": "KindEnum", "in": True}]}))
            constants = '''from typing import Literal, TypeAlias
KindEnum: TypeAlias = Literal[0, 1]
"""Тип
0 — FIRST: Первый
1 — SECOND: Второй
"""
'''
            source = "class Client:\n    def Set(self, value): ksapi.Client_Set(self.app, self.reference, value)"
            stub = "from constants import KindEnum\nclass Client:\n    def Set(self, value: KindEnum) -> None: ..."
            def check(constant_text=constants, stub_text=stub):
                errors = []
                trees = {"constants": (ast.parse("FIRST = 0\nSECOND = FIRST | 1"), ast.parse(constant_text)),
                         "ksapi": (ast.parse(source), ast.parse(stub_text))}
                counts = check_enum_aliases(trees, docs, metadata, errors)
                return counts, errors
            counts, errors = check()
            self.assertEqual(errors, [])
            self.assertEqual(counts, {"aliases": 1, "input_parameters": 1, "inline_input_parameters": 0})
            self.assertIn("enum_values", [e["code"] for e in check(constants.replace("Literal[0, 1]", "Literal[0, 2]"))[1]])
            self.assertIn("enum_mapping", [e["code"] for e in check(constants.replace("1 — SECOND", "1 — WRONG"))[1]])
            original_docs = docs.read_text()
            for content, code in [
                ("| FIRST | 0 | First |\n| SECOND | | Missing |", "enum_table"),
                ("| FIRST | 0 | First |\n| SECOND | 2 | Drift |", "enum_installed_values"),
                ("| FIRST | 0 | First |\n| SECOND | 1 | 8 | Composite |", "enum_table"),
            ]:
                docs.write_text(json.dumps({"section": "Константы API", "title": "KindEnum - Kind", "content": content}))
                self.assertIn(code, [e["code"] for e in check()[1]])
            docs.write_text(original_docs + "\n" + json.dumps({"content": "Комбинация [KindEnum](<webhelp:kind.html>)"}))
            self.assertIn("enum_domain", [e["code"] for e in check()[1]])
            docs.write_text(original_docs)
            metadata.write_text(metadata.read_text().replace("KindEnum", "int32_t"))
            self.assertIn("enum_binding", [e["code"] for e in check()[1]])


class InlineEnumVerificationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.docs, self.metadata = root / "pages.jsonl", root / "metadata.json"
        self.page = {"section": "Константы API", "title": "KindEnum - Тип",
                     "content": "| FIRST | 0 | Первый |\n| SECOND | 1 | Второй |"}
        self.cpp = {"name_c": "Client_Set", "parameters": [
            {"name": "self", "type_cpp": "ISelfPtr", "in": True},
            {"name": "value", "type_cpp": "KindEnum", "in": True}]}
        self.source = "class Client:\n    def Set(self, value): ksapi.Client_Set(self.app, self.reference, value)"
        self.stub = '''from typing import Literal
class Client:
    def Set(self, value: Literal[0, 1]) -> None:
        """Допустимые значения value (KindEnum):
        0 — FIRST: Первый
        1 — SECOND: Второй
        """
        ...
'''
        self.installed = "FIRST = 0\nSECOND = FIRST | 1"

    def check(self, *, stub=None, source=None, pages=None, cpp=None, installed=None, constants=""):
        self.docs.write_text("\n".join(json.dumps(page) for page in (pages if pages is not None else [self.page])), encoding="utf-8")
        self.metadata.write_text(json.dumps(cpp if cpp is not None else self.cpp), encoding="utf-8")
        trees = {"constants": (ast.parse(installed if installed is not None else self.installed), ast.parse(constants)),
                 "ksapi": (ast.parse(source if source is not None else self.source), ast.parse(stub if stub is not None else self.stub))}
        errors = []
        counts = check_enum_aliases(trees, self.docs, self.metadata, errors)
        return counts, errors

    def test_inline_without_alias_uses_exact_cpp_identity(self):
        counts, errors = self.check()
        self.assertEqual(errors, [])
        self.assertEqual(counts, {"aliases": 0, "input_parameters": 1, "inline_input_parameters": 1})

    def test_inline_same_enum_in_two_parameters_of_one_method(self):
        source = self.source.replace("self, value)", "self, value, other)").replace("self.reference, value)", "self.reference, value, other)")
        stub = self.stub.replace("value: Literal[0, 1]", "value: Literal[0, 1], other: Literal[0, 1]")
        stub = stub.replace('        """\n', "\n        Допустимые значения other (KindEnum):\n        0 — FIRST: Первый\n        1 — SECOND: Второй\n        \"\"\"\n")
        cpp = {**self.cpp, "parameters": [*self.cpp["parameters"], {"name": "other", "type_cpp": "KindEnum", "in": True}]}
        counts, errors = self.check(source=source, stub=stub, cpp=cpp)
        self.assertEqual(errors, [])
        self.assertEqual(counts, {"aliases": 0, "input_parameters": 2, "inline_input_parameters": 2})

    def test_inline_mapping_normalizes_sdk_links_and_escaped_pipes(self):
        page = {**self.page, "content": "| FIRST | 0 | [Первый](<webhelp:first.html>) |\n| SECOND | 1 | Open\\|Save |"}
        counts, errors = self.check(pages=[page], stub=self.stub.replace("Второй", "Open|Save"))
        self.assertEqual(errors, [])
        self.assertEqual(counts["inline_input_parameters"], 1)

    def test_inline_rejects_missing_extra_wrong_and_bool_values(self):
        for value in ("Literal[0]", "Literal[0, 1, 2]", "Literal[0, 2]", "Literal[False, 1]"):
            with self.subTest(value=value):
                errors = self.check(stub=self.stub.replace("Literal[0, 1]", value))[1]
                self.assertIn("enum_values", [e["code"] for e in errors])

    def test_inline_rejects_missing_or_wrong_parameter_mapping(self):
        for before, after in (("Допустимые значения value (KindEnum):", ""),
                              ("значения value", "значения other"), ("(KindEnum)", "(OtherEnum)"),
                              ("1 — SECOND: Второй", ""), ("1 — SECOND", "2 — SECOND"),
                              ("SECOND: Второй", "SECOND: Wrong"), ("1 — SECOND", "1 — WRONG"),
                              ("SECOND: Второй", "SECOND: Второй wrong"),
                              ("SECOND: Второй", "SECOND: Второй\n        2 — EXTRA: Wrong")):
            with self.subTest(after=after):
                errors = self.check(stub=self.stub.replace(before, after))[1]
                self.assertIn("enum_mapping", [e["code"] for e in errors])

    def test_inline_rejects_unsafe_tables_and_installed_drift(self):
        for content, code in (("| FIRST | 0 | Первый |\n| SECOND | | Missing |", "enum_table"),
                              ("| FIRST | 0 | Первый |\n| SECOND | 1 | 8 | Composite |", "enum_table"),
                              ("| FIRST | 0 | Первый |\n| SECOND | 2 | Второй |", "enum_installed_values"),
                              ("| FIRST | 0 | Первый |\n| SECOND | 1 | Флаг |", "enum_domain")):
            with self.subTest(content=content):
                errors = self.check(pages=[{**self.page, "content": content}])[1]
                self.assertIn(code, [e["code"] for e in errors])
        errors = self.check(installed="FIRST = 0")[1]
        self.assertIn("enum_installed_values", [e["code"] for e in errors])

    def test_inline_rejects_linked_open_usage_domain(self):
        errors = self.check(pages=[self.page, {"content": "Комбинация [KindEnum](<webhelp:kind.html>)"}])[1]
        self.assertIn("enum_domain", [e["code"] for e in errors])

    def test_inline_rejects_ambiguous_table_identity(self):
        errors = self.check(pages=[self.page, self.page])[1]
        self.assertIn("enum_identity", [e["code"] for e in errors])

    def test_inline_rejects_cpp_mismatch_output_and_missing_metadata(self):
        for parameter in ({"type_cpp": "int32_t", "in": True},
                          {"type_cpp": "OtherEnum", "in": True},
                          {"type_cpp": "KindEnum", "in": False}):
            with self.subTest(parameter=parameter):
                cpp = {**self.cpp, "parameters": [self.cpp["parameters"][0], parameter]}
                errors = self.check(cpp=cpp)[1]
                self.assertIn("enum_binding", [e["code"] for e in errors])
        self.assertIn("enum_binding", [e["code"] for e in self.check(cpp={})[1]])

    def test_inline_identity_is_not_inferred_from_values_or_mapping(self):
        # A different enum with identical values must use ITS metadata identity.
        other = {**self.page, "title": "OtherEnum - Другой тип"}
        cpp = {**self.cpp, "parameters": [self.cpp["parameters"][0], {"type_cpp": "OtherEnum", "in": True}]}
        errors = self.check(pages=[self.page, other], cpp=cpp)[1]
        self.assertIn("enum_mapping", [e["code"] for e in errors])

    def test_inline_rejects_reassigned_transformed_or_conflicting_inputs(self):
        for source in (self.source.replace("ksapi.Client_Set", "value = 1; ksapi.Client_Set"),
                       self.source.replace("self.reference, value)", "self.reference, int(value))"),
                       self.source + "; ksapi.Other(value)"):
            with self.subTest(source=source):
                self.assertIn("enum_binding", [e["code"] for e in self.check(source=source)[1]])

    def test_shared_alias_and_inline_counts_include_both_kinds(self):
        constants = '''from typing import Literal, TypeAlias
SharedEnum: TypeAlias = Literal[0, 1]
"""0 — FIRST: Первый
1 — SECOND: Второй"""
'''
        source = self.source + "\n    def Read(self, value): ksapi.Client_Read(self.app, self.reference, value)\n    def Write(self, value): ksapi.Client_Read(self.app, self.reference, value)"
        stub = self.stub + "    def Read(self, value: SharedEnum) -> None: ...\n    def Write(self, value: SharedEnum) -> None: ..."
        stub = "from constants import SharedEnum\n" + stub
        shared_cpp = {"name_c": "Client_Read", "parameters": [self.cpp["parameters"][0], {"type_cpp": "SharedEnum", "in": True}]}
        counts, errors = self.check(source=source, stub=stub, constants=constants,
                                    pages=[self.page, {**self.page, "title": "SharedEnum - Общий тип"}], cpp=[self.cpp, shared_cpp])
        self.assertEqual(errors, [])
        self.assertEqual(counts, {"aliases": 1, "input_parameters": 3, "inline_input_parameters": 1})


class PortabilityAndFreshnessTests(unittest.TestCase):
    def test_missing_mypy_is_explicit_not_silently_skipped(self):
        errors = []
        with patch("check_stubs.shutil.which", return_value=None) as which:
            result = run_mypy(Path("unused"), "mypy", errors, [])
        which.assert_called_once_with("mypy")
        self.assertFalse(result["available"])
        self.assertEqual(errors[0]["code"], "mypy_missing")
        self.assertIn("--mypy", errors[0]["detail"])

    def test_explicit_mypy_override_is_resolved_before_changing_cwd(self):
        errors = []
        with patch("check_stubs.shutil.which", return_value=None) as which:
            run_mypy(Path("unused"), Path("tools/custom-mypy"), errors, [])
        which.assert_called_once_with("tools/custom-mypy")

    def test_fingerprint_uses_exact_bytes_and_missing_file_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.py"
            self.assertEqual(file_fingerprint(path), {"path": str(path), "exists": False})
            value = b"# exact CRLF bytes\r\n"
            path.write_bytes(value)
            fingerprint = file_fingerprint(path)
            self.assertEqual(fingerprint["sha256"], hashlib.sha256(value).hexdigest())
            self.assertEqual(fingerprint["bytes"], len(value))

    def test_review_classifies_cpp_abi_wrapper_conflicts_without_runtime_claims(self):
        with tempfile.TemporaryDirectory() as directory:
            metadata = Path(directory) / "metadata.json"
            metadata.write_text(json.dumps({"methods": [{"name_c": "IExtrusion_SetProfiles", "return_value": {"type_cpp": "void"}, "parameters": []}]}), encoding="utf-8")
            source = ast.parse("class IExtrusion:\n    def SetProfiles(self, profiles):\n        ksapi.IExtrusion_SetProfiles(profiles)\n")
            stub = ast.parse("class IExtrusion:\n    def SetProfiles(self, profiles: list[int]) -> None: ...\n")
            review = native_review(source, stub, metadata)[0]
            self.assertIn("native_result_discarded_python_returns_none", review["reconciliation"]["classifications"])
            self.assertIn("cpp_void_but_ctypes_restype_unconfigured_defaults_to_int", review["reconciliation"]["classifications"])
            self.assertFalse(review["reconciliation"]["runtime_validated"])


class IntegrationTests(unittest.TestCase):
    def test_installed_mypy_positive_and_each_negative_client(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ksapi.pyi").write_text(CONTROL_STUB, encoding="utf-8")
            errors = []
            result = run_mypy(root, DEFAULT_MYPY, errors, [])
            self.assertEqual(errors, [], result)
            self.assertEqual(result["full"]["exit_code"], 0)
            self.assertEqual(result["positive"]["exit_code"], 0)
            self.assertEqual(len(result["negative"]), 7)
            self.assertTrue(all(r["rejected_at_client"] for r in result["negative"].values()))

    def test_mypy_enum_clients_cover_alias_and_inline_document_type(self):
        for annotation in ("DocumentTypeEnum", "Literal[1, 2, 3, 4, 5, 6, 7]"):
            with self.subTest(annotation=annotation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                constants = '''from typing import Literal, TypeAlias
DocumentTypeEnum: TypeAlias = Literal[1, 2, 3, 4, 5, 6, 7]
class constants:
    ksDocumentPart: Literal[4] = 4
'''
                if annotation.startswith("Literal"):
                    constants = constants.replace("DocumentTypeEnum: TypeAlias = Literal[1, 2, 3, 4, 5, 6, 7]\n", "")
                (root / "constants.pyi").write_text(constants, encoding="utf-8")
                imports = "from constants import DocumentTypeEnum\n" if annotation == "DocumentTypeEnum" else "from typing import Literal\n"
                stub = CONTROL_STUB.replace("class IDocuments: ...", f"class IDocuments:\n    def Add(self, documentType: {annotation}, visible: bool) -> None: ...")
                (root / "ksapi.pyi").write_text(imports + stub, encoding="utf-8")
                errors = []
                result = run_mypy(root, DEFAULT_MYPY, errors, [])
                self.assertEqual(errors, [], result)
                self.assertEqual(set(result["enum_clients"]), {"named_constant", "numeric_literal", "invalid_value"})
                self.assertEqual(result["enum_clients"]["named_constant"]["exit_code"], 0)
                self.assertEqual(result["enum_clients"]["numeric_literal"]["exit_code"], 0)
                self.assertEqual(result["enum_clients"]["invalid_value"]["exit_code"], 1)

    def test_wrapper_is_parsed_not_imported_and_all_files_inventoried(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Bin").mkdir()
            output = root / "out"
            output.mkdir()
            (root / "Bin/custom.py").write_text(SOURCE, encoding="utf-8")
            (output / "custom.pyi").write_text(STUB, encoding="utf-8")
            report = verify(root, output, root / "missing_docs", root / "missing_metadata", mypy=None)
            self.assertTrue(report["ok"], report["errors"])
            hashes = report["fingerprints"]
            self.assertTrue(hashes["stable_during_verification"])
            self.assertEqual(hashes["inputs"]["wrappers"]["custom.py"]["sha256"], hashlib.sha256(SOURCE.encode()).hexdigest())
            self.assertEqual(hashes["outputs"]["custom.pyi"]["sha256"], hashlib.sha256(STUB.encode()).hexdigest())
            self.assertFalse(hashes["inputs"]["documentation"]["exists"])
            self.assertIn("not an exhaustive manual review", " ".join(report["limitations"]))

            def mutate(*args):
                (output / "custom.pyi").write_text(STUB + "\n# changed during mypy\n", encoding="utf-8")
                return {"available": True}

            with patch("check_stubs.run_mypy", side_effect=mutate):
                changed = verify(root, output, root / "missing_docs", root / "missing_metadata", mypy="mypy")
            self.assertFalse(changed["ok"])
            self.assertIn("artifacts_changed", changed["error_counts"])
            self.assertFalse(changed["fingerprints"]["stable_during_verification"])
            self.assertNotEqual(changed["fingerprints"]["outputs"], changed["fingerprints"]["after"]["outputs"])
            (root / "Bin/other.py").write_text("", encoding="utf-8")
            report = verify(root, output, root / "missing_docs", root / "missing_metadata", mypy=None)
            self.assertFalse(report["ok"])
            self.assertIn("stub_missing", report["error_counts"])


if __name__ == "__main__":
    unittest.main()
