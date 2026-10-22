"""Offline tests for the Markdown TOC updater."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "update_toc.py"
SPEC = importlib.util.spec_from_file_location("update_toc", SCRIPT)
toc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(toc)


class UpdateTocTests(unittest.TestCase):
    def test_updates_h2_h3_and_preserves_document_body(self):
        prefix = "# Title\n\nIntroduction.\n\n## Table of Contents\n"
        body = (
            "## Установка\n\nText.\n\n### Python и `ksapi`\n\n"
            "#### Not listed\n\n## Undo/Redo: симптом → действие\n"
        )
        source = prefix + "\n- stale\n\n" + body
        expected = prefix + (
            "\n- [Установка](#установка)\n"
            "  - [Python и ksapi](#python-и-ksapi)\n"
            "- [Undo/Redo: симптом → действие](#undoredo-симптом--действие)\n\n"
        ) + body
        self.assertEqual(toc.update_toc(source), expected)
        self.assertEqual(toc.update_toc(expected), expected)

    def test_ignores_frontmatter_and_fenced_code(self):
        source = (
            "---\n## Metadata\n---\n# Title\n## Table of Contents\n\n## Real\n"
            "```python\n## Fake\n``\n### Still fake\n```\n"
            "~~~~markdown\n## Also fake\n~~~\n### Still fenced\n~~~~\n"
            "### Visible\n"
        )
        result = toc.update_toc(source)
        generated = result.split("## Table of Contents\n", 1)[1].split("## Real\n", 1)[0]
        self.assertEqual(generated, "\n- [Real](#real)\n  - [Visible](#visible)\n\n")
        self.assertTrue(result.endswith(source.split("## Real\n", 1)[1]))

    def test_duplicate_anchors_include_h1_h4_and_existing_suffixes(self):
        source = (
            "# Same\n## Table of Contents\n\n"
            "## Same\n### Same-1\n#### Same\n### Same\n"
        )
        result = toc.update_toc(source)
        self.assertIn("- [Same](#same-1)", result)
        self.assertIn("  - [Same-1](#same-1-1)", result)
        self.assertIn("  - [Same](#same-3)", result)

    def test_links_emphasis_and_closing_hashes(self):
        source = "# Title\n## Table of Contents\n\n## **Read** [SDK](https://example.com) ###\n"
        self.assertIn("- [Read SDK](#read-sdk)", toc.update_toc(source))

    def test_preserves_crlf(self):
        source = "# Title\r\n\r\n## Table of Contents\r\n\r\n## Setup\r\nText.\r\n"
        result = toc.update_toc(source)
        self.assertIn("- [Setup](#setup)\r\n", result)
        self.assertNotIn("\n", result.replace("\r\n", ""))
        self.assertEqual(toc.update_toc(result), result)

    def test_missing_or_duplicate_toc_is_an_error(self):
        for source in ("# Title\n## Setup\n", "## Table of Contents\n## Table of Contents\n"):
            with self.subTest(source=source), self.assertRaises(ValueError):
                toc.update_toc(source)

    def test_cli_check_does_not_write_and_update_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            document = Path(directory) / "skill.md"
            original = b"# Title\r\n## Table of Contents\r\n\r\n## Setup\r\nBody.\r\n"
            document.write_bytes(original)
            command = [sys.executable, str(SCRIPT), str(document)]
            check = subprocess.run([*command, "--check"], capture_output=True, text=True)
            self.assertEqual(check.returncode, 1, check.stderr)
            self.assertEqual(document.read_bytes(), original)
            update = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(update.returncode, 0, update.stderr)
            self.assertIn(b"[Setup](#setup)\r\n", document.read_bytes())
            check = subprocess.run([*command, "--check"], capture_output=True, text=True)
            self.assertEqual(check.returncode, 0, check.stderr)

    def test_default_document_is_current(self):
        source = toc.DEFAULT_DOCUMENT.read_text(encoding="utf-8")
        self.assertEqual(toc.update_toc(source), source)


if __name__ == "__main__":
    unittest.main()
