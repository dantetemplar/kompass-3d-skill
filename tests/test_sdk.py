"""Offline tests for SDK retrieval and AST inspection."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import skill_paths
import sdk


BINDING = '''
raise RuntimeError("This module must never be imported")
class IBase:
    def Update(self, redraw=True):
        return True
class IPart(IBase):
    def SetName(self, name):
        native_set(name)
    def GetContainer(self):
        return IContainer(native_get())
class IContainer(IBase):
    pass
def GetKompas():
    return IPart(native_get())
'''


class SdkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "ksapi.py").write_text(BINDING, encoding="utf-8")
        (self.root / "constants.py").write_text(
            "class constants:\n    ksDocumentPart = 4  # Деталь\n", encoding="utf-8"
        )
        (self.root / "constants3d.py").write_text(
            "class constants:\n    o3d_planeXOY = 1  # Плоскость XOY\n", encoding="utf-8"
        )
        self.docs = self.root / "index.sqlite3"
        records = [
            {"id": "api7_add", "title": "Add — Выдавливание", "section": sdk.SECTIONS["api7"],
             "title_path": ["IExtrusions", "Add"], "content": "Создать операцию", "source_html": "add.html"},
            {"id": "api7_other", "title": "Other", "section": sdk.SECTIONS["api7"],
             "title_path": [], "content": "Выдавливание", "source_html": "other.html"},
            {"id": "api5_add", "title": "Выдавливание", "section": sdk.SECTIONS["api5"],
             "title_path": [], "content": "Legacy", "source_html": "legacy.html"},
        ]
        self.make_index(records)
        self.binding = sdk.Binding(self.root / "ksapi.py")

    def make_index(self, records):
        if self.docs.exists():
            self.docs.unlink()
        with sqlite3.connect(self.docs) as connection:
            connection.executescript('''
                CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
                INSERT INTO meta VALUES ('schema_version', '1');
                CREATE TABLE pages (key TEXT PRIMARY KEY, id TEXT, title TEXT, section TEXT,
                    source_html TEXT, content TEXT, title_path TEXT, parent TEXT,
                    prev TEXT, next TEXT, symbol TEXT);
                CREATE VIRTUAL TABLE pages_fts USING fts5(key UNINDEXED, title, content, symbol);
                CREATE TABLE links (source TEXT, target TEXT, fragment TEXT, label TEXT);
                CREATE TABLE toc (parent TEXT, child TEXT, position INTEGER);
                CREATE TABLE symbols (symbol TEXT, section TEXT, page_key TEXT);
            ''')
            for record in records:
                page = {
                    "key": "webhelp:" + record["source_html"], "title": "", "section": "",
                    "content": "", "title_path": [], "parent": None, "prev": None,
                    "next": None, "symbol": "", **record,
                }
                columns = ("key", "id", "title", "section", "source_html", "content", "title_path",
                           "parent", "prev", "next", "symbol")
                values = [json.dumps(page[k]) if k == "title_path" else page[k] for k in columns]
                connection.execute("INSERT INTO pages VALUES (?,?,?,?,?,?,?,?,?,?,?)", values)
                connection.execute("INSERT INTO pages_fts VALUES (?,?,?,?)", (
                    page["key"], page["title"], page["content"],
                    page["symbol"] + " " + " ".join(page["title_path"]),
                ))
                if page["symbol"]:
                    connection.execute("INSERT INTO symbols VALUES (?,?,?)", (
                        page["symbol"], page["section"], page["key"],
                    ))

    def test_inspect_inheritance_and_source_without_import(self):
        info = self.binding.inspect("IPart.Update", source=True)
        self.assertEqual(info["symbol"], "IBase.Update")
        self.assertEqual(info["signature"], "Update(self, redraw=True)")
        self.assertIn("return True", info["source"])

    def test_inspect_interface_and_return_metadata(self):
        info = self.binding.inspect("IPart")
        self.assertEqual(info["bases"], ["IBase"])
        self.assertEqual(len(info["members"]), 3)
        self.assertFalse(self.binding.inspect("IPart.SetName")["returns_value"])
        self.assertEqual(
            self.binding.inspect("IPart.GetContainer")["constructed_interfaces"], ["IContainer"]
        )
        self.assertEqual(self.binding.inspect("GetKompas")["signature"], "GetKompas()")

    def test_batch_inspection_parses_binding_once_and_keeps_partial_results(self):
        with patch.object(sdk, "Binding", wraps=sdk.Binding) as binding:
            with redirect_stdout(io.StringIO()) as output:
                code = sdk.main([
                    "--bin", str(self.root), "inspect", "IPart.SetName", "IPart7", "IPart.Update", "--source",
                ])
        self.assertEqual(binding.call_count, 1)
        self.assertEqual(code, 1)
        results = json.loads(output.getvalue())["results"]
        self.assertIn("native_set", results[0]["source"])
        self.assertIn("error", results[1])
        self.assertEqual(results[2]["symbol"], "IBase.Update")

    def test_compact_filtered_class_members(self):
        result = self.binding.inspect("IPart", match="update")
        self.assertEqual(len(result["members"]), 1)
        self.assertEqual(result["members"][0]["symbol"], "IBase.Update")
        self.assertNotIn("constructed_interfaces", result["members"][0])
        source = self.binding.inspect("IPart", source=True, match="setname")
        self.assertIn("native_set", source["members"][0]["source"])

    def test_batch_pages_reads_documentation_once_and_keeps_partial_results(self):
        with patch.object(sdk, "Documentation", wraps=sdk.Documentation) as index:
            with redirect_stdout(io.StringIO()) as output:
                code = sdk.main([
                    "--docs", str(self.docs), "page", "api7_add", "missing", "other.html",
                ])
        self.assertEqual(index.call_count, 1)
        self.assertEqual(code, 1)
        results = json.loads(output.getvalue())["results"]
        self.assertEqual(results[0]["id"], "api7_add")
        self.assertIn("error", results[1])
        self.assertEqual(results[2]["id"], "api7_other")

    def test_brief_verify_reports_missing_without_binding_dump(self):
        for symbols, expected in ((["IPart.Update"], 0), (["IPart.Update", "IPart7"], 1)):
            with self.subTest(symbols=symbols), redirect_stdout(io.StringIO()) as output:
                code = sdk.main(["--bin", str(self.root), "verify", "--brief", *symbols])
                result = json.loads(output.getvalue())
                self.assertEqual(code, expected)
                self.assertEqual(result["checked"], len(symbols))
                self.assertEqual(len(result["missing"]), expected)
                self.assertNotIn("results", result)

    def test_local_pagination(self):
        first = self.binding.search("ipart", 1)
        second = self.binding.search("ipart", 1, first["next_offset"])
        self.assertNotEqual(first["results"], second["results"])
        with redirect_stdout(io.StringIO()) as output:
            code = sdk.main(["--bin", str(self.root), "local", "ipart", "--limit", "1", "--offset", "1"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["results"], second["results"])

    def test_unknown_symbol_is_not_invented(self):
        for symbol in ("IPart7", "IPart.DoesNotExist", "IUnknown.Member"):
            with self.subTest(symbol=symbol), self.assertRaises(ValueError):
                self.binding.inspect(symbol)

    def test_local_search_and_limit(self):
        result = self.binding.search("ipart", 1)
        self.assertGreater(result["total"], 1)
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(self.binding.search("NoSuchSymbol", 5)["total"], 0)

    def test_document_search_sections_ranking_pagination(self):
        result = sdk.search_docs(self.docs, "ВЫДАВЛИВАНИЕ", "api7", 1)
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["results"][0]["id"], "api7_add")
        self.assertEqual(result["next_offset"], 1)
        next_page = sdk.search_docs(self.docs, "выдавливание", "api7", 1, 1)
        self.assertIsNone(next_page["next_offset"])
        self.assertEqual(next_page["results"][0]["id"], "api7_other")
        self.assertEqual(sdk.search_docs(self.docs, "выдавливание", "any", 5)["total"], 3)
        self.assertEqual(sdk.search_docs(self.docs, "IExtrusions Add", "api7", 5)["total"], 1)
        self.assertEqual(sdk.search_docs(self.docs, "nothing", "api7", 5)["results"], [])

    def test_full_page_and_missing_id(self):
        self.assertEqual(sdk.get_page(self.docs, "api7_add")["content"], "Создать операцию")
        with self.assertRaises(ValueError):
            sdk.get_page(self.docs, "missing")

    def test_duplicate_document_ids_require_source_html(self):
        records = [
            {"id": "bezier", "source_html": "bezier.html", "content": "first"},
            {"id": "bezier", "source_html": "_bezier.html", "content": "second"},
        ]
        self.make_index(records)
        with self.assertRaisesRegex(ValueError, "Ambiguous documentation id"):
            sdk.get_page(self.docs, "bezier")
        self.assertEqual(sdk.get_page(self.docs, "_bezier.html")["content"], "second")
        self.assertEqual(sdk.get_page(self.docs, "bezier.html")["content"], "first")

    def test_constants_search_by_russian_comment_and_name(self):
        result = sdk.search_constants(self.root, "плоскость XOY", 5)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["results"][0]["symbol"], "constants3d.constants.o3d_planeXOY")
        self.assertEqual(sdk.search_constants(self.root, "ksDocumentPart", 5)["total"], 1)

    def test_runner_imports_custom_sdk_and_preserves_arguments_and_cwd(self):
        macro = self.root / "macro with spaces.py"
        macro.write_text(
            '# /// script\n# requires-python = ">=3.11"\n# dependencies = []\n# ///\n'
            'import json, os, sys\nfrom constants import constants\n'
            'print(json.dumps({"args": sys.argv[1:], "cwd": os.getcwd(), '
            '"value": constants.ksDocumentPart, "ld": os.environ["LD_LIBRARY_PATH"]}))\n',
            encoding="utf-8",
        )
        # Script mode must not resolve/sync an unrelated project in the working directory.
        (self.root / "pyproject.toml").write_text(
            '[project]\nname = "unrelated"\nversion = "0.1"\n'
            'dependencies = ["this-package-must-not-be-resolved-by-the-runner"]\n', encoding="utf-8",
        )
        result = subprocess.run(
            ["bash", str(sdk.SKILL_DIR / "scripts/run.sh"), str(macro), "two words", "--flag"],
            capture_output=True, text=True, check=True, timeout=5, cwd=self.root,
            env={**os.environ, "KOMPAS_BIN": str(self.root), "UV_OFFLINE": "1",
                 "UV_PYTHON_DOWNLOADS": "never"},
        )
        output = json.loads(result.stdout)
        self.assertEqual(output["args"], ["two words", "--flag"])
        self.assertEqual(output["cwd"], str(self.root))
        self.assertEqual(output["value"], 4)
        self.assertEqual(output["ld"].split(":")[0], str(self.root))
        missing = subprocess.run(
            ["bash", str(sdk.SKILL_DIR / "scripts/run.sh"), str(self.root / "missing.py")],
            capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(missing.returncode, 1)
        self.assertIn("Macro not found", missing.stderr)

    def test_copied_skill_uses_its_own_docs_from_unrelated_cwd(self):
        copied = self.root / "standalone skill"
        shutil.copytree(sdk.SKILL_DIR, copied, ignore=shutil.ignore_patterns(".cache", "__pycache__"))
        docs = copied / ".cache/kompas-sdk-docs"
        docs.mkdir(parents=True)
        shutil.copyfile(self.docs, docs / "index.sqlite3")
        env = dict(os.environ)
        env.pop("KOMPAS_SDK_DOCS", None)
        result = subprocess.run(
            [sys.executable, str(copied / "scripts/sdk.py"), "page", "api7_add"],
            cwd=self.root, env=env, capture_output=True, text=True, check=True, timeout=5,
        )
        self.assertEqual(json.loads(result.stdout)["id"], "api7_add")
        self.assertFalse(list(copied.rglob("test_*.py")))
        for name in ("prepare_docs", "prepare_stubs", "check_stubs", "audit_artifacts"):
            with self.subTest(command=name):
                prepared = subprocess.run(
                    [sys.executable, str(copied / "scripts" / "prepare" / f"{name}.py"), "--help"],
                    cwd=self.root, env=env, capture_output=True, text=True, timeout=10,
                )
                self.assertEqual(prepared.returncode, 0, prepared.stderr)
                self.assertNotIn(str(sdk.SKILL_DIR), prepared.stdout)
                self.assertFalse((self.root / ".cache").exists())

    def test_missing_index_does_not_create_database_or_download(self):
        destination = self.root / "missing-index.sqlite3"
        with redirect_stderr(io.StringIO()) as error:
            code = sdk.main(["--docs", str(destination), "search", "эскиз"])
        self.assertEqual(code, 1)
        self.assertIn("scripts/prepare/prepare_docs.py", error.getvalue())
        self.assertFalse(destination.exists())

    def test_native_symbol_lookup_navigation_and_safe_fts(self):
        self.make_index([
            {"id": "native", "source_html": "ksapi_isketch.html", "title": "Интерфейс ISketch",
             "section": sdk.SECTIONS["ksapi"], "symbol": "ISketch"},
            {"id": "method", "source_html": "ksapi_isketch_beginedit.html", "title": "BeginEdit",
             "section": sdk.SECTIONS["ksapi"], "symbol": "ISketch.BeginEdit",
             "content": "Редактирование эскиза"},
            {"id": "com", "source_html": "isketch_beginedit.html", "title": "BeginEdit",
             "section": sdk.SECTIONS["api7"], "symbol": "ISketch.BeginEdit"},
        ])
        with sqlite3.connect(self.docs) as connection:
            connection.execute("INSERT INTO toc VALUES (?,?,?)", (
                "webhelp:ksapi_isketch.html", "webhelp:ksapi_isketch_beginedit.html", 0,
            ))
            connection.execute("INSERT INTO links VALUES (?,?,?,?)", (
                "webhelp:ksapi_isketch_beginedit.html", "webhelp:ksapi_isketch.html", "anchor", "Интерфейс",
            ))
        self.assertEqual(sdk.get_page(self.docs, "ISketch.BeginEdit")["id"], "method")
        with sdk.Documentation(self.docs) as index:
            self.assertEqual(index.search("ISketch Begin", "ksapi", 8)["total"], 1)
            self.assertEqual(index.toc("ISketch", "ksapi", 20, 0)["total"], 1)
            self.assertEqual(index.links("ISketch.BeginEdit", "ksapi", 20, 0)["results"][0]["fragment"], "anchor")
            self.assertEqual(index.search('" OR * -', "ksapi", 8)["total"], 0)
            self.assertEqual(index.search("!!!", "ksapi", 8)["total"], 0)
        with redirect_stdout(io.StringIO()) as output:
            code = sdk.main(["--docs", str(self.docs), "search", "BeginEdit"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["total"], 1)

    def test_verify_exit_status_and_missing_file_diagnostic(self):
        for symbols, expected in ((["IPart.Update"], 0), (["IPart.Update", "IPart7"], 1)):
            with self.subTest(symbols=symbols), redirect_stdout(io.StringIO()) as output:
                code = sdk.main(["--bin", str(self.root), "verify", *symbols])
                self.assertEqual(code, expected)
                self.assertEqual(json.loads(output.getvalue())["ok"], expected == 0)
        with redirect_stderr(io.StringIO()) as error:
            code = sdk.main(["--bin", str(self.root / "missing"), "inspect", "IPart"])
        self.assertEqual(code, 1)
        self.assertIn("FileNotFoundError", error.getvalue())


if __name__ == "__main__":
    unittest.main()
