"""Offline stub excerpts and ty check tests; no native modules are imported."""
from __future__ import annotations

import ast
import io
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import skill_paths
from sdk import StubDocs, main, qualified_symbol

SKILL_DIR = skill_paths.SKILL_DIR
SCRIPT = skill_paths.SCRIPTS_DIR / "sdk.py"
TY = shutil.which("ty")

STUB = '''from typing import overload
from constants3d import Mode as Mode
raise RuntimeError("STUB MUST NOT BE EXECUTED")
class IBase:
    def Update(self) -> bool:
        "Обновить"
        ...
class IText(IBase):
    """Интерфейс IText

    Источники SDK:
    - [IText](../kompas-sdk-docs/IText.md)
    """
    _myId: str = 'id'
    def __init__(self, reference: int) -> None: ...
    def Replace(self, old: str, new: str) -> bool: ...
    @overload
    def Assign(self, other: IText | None) -> bool:
        """Скопировать текст

        Python binding:
        - other: None is passed as native handle 0.
        """
        ...
    @overload
    def Assign(self, other: str) -> bool: ...
    def AddTable(self) -> None: ...
    def Edit(self) -> bool: ...
    def Find(self) -> str: ...
    def Clear(self) -> None: ...
    @property
    def Count(self) -> int: ...
    class Nested:
        def Run(self) -> bool: ...
def GetKompas(
    name: str = "🛠",
) -> IText:
    "Получить приложение"
    ...
Alias: str = 'value'
"Документация атрибута"
'''


class StubFixture:

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="typing api тест ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stubs = self.root / "stubs"
        self.stubs.mkdir()
        (self.stubs / "ksapi.pyi").write_text(STUB, encoding="utf-8")
        for module in ("constants", "constants3d"):
            (self.stubs / f"{module}.pyi").write_text('''from typing import Literal, TypeAlias
Mode: TypeAlias = Literal[0, 1]
class constants:
    "Константы"
    o3d_planeXOY: Literal[1] = 1
    "плоскость XOY"
''', encoding="utf-8")
        self.docs = StubDocs(self.stubs)

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), "--stubs", str(self.stubs), *args],
                              cwd=self.root, capture_output=True, text=True, timeout=40, check=False)


