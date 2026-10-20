"""Offline checks for the standalone gallery; never imports native KsAPI."""
import ast
import math
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import Mock

from test_recipes import load_recipe

from skill_paths import SKILL_DIR

ROOT = SKILL_DIR
EXAMPLES = ROOT / "examples"
RUNNER = Path(__file__).resolve().parents[1] / "tools" / "run_examples.py"
NAMES = ["01_plate", "02_ring", "03_holes", "04_revolve", "05_offset_plane",
         "06_loft", "07_body_pattern", "08_boolean", "09_reposition", "10_assembly",
         "11_fillet_edit", "12_chamfer", "13_native_hole", "14_shell", "15_linear_pattern"]


class GalleryTests(unittest.TestCase):
    def test_examples_are_standalone_scripts(self):
        for name in NAMES:
            with self.subTest(name=name):
                source = (EXAMPLES / f"{name}.py").read_text()
                tree = ast.parse(source)
                self.assertIn('# dependencies = []', source)
                self.assertIn('if __name__ == "__main__":', source)
                calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
                self.assertTrue(any(isinstance(n.func, ast.Attribute) and n.func.attr == "GetKompas"
                                    for n in calls))
                self.assertFalse(any(isinstance(n.func, ast.Attribute) and n.func.attr == "OpenKompas"
                                     for n in calls))
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom):
                        self.assertNotIn(node.module, ("basic_part", "incremental_edit"))
                        self.assertEqual(node.level, 0)
                self.assertIn("finally:", source)
                self.assertIn("kdDoNotSaveChanges", source)
                self.assertIn("GetObjectError", source)
                self.assertIn("GetGabarit", source)
                self.assertIn("IsSolid", source)
                functions = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
                self.assertIn("validate", functions)
                if name != "10_assembly":
                    self.assertIn("build", functions)

    def test_runner_has_syntax_and_only_known_local_import_targets(self):
        source = RUNNER.read_text()
        ast.parse(source)
        for name in NAMES:
            self.assertIn(f'"{name}"', source)
        self.assertIn("SaveAsToRasterFormat", source)
        self.assertIn("Image.open", source)
        self.assertIn("document_ids(app) == initial", source)
        self.assertNotIn("OpenKompas", source)

    def test_runner_resolves_packaged_examples_from_its_own_location(self):
        tree = ast.parse(RUNNER.read_text())
        assignment = next(node for node in tree.body if isinstance(node, ast.Assign)
                          and any(isinstance(target, ast.Name) and target.id == "EXAMPLES"
                                  for target in node.targets))
        namespace = {"Path": Path, "__file__": str(RUNNER)}
        exec(compile(ast.Module(body=[assignment], type_ignores=[]),
                     str(RUNNER), "exec"), namespace)
        self.assertEqual(namespace["EXAMPLES"], EXAMPLES)

    def test_skill_contains_only_the_shared_macro_runner(self):
        self.assertEqual(list(ROOT.rglob("*.sh")), [ROOT / "scripts/run.sh"])
        self.assertFalse((ROOT / "scripts/run_examples.py").exists())

    def test_gallery_local_links_exist(self):
        text = (ROOT / "references/recipes.md").read_text()
        for name in NAMES:
            self.assertIn(f"../examples/{name}.py", text)
            self.assertIn(f"../examples/{name}.jpg", text)
            path = EXAMPLES / f"{name}.jpg"
            self.assertTrue(path.is_file(), path)
            self.assertGreater(path.stat().st_size, 1000)
        for url in re.findall(r'\]\(([^)]+)\)', text):
            if "://" not in url and not url.startswith("#"):
                self.assertTrue((ROOT / "references" / url.split("#")[0]).exists(), url)


