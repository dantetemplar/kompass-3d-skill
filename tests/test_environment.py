"""Preparation must use the selected installation and never alter its sources."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import skill_paths

from environment import validate_environment, validate_output
import audit_artifacts
import check_stubs
import prepare_docs
import prepare_stubs


class EnvironmentTests(unittest.TestCase):
    def test_default_caches_belong_to_the_installable_skill(self):
        self.assertEqual(prepare_docs.DEFAULT_OUT, skill_paths.SKILL_DIR / ".cache/kompas-sdk-docs")
        for module in (prepare_stubs, check_stubs, audit_artifacts):
            with self.subTest(module=module.__name__):
                self.assertEqual(module.SKILL_DIR, skill_paths.SKILL_DIR)

    def test_matching_installation_environment(self):
        install = Path("/chosen/kompas")
        with patch.dict(os.environ, {"PYTHONPATH": "/chosen/kompas/Bin:/other", "LD_LIBRARY_PATH": "/other:/chosen/kompas/Bin"}):
            validate_environment(install)
        with patch.dict(os.environ, {"PYTHONPATH": "/other", "LD_LIBRARY_PATH": "/chosen/kompas/Bin"}):
            with self.assertRaisesRegex(ValueError, "PYTHONPATH"):
                validate_environment(install)

    def test_sdk_and_opt_outputs_are_refused(self):
        for output in (Path("/opt/new-cache"), Path("/chosen/kompas/Bin/stubs")):
            with self.assertRaises(ValueError):
                validate_output(output, Path("/chosen/kompas"))

    def test_symlink_output_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "real").mkdir()
            (root / "alias").symlink_to(root / "real", target_is_directory=True)
            with self.assertRaises(ValueError):
                validate_output(root / "alias/cache", root / "sdk")
            validate_output(root / "new/cache", root / "sdk")


if __name__ == "__main__":
    unittest.main()
