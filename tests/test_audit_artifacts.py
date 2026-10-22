"""Independent artifact audits catch broken links and wrong documentation owners."""
import json
from pathlib import Path
import tempfile
import unittest

import skill_paths

from audit_artifacts import audit


class AuditTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.docs = root / "docs"
        self.stubs = root / "stubs"
        (self.docs / "llm").mkdir(parents=True)
        self.stubs.mkdir()
        page = {"source_html": "ksapi_b.html", "section": "API интерфейсов. KsAPI",
                "symbol": "B.Right", "markdown_path": "llm/B.md"}
        (self.docs / "llm/pages.jsonl").write_text(json.dumps(page) + "\n")
        (self.docs / "llm/manifest.json").write_text(json.dumps({"generated_files": [], "unresolved_links": []}))

    def test_detects_any_wrong_owner_and_missing_link(self):
        (self.stubs / "ksapi.pyi").write_text('''from typing import Any
class A:
    """Источники SDK:
    - [B](../docs/llm/B.md)
    """
    field: Any
    def Wrong(self) -> Any: ...
''')
        report = audit(self.docs, self.stubs)
        self.assertFalse(report["ok"])
        self.assertEqual(report["unknown_count"], 2)
        self.assertEqual({item["error"] for item in report["errors"]},
                         {"missing local link", "documentation belongs to another symbol"})

    def test_accepts_class_and_inherited_sources(self):
        (self.docs / "llm/B.md").write_text("Native B documentation")
        (self.stubs / "ksapi.pyi").write_text('''class B:
    """Источники SDK:
    - [B](../docs/llm/B.md)
    """
    def Right(self) -> bool:
        """Real method description."""
        ...
class Child(B):
    """Источники SDK:
    - [B](../docs/llm/B.md)
    """
''')
        report = audit(self.docs, self.stubs)
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["counts"]["local_links_checked"], 2)

    def test_accepts_constant_sdk_sources(self):
        page = {"source_html": "constants.html", "section": "Константы API", "symbol": None,
                "markdown_path": "llm/constants.md", "content": "| VALUE | 1 | Description |"}
        (self.docs / "llm/pages.jsonl").write_text(json.dumps(page) + "\n")
        (self.docs / "llm/constants.md").write_text(page["content"])
        (self.stubs / "constants.pyi").write_text('''class constants:
    """Источники SDK:
    - [Константы API](../docs/llm/constants.md)
    """
    VALUE: int = 1
    "Description"
''')
        report = audit(self.docs, self.stubs)
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["counts"]["local_links_checked"], 1)

    def test_accepts_inline_enum_sources_on_native_class(self):
        page = {"source_html": "kind.html", "section": "Константы API", "symbol": None,
                "markdown_path": "llm/kind.md", "content": "| FIRST | 0 | First |"}
        (self.docs / "llm/pages.jsonl").write_text(json.dumps(page) + "\n")
        (self.docs / "llm/kind.md").write_text(page["content"])
        (self.stubs / "ksapi.pyi").write_text('''from typing import Literal
class B:
    """Источники SDK:
    - [Константы API](../docs/llm/kind.md)
    """
    def SetKind(self, value: Literal[0]) -> None:
        """Допустимые значения value (KindEnum):
        0 — FIRST: First
        """
        ...
''')
        report = audit(self.docs, self.stubs)
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["counts"]["local_links_checked"], 1)

    def test_rejects_method_level_sources(self):
        (self.stubs / "ksapi.pyi").write_text('''class B:
    def Right(self) -> bool:
        """Источник SDK: [ksapi_b.html](../docs/llm/B.md)"""
        ...
''')
        report = audit(self.docs, self.stubs)
        self.assertFalse(report["ok"])
        self.assertIn("SDK sources must be listed on the class", [item["error"] for item in report["errors"]])


if __name__ == "__main__":
    unittest.main()
