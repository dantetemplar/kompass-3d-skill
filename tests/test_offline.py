"""The pipeline must not execute input code, access network or load native libraries."""
from __future__ import annotations

import skill_paths

from contextlib import ExitStack
import encodings.cp437
import encodings.utf_16_le
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from docs import prepare_docs
from prepare_stubs import generate
from test_docs import write_fixture
import test_stubs


class OfflineTests(unittest.TestCase):
    def test_generators_need_neither_network_nor_native_loader(self):
        fixture = test_stubs.NativeTests(methodName="test_exact_native_controls")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "help.zip"
            write_fixture(source)
            with ExitStack() as stack:
                for name in ("socket.socket", "socket.create_connection", "ctypes.CDLL", "subprocess.Popen", "builtins.eval", "builtins.exec"):
                    stack.enter_context(patch(name, side_effect=AssertionError(f"Forbidden during preparation: {name}")))
                docs = prepare_docs(source, root / "docs", root / "sdk")
                stubs = generate(fixture.install, fixture.docs, root / "stubs", fixture.meta)
            self.assertEqual(docs["errors"], 0)
            self.assertGreater(stubs["counts"]["methods"], 0)


if __name__ == "__main__":
    unittest.main()