class RasterSafetyTests(unittest.TestCase):
    def setUp(self):
        # Compile only the pure Python capture helper; no native imports or CAD.
        tree = ast.parse(RUNNER.read_text())
        function = next(node for node in tree.body
                        if isinstance(node, ast.FunctionDef) and node.name == "capture")
        self.namespace = {"Path": Path, "math": math, "ksapi": Mock(),
                          "c": Mock(), "c3d": Mock()}
        self.namespace["c3d"].ksVPIsometric = 5
        self.namespace["require"] = load_recipe().require
        exec(compile(ast.Module(body=[function], type_ignores=[]),
                     "capture-under-test", "exec"), self.namespace)
        self.capture = self.namespace["capture"]

    def test_existing_raster_and_dangling_symlink_fail_before_cad(self):
        with tempfile.TemporaryDirectory() as directory:
            for symlink in (False, True):
                with self.subTest(symlink=symlink):
                    target = Path(directory) / ("link.jpg" if symlink else "existing.jpg")
                    if symlink:
                        target.symlink_to(Path(directory) / "absent.jpg")
                    else:
                        target.write_bytes(b"keep original")
                    doc = Mock()
                    with self.assertRaises(FileExistsError):
                        self.capture(doc, target)
                    doc.SetActive.assert_not_called()
                    doc.SaveAsToRasterFormat.assert_not_called()
                    if not symlink:
                        self.assertEqual(target.read_bytes(), b"keep original")

    def test_collision_during_view_preparation_fails_before_export(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "preview.jpg"
            doc = Mock()
            manager = self.namespace["ksapi"].IKompasDocument3D.return_value.GetViewProjectionManager.return_value
            manager.GetCount.return_value = 1
            manager.GetViewProjection.return_value.GetViewProjectonType.return_value = 5
            parameters = self.namespace["ksapi"].IRasterConvertParameters.return_value
            parameters.CalcRasterScale.side_effect = lambda *_: target.write_bytes(b"another writer")
            with self.assertRaisesRegex(FileExistsError, "занят"):
                self.capture(doc, target)
            doc.SaveAsToRasterFormat.assert_not_called()
            self.assertEqual(target.read_bytes(), b"another writer")

    def test_volume_rejects_wrong_units_before_calculation(self):
        tree = ast.parse(RUNNER.read_text())
        function = next(node for node in tree.body
                        if isinstance(node, ast.FunctionDef) and node.name == "verified_volume")
        exec(compile(ast.Module(body=[function], type_ignores=[]),
                     "volume-under-test", "exec"), self.namespace)
        self.namespace["c"].ksLUnMM = 1
        inertia = self.namespace["ksapi"].IMassInertiaParam.return_value
        inertia.GetLengthUnits.return_value = 0
        with self.assertRaisesRegex(RuntimeError, "единицы"):
            self.namespace["verified_volume"](Mock())
        inertia.Calculate.assert_not_called()


class FilletEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.recipe = load_recipe("11_fillet_edit")

    def faces(self, radius=5, shift=0, count=4, area_scale=1):
        faces = []
        for sx, sy in ((-1, -1), (-1, 1), (1, -1), (1, 1))[:count]:
            xs = sorted((sx * 30 + shift, sx * (30 - radius) + shift))
            ys = sorted((sy * 20, sy * (20 - radius)))
            face = Mock()
            face.IsCylinder.return_value = True
            face.GetRadius.return_value = radius
            face.GetArea.return_value = self.recipe.math.pi * radius * 10 / 2 * area_scale
            face.GetMathSurface.return_value.GetGabarit.return_value = (
                True, xs[0], ys[0], 0, xs[1], ys[1], 10)
            faces.append(face)
        return faces

    def part(self, **kwargs):
        part = Mock()
        part.GetModelObjects.return_value = self.faces(**kwargs)
        self.recipe.c.ksLUnMM = 1
        return part

    def test_correct_surfaces_pass_without_calculating_intermediate_mass(self):
        self.recipe.verify_rounds(self.part(), 5)
        self.assertFalse(hasattr(self.recipe.ksapi, "IMassInertiaParam"))

    def test_wrong_radius_missing_faces_shift_and_area_cannot_pass(self):
        for data in ({"radius": 3}, {"count": 3}, {"shift": 1}, {"area_scale": 2}):
            with self.subTest(data=data), self.assertRaises(RuntimeError):
                self.recipe.verify_rounds(self.part(**data), 5)

    def test_corner_selection_uses_both_endpoints_not_collection_order(self):
        self.recipe.ksapi.IEdge = lambda obj: obj
        self.recipe.c3d.o3d_edge = 7
        edges = []
        for x, y in ((30, 20), (-30, -20), (-30, 20), (30, -20)):
            edge = Mock()
            edge.IsStraight.return_value = True
            edge.GetPoint.side_effect = lambda start, *_, x=x, y=y: (True, x, y, 0 if start else 10)
            edges.append(edge)
        decoy = Mock()
        decoy.IsStraight.return_value = True
        decoy.GetPoint.side_effect = [(True, 0, 0, 0), (True, 0, 0, 10)]
        part = Mock()
        part.GetModelObjects.return_value = [decoy, *edges]
        self.assertEqual(self.recipe.vertical_corner_edges(part), edges)


class HoleAndGridEvidenceTests(unittest.TestCase):
    @staticmethod
    def cylinder(x, y, radius, zmin, zmax):
        face = Mock()
        face.IsCylinder.return_value = True
        face.GetRadius.return_value = radius
        rims = []
        for z in (zmin, zmax):
            edge = Mock()
            edge.IsCircle.return_value = True
            edge.GetMathCurve.return_value.GetGabarit.return_value = (
                True, x - radius, y - radius, z, x + radius, y + radius, z)
            rims.append(edge)
        face.GetLimitingEdges.return_value = rims
        return face

    def test_blind_hole_wrong_side_same_volume_is_rejected(self):
        recipe = load_recipe("13_native_hole")
        part = Mock()
        part.GetModelObjects.return_value = [self.cylinder(12, 7, 5, 4, 10)]
        recipe.verify_cylindrical_walls(part, [(12, 7, 5, 4, 10)])
        for wall in ((12, 7, 5, 0, 6), (0, 0, 5, 4, 10), (12, 7, 4, 4, 10)):
            part.GetModelObjects.return_value = [self.cylinder(*wall)]
            with self.subTest(wall=wall), self.assertRaises(RuntimeError):
                recipe.verify_cylindrical_walls(part, [(12, 7, 5, 4, 10)])

    def test_grid_same_count_and_volume_wrong_centres_is_rejected(self):
        recipe = load_recipe("15_linear_pattern")
        expected = [(x, y, 2, 0, 10) for x in (-20, 0, 20) for y in (-10, 10)]
        part = Mock()
        part.GetModelObjects.return_value = [self.cylinder(*wall) for wall in expected]
        recipe.verify_cylindrical_walls(part, expected)
        collapsed = [(x, 0, 2, 0, 10) for x in (-25, -15, -5, 5, 15, 25)]
        part.GetModelObjects.return_value = [self.cylinder(*wall) for wall in collapsed]
        with self.assertRaises(RuntimeError):
            recipe.verify_cylindrical_walls(part, expected)


if __name__ == "__main__":
    unittest.main()
