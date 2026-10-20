"""Publication and unknown-type coverage include more than method signatures."""
import json
import tempfile
from pathlib import Path
import unittest

from artifacts import atomic_write, file_identity, unknown_annotations, validate_documentation


class ArtifactTests(unittest.TestCase):
    def test_any_inventory_includes_attributes_constants_and_signatures(self):
        result = unknown_annotations({"sample.pyi": "from typing import Any\nvalue: Any\nclass A:\n    attr: list[Any]\n    def method(self, arg: Any) -> Any: ...\n"})
        self.assertEqual(len(result), 4)
        self.assertEqual({item["field"] for item in result}, {"value", "attr", "arg", "return"})

    def test_stale_documentation_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "help.zip"
            archive.write_bytes(b"original")
            manifest = {"package": {"install": str(root / "sdk")}, "source": file_identity(archive)}
            (root / "manifest.json").write_text(json.dumps(manifest))
            validate_documentation(root / "pages.jsonl", root / "sdk")
            with self.assertRaisesRegex(ValueError, "different SDK"):
                validate_documentation(root / "pages.jsonl", root / "other")
            archive.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "changed"):
                validate_documentation(root / "pages.jsonl", root / "sdk")

    def test_atomic_write_preserves_unrelated_files_refuses_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "marker").write_text("keep")
            target = root / "stub.pyi"
            atomic_write(target, "value: int\n")
            before = file_identity(target)
            atomic_write(target, "value: int\n")
            self.assertEqual(before, file_identity(target))
            (root / "alias").symlink_to(target)
            with self.assertRaises(ValueError):
                atomic_write(root / "alias", "wrong")
            self.assertEqual((root / "marker").read_text(), "keep")
            self.assertEqual(sorted(path.name for path in root.iterdir()), ["alias", "marker", "stub.pyi"])


if __name__ == "__main__":
    unittest.main()