class StubDocTests(StubFixture, unittest.TestCase):
    def test_symbol_validation_and_modules(self):
        self.assertEqual(qualified_symbol("IText.Assign"), "ksapi.IText.Assign")
        self.assertEqual(qualified_symbol("ksapi.GetKompas"), "ksapi.GetKompas")
        self.assertEqual(qualified_symbol("constants3d.constants.o3d_planeXOY"),
                         "constants3d.constants.o3d_planeXOY")
        for value in ("", "a..b", "x()", "x; import os", "class", ".x"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                qualified_symbol(value)

    def test_method_context_exact_docstring_overloads_and_neighbor_counts(self):
        result = self.docs.doc("IText.Assign")
        self.assertIn("class IText(IBase):", result)
        self.assertIn("[IText](../kompas-sdk-docs/IText.md)", result)
        self.assertIn("# 2 methods above: Replace, __init__", result)
        self.assertIn("# 5 methods below: AddTable, Edit, Find, ...", result)
        self.assertIn("    @overload\n    def Assign(self, other: IText | None) -> bool:", result)
        self.assertIn("- other: None is passed as native handle 0.", result)
        self.assertIn("def Assign(self, other: str) -> bool: ...", result)
        self.assertNotIn("def Replace", result)
        self.assertNotIn("def AddTable", result)
        self.assertNotIn("_myId", result)
        ast.parse(result)

    def test_python_source_links_point_to_method_class_function_and_constant(self):
        source = '''raise RuntimeError("DO NOT IMPORT")
class IBase:
    def Update(self): return True
class IText(IBase):
    def Assign(self, other): return True
def GetKompas(): return IText()
'''
        (self.root / "ksapi.py").write_text(source, encoding="utf-8")
        (self.root / "constants3d.py").write_text(
            "class constants:\n    o3d_planeXOY = 1\n", encoding="utf-8",
        )
        docs = StubDocs(self.stubs, self.root)
        for symbol, module, line in (("IText.Assign", "ksapi", 5), ("IText", "ksapi", 4),
                                     ("GetKompas", "ksapi", 6), ("IText.Update", "ksapi", 3),
                                     ("constants3d.constants.o3d_planeXOY", "constants3d", 2)):
            with self.subTest(symbol=symbol):
                self.assertIn(f"# Python binding: {self.root / (module + '.py')}:{line}\n", docs.doc(symbol))
        with patch("sdk.ast.parse", wraps=ast.parse) as parse:
            docs.doc("IText.Assign")
            self.assertEqual(parse.call_count, 0)

    def test_missing_source_does_not_invent_a_line_or_hide_stub_docs(self):
        docs = StubDocs(self.stubs, self.root)
        self.assertIn(f"# Python binding: {self.root / 'ksapi.py'} — file not found", docs.doc("IText.Assign"))
        (self.root / "ksapi.py").write_text("class IText: ...\n", encoding="utf-8")
        result = docs.doc("IText.Assign")
        self.assertIn("declaration not found: IText.Assign", result)
        self.assertIn("Скопировать текст", result)

    def test_class_lists_compact_signatures_without_method_docs(self):
        result = self.docs.doc("IText")
        self.assertIn("class IText(IBase):", result)
        self.assertIn("Интерфейс IText", result)
        self.assertIn("def Assign(self, other: IText | None) -> bool: ...", result)
        self.assertIn("def AddTable(self) -> None: ...", result)
        self.assertIn("@property\n    def Count(self) -> int: ...", result)
        self.assertNotIn("Скопировать текст", result)
        ast.parse(result)

    def test_function_preserves_multiline_signature_and_docstring(self):
        result = self.docs.doc("ksapi.GetKompas")
        self.assertIn('def GetKompas(\n    name: str = "🛠",\n) -> IText:', result)
        self.assertIn("Получить приложение", result)
        ast.parse(result)

    def test_constants_attributes_reexports_and_type_aliases(self):
        for symbol, text in (("constants3d.constants.o3d_planeXOY", '"плоскость XOY"'),
                             ("Alias", '"Документация атрибута"'),
                             ("Mode", "Mode: TypeAlias = Literal[0, 1]"),
                             ("constants.constants.o3d_planeXOY", "Literal[1] = 1")):
            with self.subTest(symbol=symbol):
                result = self.docs.doc(symbol)
                self.assertIn(text, result)
                ast.parse(result)

    def test_inherited_method_reports_actual_owner_and_source(self):
        result = self.docs.doc("IText.Update")
        self.assertIn("# IText.Update —", result)
        self.assertIn("class IBase:", result)
        self.assertIn("def Update(self) -> bool:", result)
        self.assertNotIn("class IText", result)

    def test_nested_class_context(self):
        result = self.docs.doc("IText.Nested.Run")
        self.assertIn("class IText(IBase):", result)
        self.assertIn("    class Nested:\n\n        def Run(self) -> bool: ...", result)
        ast.parse(result)

    def test_batch_parses_module_once_without_ty_or_processes(self):
        with patch("sdk.ast.parse", wraps=ast.parse) as parse, \
                patch("sdk.shutil.which", side_effect=AssertionError("ty lookup forbidden")), \
                patch("sdk.subprocess.run", side_effect=AssertionError("process launch forbidden")), \
                redirect_stdout(io.StringIO()) as output:
            code = main(["--stubs", str(self.stubs), "--bin", str(self.root), "doc", "IText.Assign", "GetKompas"])
        self.assertEqual(code, 0)
        self.assertEqual(parse.call_count, 1)
        self.assertIn("Скопировать текст", output.getvalue())
        self.assertIn("Получить приложение", output.getvalue())

    def test_unknown_and_invalid_symbols_do_not_hide_other_results(self):
        result = self.run_cli("doc", "IText.Assign", "IText.NoSuchMethod", "IText()", "GetKompas")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Скопировать текст", result.stdout)
        self.assertIn("Получить приложение", result.stdout)
        self.assertIn("Symbol not found in stubs", result.stderr)
        self.assertIn("Expected a dotted Python symbol", result.stderr)

    def test_missing_stubs_explains_preparation(self):
        with redirect_stderr(io.StringIO()) as err:
            self.assertEqual(main(["--stubs", str(self.root), "doc", "IText.Assign"]), 2)
        self.assertIn("prepare_stubs.py", err.getvalue())

    def test_doc_only_requires_queried_modules(self):
        (self.stubs / "constants.pyi").unlink()
        result = self.run_cli("doc", "IText.Assign")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_cyclic_inheritance_does_not_recurse_forever(self):
        (self.stubs / "ksapi.pyi").write_text("class A(B): ...\nclass B(A): ...\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Symbol not found"):
            self.docs.doc("A.Missing")

    def test_hover_command_removed(self):
        result = self.run_cli("--help")
        self.assertNotIn("hover", result.stdout)
        self.assertEqual(self.run_cli("hover", "macro.py", "1:1").returncode, 2)

    def test_copied_skill_uses_its_own_stubs(self):
        copied = self.root / "copied skill"
        (copied / "scripts").mkdir(parents=True)
        shutil.copy2(SCRIPT, copied / "scripts/sdk.py")
        shutil.copytree(self.stubs, copied / ".cache/kompas-stubs")
        result = subprocess.run(
            [sys.executable, str(copied / "scripts/sdk.py"), "doc", "IText.Assign"],
            cwd=self.root, capture_output=True, text=True, timeout=40, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Скопировать текст", result.stdout)
        self.assertNotIn(str(SKILL_DIR), result.stdout)
        self.assertIn(str(copied), result.stdout)

    @unittest.skipUnless((SKILL_DIR / ".cache/kompas-stubs/ksapi.pyi").is_file(), "Prepared native stubs required")
    def test_real_native_stubs(self):
        command = [sys.executable, str(SCRIPT), "doc", "IText.Assign", "ISketch.GetPoint3D",
                   "IExtrusion.SetSideParameters", "constants3d.constants.o3d_planeXOY"]
        result = subprocess.run(command, cwd=self.root, capture_output=True, text=True, timeout=40, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("class IText(IKompasAPIObject):", result.stdout)
        self.assertIn("def Assign(self, other: IText | None) -> bool:", result.stdout)
        self.assertIn("Скопировать текст", result.stdout)
        self.assertIn("Returns: (status, xOut, yOut, zOut).", result.stdout)
        self.assertIn("extrusionType: ksEndTypeEnum", result.stdout)
        self.assertIn("плоскость XOY", result.stdout)
        ast.parse(result.stdout)


@unittest.skipUnless(TY, "Run with uv run --with ty==0.0.90 python -m unittest discover -s tests")
class TyIntegrationTests(StubFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        # Keep the check fixture independent of intentional AST-only declarations.
        (self.stubs / "ksapi.pyi").write_text('''class IText:
    def Assign(self, other: str) -> bool: ...
''', encoding="utf-8")
        self.macro = self.root / "external project" / "макрос.py"
        self.macro.parent.mkdir()
        self.macro.write_text('''# /// script
# requires-python = ">=3.11"
# dependencies = ["must-not-be-installed-by-this-tool"]
# ///
import ksapi
def build(text: ksapi.IText):
    text.Assign('value')
raise RuntimeError("THIS FILE MUST NOT BE EXECUTED")
''', encoding="utf-8")

    def test_check_valid_and_invalid_macro_without_execution(self):
        good = self.run_cli("check", str(self.macro))
        self.assertEqual(good.returncode, 0, good.stderr + good.stdout)
        self.assertNotIn("THIS FILE MUST NOT BE EXECUTED", good.stderr)
        self.macro.write_text("import ksapi\ndef build(s: ksapi.IText):\n    s.Assign(123)\n", encoding="utf-8")
        bad = self.run_cli("check", str(self.macro))
        self.assertEqual(bad.returncode, 1, bad.stderr + bad.stdout)
        self.assertIn("invalid-argument-type", bad.stdout + bad.stderr)

    def test_explicit_project(self):
        result = self.run_cli("--project", str(self.macro.parent), "check", str(self.macro))
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_timeout_is_bounded(self):
        result = self.run_cli("--timeout", "0.000001", "check", str(self.macro))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("timed out", result.stderr)


if __name__ == "__main__":
    unittest.main()
