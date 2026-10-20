"""Independent artifact audits catch broken links and wrong documentation owners."""
import json
from pathlib import Path
import tempfile
import unittest

import skill_paths

from audit_artifacts import audit


class AuditTests(unittest.TestCase):
    def test_detects_any_wrong_owner_and_missing_link(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            docs = root / "docs"
            stubs = root / "stubs"
            (docs / "llm").mkdir(parents=True)
            stubs.mkdir()
            page = {"source_html": "ksapi_a.html", "section": "API интерфейсов. KsAPI", "symbol": "A.Right"}
            (docs / "llm/pages.jsonl").write_text(json.dumps(page) + "\n")
            (docs / "llm/manifest.json").write_text(json.dumps({"generated_files": [], "unresolved_links": []}))
            (stubs / "ksapi.pyi").write_text('''from typing import Any
class A:
    field: Any
    def Wrong(self) -> Any:
        """Native documentation: ksapi_a.html (id: test)
        Local documentation: [test](missing.md#missing)
        """
        ...
''')
            report = audit(docs, stubs)
            self.assertFalse(report["ok"])
            self.assertEqual(report["unknown_count"], 2)
            self.assertEqual({item["error"] for item in report["errors"]}, {"missing local link", "documentation belongs to another symbol"})


if __name__ == "__main__":
    unittest.main()
