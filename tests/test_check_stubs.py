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

from check_stubs import (CONTROL_TYPES, DEFAULT_MYPY, check_controls, check_documentation,
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
            methods = {f"{c.name}.{m.name}": m for c in tree.body if isinstance(c, ast.ClassDef)
                       for m in c.body if isinstance(m, ast.FunctionDef)}
            pages = []
            for symbol in CONTROL_TYPES:
                if "." not in symbol:
                    continue
                source = "ksapi_" + symbol.lower().replace(".", "_") + ".html"
                content = f"Native text for {symbol}"
                pages.append({"section": "API интерфейсов. KsAPI", "source_html": source, "content": content})
                pages.append({"section": "API интерфейсов. Версия 7", "source_html": "api7_" + source, "content": "WRONG API7"})
                methods[symbol].body.insert(0, ast.Expr(value=ast.Constant(value=f"{content}\nLocal documentation: [link](local.md)\nNative documentation: {source}")))
            docs.write_text("\n".join(json.dumps(p) for p in pages), encoding="utf-8")
            errors = []
            self.assertEqual(check_documentation(tree, docs, errors), 5)
            self.assertEqual(errors, [])
            methods["ISketch.BeginEdit"].body[0].value.value = "WRONG API7\nNative documentation: api7_isketch_beginedit.html"
            check_documentation(tree, docs, errors)
            self.assertIn("docs_mismatch", [e["code"] for e in errors])
            self.assertEqual(errors[0]["symbol"], "ISketch.BeginEdit")


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
