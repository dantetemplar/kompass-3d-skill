"""Offline integrity checks for the published practice corpus and its dependencies."""
import ast
from collections import Counter
from pathlib import Path
import re
import unittest
from urllib.parse import quote, unquote
from zipfile import ZipFile

REPOSITORY = Path(__file__).resolve().parents[1]
CORPUS = REPOSITORY / "PracticeProblems_ALL250_CSWA"


class PracticeProblemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse((REPOSITORY / "tools/extract_pdf.py").read_text())
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name in {"dependencies", "markdown"}]
        namespace = {"Path": Path, "re": re, "quote": quote, "ZipFile": ZipFile}
        exec(compile(ast.Module(body=functions, type_ignores=[]), "extract-markdown", "exec"), namespace)
        cls.dependencies = staticmethod(namespace["dependencies"])

    def test_all_tasks_have_drawings_and_valid_local_links(self):
        documents = sorted(CORPUS.glob("Level*/*.md"))
        self.assertEqual(len(documents), 250)
        for document in documents:
            with self.subTest(document=document):
                text = document.read_text()
                self.assertIn("## Текст задания", text)
                self.assertIn(f"![Чертёж]({document.with_suffix('.jpg').name})", text)
                self.assertNotIn("[Исходный PDF]", text)
                for url in re.findall(r'\]\(([^)]+)\)', text):
                    self.assertTrue((document.parent / unquote(url)).is_file(), url)

    def test_archive_links_and_manifests_match_the_actual_components(self):
        directory = CORPUS / "Level09_AssembliesMates"
        documents = sorted(directory.glob("*.md"))
        self.assertEqual(len(documents), 16)
        linked = set()
        for document in documents:
            text = document.read_text()
            links = re.findall(r'\]\(([^)]+\.zip)\)', text)
            self.assertEqual(len(links), 1, document)
            archive = directory / unquote(links[0])
            linked.add(archive)
            with ZipFile(archive) as source:
                self.assertIsNone(source.testzip(), archive)
                names = [item.filename for item in source.infolist() if not item.is_dir()]
            self.assertTrue(all(Path(name).suffix.lower() in {".sldprt", ".sldasm"}
                                for name in names), archive)
            for name in names:
                self.assertIn(f"- `{name}`", text)
        self.assertEqual(len(linked), 10)
        self.assertEqual(linked, set(directory.glob("*.zip")))

    def test_dependency_sections_survive_regeneration(self):
        counts = Counter()
        for document in sorted(CORPUS.glob("Level*/*.md")):
            text = document.read_text()
            original = text.split("## Текст задания\n\n", 1)[1]
            section = self.dependencies(document.with_suffix(".pdf"), original)
            if section:
                self.assertIn(section, text, document)
            if "## Предыдущее задание" in section:
                counts[document.parent.name] += 1
        self.assertEqual(counts, {"Level09_AssembliesMates": 6, "Level10_CSWAExamLevel": 9})

    def test_source_errata_are_explicit_and_original_wording_is_preserved(self):
        directory = CORPUS / "Level10_CSWAExamLevel"
        text = (directory / "PracticeProblems_10_7C_ENG.md").read_text()
        self.assertIn("[10.7B](PracticeProblems_10_7B_ENG.md)", text)
        self.assertIn("Вероятная опечатка", text)
        self.assertIn("HINT: Start with the 9.7B part.", text)
        text = (CORPUS / "Level09_AssembliesMates/PracticeProblems_9_10_ENG.md").read_text()
        self.assertIn("## Примечание к оригиналу", text)
        self.assertIn("Revolve Boss/Cut (Level 6)", text.split("## Текст задания", 1)[1])


if __name__ == "__main__":
    unittest.main()
