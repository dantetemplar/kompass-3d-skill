"""Offline regression tests: no native KsAPI imports or CAD execution."""
import importlib.util
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch


MACROS_DIR = Path(__file__).resolve().parents[1] / "macros"


def load_macro(name):
    api = ModuleType("ksapi")
    api.IKompasDocument2D = lambda doc: doc
    api.IDrawingContainer = lambda view: view
    constants = ModuleType("constants")
    constants.constants = SimpleNamespace(
        ksDocumentDrawing=1, ksDocumentFragment=2, ksDocumentPart=3, ksDocumentAssembly=4,
    )
    spec = importlib.util.spec_from_file_location(name, MACROS_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"ksapi": api, "constants": constants}), patch.object(
        sys, "path", list(sys.path)
    ):
        spec.loader.exec_module(module)
    return module


class MacroTests(unittest.TestCase):
    def setUp(self):
        self.touch = load_macro("touch_active")
        self.draw = load_macro("draw_rectangle")

    def test_portal_copies_never_overwrite_or_reuse_same_named_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "run/user/1000/doc/token/model.m3d"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"NEW1")
            writable = root / "models"
            writable.mkdir()
            existing = writable / source.name
            existing.write_bytes(b"OLD2")
            with patch.object(self.touch, "WRITABLE", writable):
                first = self.touch.ensure_writable(source)
                source.write_bytes(b"different size")
                second = self.touch.ensure_writable(source)
            self.assertNotEqual(first, second)
            self.assertEqual(first.name, source.name)
            self.assertEqual(first.read_bytes(), b"NEW1")
            self.assertEqual(second.read_bytes(), b"different size")
            self.assertEqual(existing.read_bytes(), b"OLD2")

    def test_missing_api_session_never_starts_kompas(self):
        for name in ("hello_box", "draw_rectangle", "touch_active"):
            with self.subTest(macro=name):
                macro = load_macro(name)
                with patch.object(macro.ksapi, "GetKompas", return_value=None, create=True), patch.object(
                    macro.ksapi, "OpenKompas", create=True
                ) as start:
                    with self.assertRaises(RuntimeError) as error:
                        macro.connect()
                    message = str(error.exception)
                    self.assertIn(f'"{macro.BIN}/kKompas" -APIServer=10500', message)
                    self.assertIn('LD_LIBRARY_PATH=', message)
                    self.assertIn('LC_ALL=', message)
                    self.assertNotIn('.sh', message)
                    self.assertNotIn('-hidden', message)
                    start.assert_not_called()

    def test_existing_api_session_is_reused(self):
        for name in ("hello_box", "draw_rectangle", "touch_active"):
            with self.subTest(macro=name):
                macro = load_macro(name)
                app = Mock()
                with patch.object(macro.ksapi, "GetKompas", return_value=app, create=True), patch.object(
                    macro.ksapi, "OpenKompas", create=True
                ) as start:
                    self.assertIs(macro.connect(), app)
                    start.assert_not_called()
                    app.SetVisible.assert_not_called()

    def test_regular_path_is_unchanged(self):
        path = Path("/home/user/model.m3d")
        self.assertEqual(self.touch.ensure_writable(path), path)

    def part(self):
        part = Mock()
        part.GetMass.return_value = 1.0
        part.GetName.return_value = "test"
        part.GetMaterial.return_value = "steel"
        return part

    def test_missing_variable_stops_before_point_creation(self):
        part = self.part()
        part.AddVariable.return_value = None
        with self.assertRaisesRegex(RuntimeError, "macro_touched"):
            self.touch.touch_part(part)
        part.GetModelContainer.assert_not_called()

    def test_failed_point_update_stops_before_rebuild(self):
        part = self.part()
        point = part.GetModelContainer.return_value.GetPoints3D.return_value.Add.return_value
        point.Update.return_value = False
        with self.assertRaisesRegex(RuntimeError, "macro_point"):
            self.touch.touch_part(part)
        part.RebuildModel.assert_not_called()

    def test_failed_rebuild_is_not_success(self):
        part = self.part()
        part.RebuildModel.return_value = False
        with self.assertRaisesRegex(RuntimeError, "перестроить"):
            self.touch.touch_part(part)

    def test_failed_circle_update_is_not_success(self):
        doc = Mock()
        view = doc.GetViewsAndLayersManager.return_value.GetViews.return_value.GetActiveView.return_value
        view.GetCircles.return_value.Add.return_value.Update.return_value = False
        with self.assertRaisesRegex(RuntimeError, "окружность"):
            self.touch.touch_drawing(doc)

    def test_failed_line_update_is_not_success(self):
        container = Mock()
        container.GetLineSegments.return_value.Add.return_value.Update.return_value = False
        with self.assertRaisesRegex(RuntimeError, "отрезок"):
            self.draw.add_line(container, 0, 0, 1, 1)

    def test_failed_rectangle_update_never_reports_completion(self):
        app = Mock()
        doc = app.GetDocuments.return_value.AddWithDefaultSettings.return_value
        view = doc.GetViewsAndLayersManager.return_value.GetViews.return_value.GetActiveView.return_value
        view.GetRectangles.return_value.Add.return_value.Update.return_value = False
        with patch.object(self.draw, "connect", return_value=app):
            with self.assertRaisesRegex(RuntimeError, "прямоугольник"):
                self.draw.main()
        app.ShowMessageBox.assert_not_called()
        view.GetLineSegments.assert_not_called()


if __name__ == "__main__":
    unittest.main()
