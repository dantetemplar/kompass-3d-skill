"""Run with python3 -m unittest discover -s prepare -p test_docs.py."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import closing
from pathlib import Path
from urllib.parse import unquote

from docs import (
    NATIVE_SECTION,
    PAGE_COLUMNS,
    canonical_key,
    html_to_markdown,
    infer_symbol,
    parse_js_call,
    prepare_docs,
)


def js_call(function: str, data: dict) -> str:
    return function + "(" + json.dumps(data, ensure_ascii=True) + ");"


def topic(title: str, path: list[str], body: str, **fields) -> str:
    return js_call("hmLoadTopic", {"hmTitle": title, "hmTitlePath": " > ".join(path), "hmBody": body, **fields})


def write_fixture(path: Path, extra: bool = False) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for prefix in ("", "nested/"):
            archive.writestr(prefix + "jstopics/owner.js", topic("Интерфейс ISketch", [NATIVE_SECTION, "Интерфейс ISketch"], '<p id="owner-anchor">Интерфейс эскиза</p>'))
            archive.writestr(prefix + "jstopics/member.js", topic(
                "GetPoint3D - Получить точку", [NATIVE_SECTION, "Интерфейс ISketch", "ISketch - методы", "GetPoint3D - Получить точку"],
                '<p id="точка">Координаты &amp; точка <a href="owner.html#owner-anchor">Владелец</a> '
                '<a href="#точка">Якорь</a><a href="missing.html">missing</a></p><script>bad()</script>',
                hmParentLink="owner.html", hmPrevLink="owner.html", hmNextLink="member.html#точка"))
            archive.writestr(prefix + "js/hmcontent.js", js_call("hmLoadTOC", {"items": [
                {"cp": "ISketch", "hf": "owner.html", "items": [{"cp": "GetPoint3D", "hf": "member.html", "items": []}]},
            ]}))
            archive.writestr(prefix + "js/hmkwindex.js", js_call("hmLoadIndex", {"keywords": [
                {"kw": "ISketch", "hrefs": ["owner.html#owner-anchor"], "captions": ["ISketch"], "subkw": [
                    {"kw": "GetPoint3D", "hrefs": ["member.html#точка"], "captions": ["точка"], "subkw": []},
                ]},
            ]}))
        # The same symbol name in the Automation section must remain separate.
        automation = "API интерфейсов. Версия 7"
        archive.writestr("jstopics/com_member.js", topic("GetPoint3D - COM", [automation, "Интерфейс ISketch", "ISketch - методы", "GetPoint3D - COM"], "<p>Automation HRESULT</p>"))
        if extra:
            archive.writestr("jstopics/stale.js", topic("Интерфейс IStale", [NATIVE_SECTION, "Интерфейс IStale"], "<p>obsolete</p>"))


class LiteralTests(unittest.TestCase):
    def test_js_unicode_escapes_and_safe_literals(self):
        data = parse_js_call(r'''/* hi */ hmLoadTopic({hmTitle:"\u0422\u043e\u0447\u043a\u0430 \ud83d\ude00", body:'a\x20b\n\t\"\'\\\/', enabled:true, value:null, items:[1,-2.5,],}); // end''', "hmLoadTopic")
        self.assertEqual(data["hmTitle"], "Точка 😀")
        self.assertEqual(data["body"], "a b\n\t\"'\\/")
        self.assertEqual(data["items"], [1, -2.5])
        self.assertTrue(data["enabled"])
        self.assertIsNone(data["value"])

    def test_rejects_executable_js_and_malformed_literals(self):
        for raw in ('hmLoadTopic({x:alert(1)})', 'hmLoadTopic({x:"ok"}); alert(1)',
                    'hmLoadTopic({x:"a",x:"b"})', r'hmLoadTopic({x:"\uZZZZ"})', 'hmLoadTopic({x:1}):'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_js_call(raw, "hmLoadTopic")

    def test_html_text_and_links(self):
        markdown = html_to_markdown('<h2>Заголовок</h2><p>A &amp; B&nbsp;<a href="x.html#y">ссылка</a></p>'
                                    '<script>hidden</script><style>bad</style><ul><li>one</li></ul>'
                                    '<pre>int x = 1;</pre><a href="javascript:evil()">safe</a>')
        self.assertIn("## Заголовок", markdown)
        self.assertIn("A & B [ссылка](<x.html#y>)", markdown)
        self.assertIn("- one", markdown)
        self.assertIn("```\nint x = 1;\n```", markdown)
        self.assertNotIn("hidden", markdown)
        self.assertNotIn("evil", markdown)

    def test_preformatted_code_keeps_indentation_tabs_blank_lines_and_fences(self):
        code = 'if (ready) {\r\n    x = 1;\r\n\r\n\r\n\tcall();\r\n    // ```\r\n}\r\n'
        fragment = '<p>Before</p><pre><code>' + code + '</code></pre><p>After</p>'
        markdown = html_to_markdown(fragment)
        self.assertIn('````\n' + code.replace('\r\n', '\n') + '````', markdown)
        self.assertIn('Before\n', markdown)
        self.assertTrue(markdown.endswith('After'))

    def test_tables_keep_rows_columns_spans_and_links(self):
        markdown = html_to_markdown(
            '<table><tr><th>Parameter</th><th colspan="2">Meaning</th></tr>'
            '<tr><td rowspan="2">x</td><td><p>Input</p><p>plane</p></td>'
            '<td><a href="owner.html">ISketch</a></td></tr>'
            '<tr><td>Output | point</td><td>3D</td></tr></table>'
            '<table><tr><td>TRUE</td><td>Success</td></tr></table>')
        self.assertIn('| Parameter | Meaning |  |\n| --- | --- | --- |', markdown)
        self.assertIn('| x | Input<br>plane | [ISketch](<owner.html>) |', markdown)
        self.assertIn('|  | Output \\| point | 3D |', markdown)
        self.assertIn('| Column 1 | Column 2 |\n| --- | --- |\n| TRUE | Success |', markdown)

    def test_preformatted_code_inside_table_cell(self):
        markdown = html_to_markdown('<table><tr><td>Example</td><td><pre>    a | b\n\n\t&amp; x</pre></td></tr></table>')
        self.assertIn('<pre>    a &#124; b&#10;&#10;\t&amp; x</pre>', markdown)
        self.assertIn('| Example |', markdown)

    def test_nested_table_stays_in_its_parent_cell(self):
        markdown = html_to_markdown('<table><tr><td>Outer<table><tr><td>Inner</td>'
                                    '<td>Value</td></tr></table></td><td>Second</td></tr></table>')
        self.assertIn('Outer', markdown)
        self.assertIn('Inner', markdown)
        self.assertIn('Value', markdown)
        self.assertIn('Second |', markdown)
        self.assertNotIn('__kompas_sdk_block_', markdown)

    def test_conservative_symbols(self):
        path = [NATIVE_SECTION, "Интерфейс ISketch", "ISketch - методы", "GetPoint3D - Получить точку"]
        self.assertEqual(infer_symbol(path[-1], path), "ISketch.GetPoint3D")
        self.assertEqual(infer_symbol("Интерфейс ISketch", path[:2]), "ISketch")
        self.assertIsNone(infer_symbol("ISketch - методы", path[:3]))
        self.assertIsNone(infer_symbol("Example - пример", [NATIVE_SECTION, "Example - пример"]))
        self.assertIsNone(infer_symbol("Example - пример", [NATIVE_SECTION, "Интерфейс ISketch", "Example - пример"]))


class GenerationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "help.zip"
        self.out = self.root / "cache"
        write_fixture(self.source)

    def tearDown(self):
        self.temporary.cleanup()

    def generate(self):
        return prepare_docs(self.source, self.out, self.root / "kompas3d-v25")

    def test_schema_collisions_links_toc_symbols_and_search(self):
        summary = self.generate()
        self.assertEqual(summary["pages"], 5)
        self.assertEqual(summary["keywords"], 4)
        self.assertEqual(summary["errors"], 0)
        with closing(sqlite3.connect(self.out / "index.sqlite3")) as database:
            self.assertEqual(tuple(row[1] for row in database.execute("PRAGMA table_info(pages)")), PAGE_COLUMNS)
            self.assertEqual(database.execute("SELECT count(*) FROM pages WHERE id='member'").fetchone()[0], 2)
            self.assertEqual(database.execute("SELECT parent,prev,next FROM pages WHERE key='webhelp:nested/member.html'").fetchone(),
                             ("webhelp:nested/owner.html", "webhelp:nested/owner.html", "webhelp:nested/member.html"))
            self.assertEqual(database.execute("SELECT target FROM links WHERE source='webhelp:nested/member.html' AND label='Владелец'").fetchone()[0], "webhelp:nested/owner.html")
            self.assertEqual(database.execute("SELECT parent,child FROM toc WHERE parent='webhelp:nested/owner.html'").fetchone(), ("webhelp:nested/owner.html", "webhelp:nested/member.html"))
            self.assertEqual(database.execute("SELECT count(*) FROM symbols WHERE symbol='ISketch.GetPoint3D' AND section=?", (NATIVE_SECTION,)).fetchone()[0], 2)
            self.assertEqual(database.execute("SELECT count(*) FROM pages_fts WHERE pages_fts MATCH ?", ('"ISketch.GetPoint3D"',)).fetchone()[0], 3)
            self.assertEqual(database.execute("SELECT count(*) FROM pages_fts WHERE pages_fts MATCH ?", ('координаты',)).fetchone()[0], 2)
            self.assertEqual(dict(database.execute("SELECT key,value FROM meta"))["source_sha256"], hashlib.sha256(self.source.read_bytes()).hexdigest())
        keywords = [json.loads(line) for line in (self.out / "llm/keywords.jsonl").read_text().splitlines()]
        self.assertEqual(keywords[-1]["path"], ["ISketch", "GetPoint3D"])
        self.assertEqual(keywords[-1]["targets"][0]["key"], "webhelp:nested/member.html")
        manifest = json.loads((self.out / "llm/manifest.json").read_text())
        self.assertEqual(len(manifest["unresolved_links"]), 2)
        self.assertTrue(all(item["target"] == "missing.html" for item in manifest["unresolved_links"]))
        self.assertEqual(len(manifest["source"]["members"]), 9)
        self.assertIn("pages_jsonl", manifest["schemas"])

    def test_markdown_links_exist_and_sections_are_separate(self):
        self.generate()
        index = (self.out / "llm/index.md").read_text()
        self.assertIn(NATIVE_SECTION, index)
        self.assertIn("API интерфейсов. Версия 7", index)
        for document in self.out.rglob("*.md"):
            text = document.read_text()
            for href in re.findall(r"\]\(<([^>]+)>\)", text):
                if href.startswith(("https:", "http:", "mailto:")):
                    continue
                path, _, fragment = unquote(href).partition("#")
                target = document.parent / path if path else document
                self.assertTrue(target.is_file(), f"{document}: {href}")
                if fragment:
                    self.assertIn(f'id="{fragment}"', target.read_text())
        self.assertGreaterEqual(len(list((self.out / "llm/api_objects").iterdir())), 2)

    def test_jsonl_markdown_identity_matches_exact_generated_file_and_anchor(self):
        self.generate()
        pages = [json.loads(line) for line in (self.out / 'llm/pages.jsonl').read_text().splitlines()]
        for page in pages:
            document = self.out / page['markdown_path']
            self.assertTrue(document.is_file())
            self.assertIn(f'<a id="{page["markdown_fragment"]}"></a>', document.read_text())
            self.assertTrue(page['markdown_path'].startswith('llm/api_objects/'))
            self.assertNotIn('#', page['markdown_fragment'])

    def test_direct_api_refuses_installation_and_opt_outputs_before_reading(self):
        for output, install in ((self.root / 'sdk/cache', self.root / 'sdk'),
                                (Path('/opt/do-not-create-docs-output'), self.root / 'sdk')):
            with self.subTest(output=output), self.assertRaises(ValueError):
                prepare_docs(self.root / 'missing.zip', output, install)
            self.assertFalse(output.exists())

    def test_structured_content_is_preserved_through_all_outputs(self):
        with zipfile.ZipFile(self.source, 'a') as archive:
            archive.writestr('jstopics/format.js', topic('Formatting', ['Formatting'],
                '<table><tr><td>x</td><td>Coordinate</td></tr></table>'
                '<pre>if (x) {\n    call();\n\n\n\treturn;\n}</pre>'))
        self.generate()
        page = next(json.loads(line) for line in (self.out / 'llm/pages.jsonl').read_text().splitlines()
                    if json.loads(line)['id'] == 'format')
        expected = 'if (x) {\n    call();\n\n\n\treturn;\n}'
        with closing(sqlite3.connect(self.out / 'index.sqlite3')) as database:
            stored = database.execute('SELECT content FROM pages WHERE id=?', ('format',)).fetchone()[0]
        for text in (page['content'], stored, (self.out / page['markdown_path']).read_text()):
            self.assertIn('| x | Coordinate |', text)
            self.assertIn(expected, text)

    def test_repeat_is_byte_deterministic_preserves_unrelated_files(self):
        (self.out / ".git").mkdir(parents=True)
        (self.out / ".git/config").write_text("old clone")
        self.generate()
        manifest = json.loads((self.out / "llm/manifest.json").read_text())
        before = {name: (self.out / name).read_bytes() for name in manifest["generated_files"]}
        self.generate()
        after = {name: (self.out / name).read_bytes() for name in manifest["generated_files"]}
        self.assertEqual(before, after)
        self.assertEqual((self.out / ".git/config").read_text(), "old clone")

    def test_stale_owned_markdown_removed_only(self):
        write_fixture(self.source, extra=True)
        self.generate()
        marker = self.out / "llm/api_objects/user.md"
        marker.write_text("keep")
        stale = [path for path in self.out.rglob("IStale*.md")]
        self.assertEqual(len(stale), 1)
        write_fixture(self.source)
        self.generate()
        self.assertFalse(stale[0].exists())
        self.assertEqual(marker.read_text(), "keep")

    def test_output_symlinks_refused(self):
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        self.out.mkdir()
        (self.out / "llm").symlink_to(elsewhere, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.generate()
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_unsafe_archive_and_duplicate_paths_refused(self):
        with zipfile.ZipFile(self.source, "w") as archive:
            archive.writestr("../jstopics/bad.js", topic("x", ["x"], "x"))
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            self.generate()

    def test_bad_topic_reported_without_executing(self):
        with zipfile.ZipFile(self.source, "a") as archive:
            archive.writestr("jstopics/evil.js", 'hmLoadTopic({hmBody:execute()})')
        summary = self.generate()
        self.assertEqual(summary["errors"], 1)
        self.assertEqual(summary["pages"], 5)
        manifest = json.loads((self.out / "llm/manifest.json").read_text())
        self.assertEqual(manifest["errors"][0]["source"], "jstopics/evil.js")

    def test_canonical_keys_keep_full_source_path(self):
        self.assertNotEqual(canonical_key("one/member.html"), canonical_key("two/member.html"))


if __name__ == "__main__":
    unittest.main()
