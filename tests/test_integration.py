"""Integration between independently generated documentation and the portable reader."""
from __future__ import annotations

from skill_paths import SCRIPTS_DIR

import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from zipfile import ZipFile

from docs import NATIVE_SECTION, prepare_docs

SKILL_SCRIPTS = SCRIPTS_DIR
spec = importlib.util.spec_from_file_location("portable_sdk", SKILL_SCRIPTS / "sdk.py")
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)


class IntegrationTests(unittest.TestCase):
    def test_prepared_index_search_navigation_and_portability(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "help.zip"
            with ZipFile(archive, "w") as stream:
                for name, title, path, body, parent in (
                    ("ksapi_isketch", "Интерфейс ISketch", [NATIVE_SECTION, "Интерфейс ISketch"],
                     '<p>Эскиз</p><a href="ksapi_isketch_beginedit.html#details">Редактировать</a>', ""),
                    ("ksapi_isketch_beginedit", "BeginEdit - Редактирование эскиза",
                     [NATIVE_SECTION, "Интерфейс ISketch", "ISketch - методы", "BeginEdit - Редактирование эскиза"],
                     '<p id="details">Войти в режим редактирования</p><a href="ksapi_isketch.html">Интерфейс</a>', "ksapi_isketch.html"),
                ):
                    data = {
                        "hmTitle": title, "hmTitlePath": " > ".join(path), "hmBody": body,
                        "hmParentLink": parent, "hmPrevLink": "", "hmNextLink": "",
                    }
                    stream.writestr("jstopics/" + name + ".js", "hmLoadTopic(" + json.dumps(data, ensure_ascii=False) + ");")
                stream.writestr("js/hmcontent.js", 'hmLoadTOC({items:[{cp:"Эскиз",hf:"ksapi_isketch.html",items:[{cp:"Редактирование",hf:"ksapi_isketch_beginedit.html",items:[]}]}]});')
                stream.writestr("js/hmkwindex.js", 'hmLoadIndex({keywords:[]});')
            out = root / "original"
            summary = prepare_docs(archive, out, root / "sdk")
            self.assertEqual(summary["errors"], 0)
            relocated = root / "copied"
            shutil.copytree(out, relocated)
            shutil.rmtree(out)
            with reader.Documentation(relocated) as index:
                page = index.resolve("ISketch.BeginEdit")
                self.assertEqual(page["source_html"], "ksapi_isketch_beginedit.html")
                hits = index.search("ISketch Begin", "ksapi", 5)
                self.assertGreaterEqual(hits["total"], 1)
                self.assertEqual(hits["results"][0]["symbol"], "ISketch.BeginEdit")
                self.assertEqual(index.search("РЕДАКТИРОВ", "ksapi", 5)["total"], 2)
                roots = index.toc(None, "ksapi", 5, 0)
                self.assertEqual(roots["total"], 1)
                children = index.toc("ISketch", "ksapi", 5, 0)
                self.assertEqual(children["results"][0]["symbol"], "ISketch.BeginEdit")
                links = index.links("ISketch", "ksapi", 5, 0)
                self.assertEqual(links["results"][0]["fragment"], "details")

    def test_rejects_stale_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "index.sqlite3"
            with sqlite3.connect(path) as connection:
                connection.executescript("CREATE TABLE meta(key TEXT, value TEXT); INSERT INTO meta VALUES ('schema_version','1'); INSERT INTO meta VALUES ('source_sha256','old');")
            (root / "llm").mkdir()
            (root / "llm/manifest.json").write_text(json.dumps({"source": {"sha256": "new"}}))
            with self.assertRaisesRegex(ValueError, "Stale SDK index"):
                reader.Documentation(path)

    def test_rejects_unknown_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.sqlite3"
            with sqlite3.connect(path) as connection:
                connection.executescript("CREATE TABLE meta(key TEXT, value TEXT); INSERT INTO meta VALUES ('schema_version','999');")
            with self.assertRaisesRegex(ValueError, "schema"):
                reader.Documentation(path)


if __name__ == "__main__":
    unittest.main()
