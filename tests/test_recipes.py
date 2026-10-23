"""Offline recipe tests: native module is replaced; no CAD document is opened."""
import ast
import importlib.util
import re
import shutil
import subprocess
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from skill_paths import SKILL_DIR


def load_recipe(name="01_plate"):
    spec = importlib.util.spec_from_file_location(
        name, SKILL_DIR / "examples" / f"{name}.py"
    )
    recipe = importlib.util.module_from_spec(spec)
    api = ModuleType("ksapi")
    api.GetKompas = Mock(return_value=None)
    api.IKompasDocument3D = lambda doc: doc
    api.IDrawingContainer = lambda view: view
    api.IFeature = lambda obj: obj
    api.IFace = lambda obj: obj
    constants = ModuleType("constants")
    constants.constants = SimpleNamespace(
        ksDocumentPart=4, kdDoNotSaveChanges=0, ksOperTree=1,
        ksCMEditUndo=57643, ksCMEditRedo=57644,
    )
    constants3d = ModuleType("constants3d")
    constants3d.constants = SimpleNamespace(
        o3d_planeXOY=1, o3d_bossExtrusion=2, o3d_cutExtrusion=3, dtNormal=4, dtReverse=7, etBlind=5, o3d_face=6,
    )
    with patch.dict(sys.modules, {"ksapi": api, "constants": constants, "constants3d": constants3d}):
        spec.loader.exec_module(recipe)
    return recipe


class SkillIntegrityTests(unittest.TestCase):
    def test_installable_skill_excludes_repository_development_files(self):
        self.assertTrue((SKILL_DIR / "SKILL.md").is_file())
        self.assertFalse((SKILL_DIR.parent.parent / "SKILL.md").exists())
        self.assertFalse(list(SKILL_DIR.rglob("test_*.py")))
        for name in ("tests", ".git", ".vscode", "INSIGHTS.md"):
            self.assertFalse((SKILL_DIR / name).exists(), name)
        metadata = (SKILL_DIR / "SKILL.md").read_text().split("---", 2)[1]
        fields = dict(line.split(": ", 1) for line in metadata.strip().splitlines())
        self.assertEqual(fields["name"], SKILL_DIR.name)
        self.assertRegex(fields["name"], r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
        self.assertLessEqual(len(fields["name"]), 64)
        self.assertTrue(0 < len(fields["description"]) <= 1024)
        self.assertTrue(0 < len(fields["compatibility"]) <= 500)

    def test_examples_import_only_stdlib_and_native_sdk(self):
        root = SKILL_DIR
        allowed = sys.stdlib_module_names | {"ksapi", "constants", "constants3d"}
        for path in (root / "examples").glob("*.py"):
            with self.subTest(path=path.name):
                tree = ast.parse(path.read_text(), filename=str(path))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        modules = [alias.name.split(".")[0] for alias in node.names]
                    elif isinstance(node, ast.ImportFrom):
                        self.assertEqual(node.level, 0)
                        modules = [(node.module or "").split(".")[0]]
                    else:
                        continue
                    self.assertFalse(set(modules) - allowed, modules)

    def test_skill_docs_have_local_links_and_no_project_dependencies(self):
        root = SKILL_DIR
        for path in (root / "SKILL.md", *(root / "references").glob("*.md")):
            text = path.read_text()
            with self.subTest(path=path.name):
                match = re.search(r"(?i)riki-tiki|grinder|jura|/home/dante|overhead_deck|adjustment_dial|motor_pinion_18", text)
                self.assertIsNone(match, match.group() if match else "")
                for target in re.findall(r"\]\(([^)]+)\)", text):
                    if "://" not in target and not target.startswith("#"):
                        self.assertTrue((path.parent / target.split("#")[0]).is_file(), target)

    def test_copied_examples_and_tests_work_without_original_project(self):
        root = SKILL_DIR
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / "standalone repository"
            skill = copied / "skills" / root.name
            shutil.copytree(root / "examples", skill / "examples", ignore=shutil.ignore_patterns("__pycache__"))
            tests = copied / "tests"
            tests.mkdir()
            shutil.copyfile(Path(__file__), tests / "test_recipes.py")
            shutil.copyfile(Path(__file__).with_name("skill_paths.py"), tests / "skill_paths.py")
            result = subprocess.run(
                [sys.executable, "-m", "unittest", "discover", "-s", str(tests),
                 "-p", "test_recipes.py", "-k", "IncrementalTests"],
                cwd=directory, capture_output=True, text=True, timeout=10,
            )
            # Incremental suite only; integrity tests need the complete docs tree.
            self.assertEqual(result.returncode, 0, result.stderr)


class DocumentLifecycleTests(unittest.TestCase):
    def test_owned_documents_close_in_reverse_order_once(self):
        recipe = load_recipe("10_assembly")
        order = []
        first = Mock()
        second = Mock()
        first.Close.side_effect = lambda mode: order.append("first") or True
        second.Close.side_effect = lambda mode: order.append("second") or True
        owned = [first, second]
        recipe.close_owned(owned)
        recipe.close_owned(owned)
        self.assertEqual(order, ["second", "first"])
        self.assertEqual(owned, [])

    def test_failed_close_consumes_handle_and_stops_cleanup(self):
        recipe = load_recipe("10_assembly")
        for outcome in (False, ConnectionError("lost Close response")):
            with self.subTest(outcome=outcome):
                first = Mock()
                second = Mock()
                if isinstance(outcome, Exception):
                    second.Close.side_effect = outcome
                else:
                    second.Close.return_value = outcome
                owned = [first, second]
                with self.assertRaises((RuntimeError, ConnectionError)):
                    recipe.close_owned(owned)
                second.Close.assert_called_once()
                first.Close.assert_not_called()
                self.assertEqual(owned, [first])

    def test_documented_close_helper_matches_executable_example(self):
        recipe = load_recipe("10_assembly")
        text = (SKILL_DIR / "SKILL.md").read_text()
        snippet = next(code for code in re.findall(r"```python\n(.*?)\n```", text, re.DOTALL)
                       if code.startswith("def close_owned("))
        namespace = {"ksapi": SimpleNamespace(IKompasDocument=object),
                     "c": recipe.c, "require": recipe.require}
        exec(compile(snippet, "SKILL.md:close_owned", "exec"), namespace)
        doc = Mock()
        doc.Close.return_value = False
        owned = [doc]
        with self.assertRaises(RuntimeError):
            namespace["close_owned"](owned)
        namespace["close_owned"](owned)
        doc.Close.assert_called_once()

    def test_native_hole_reopen_failure_does_not_close_stale_handle(self):
        for outcome in (False, ConnectionError("lost Close response"), "reopen failed"):
            with self.subTest(outcome=outcome):
                recipe = load_recipe("13_native_hole")
                app = Mock()
                documents = app.GetDocuments.return_value
                doc = documents.AddWithDefaultSettings.return_value
                doc.SaveAs.side_effect = lambda path: Path(path).write_bytes(b"saved fixture") > 0
                if outcome == "reopen failed":
                    documents.Open.side_effect = ValueError(outcome)
                    expected = ValueError
                elif isinstance(outcome, Exception):
                    doc.Close.side_effect = outcome
                    expected = ConnectionError
                else:
                    doc.Close.return_value = outcome
                    expected = RuntimeError
                with patch.object(recipe.ksapi, "GetKompas", return_value=app), \
                        patch.object(recipe, "build"), patch.object(recipe, "validate"), \
                        self.assertRaises(expected):
                    recipe.main([])
                doc.Close.assert_called_once()
                app.GetActiveDocument.return_value.SetActive.assert_not_called()
                if outcome != "reopen failed":
                    documents.Open.assert_not_called()

    def test_native_hole_final_close_failure_does_not_switch_documents(self):
        recipe = load_recipe("13_native_hole")
        app = Mock()
        documents = app.GetDocuments.return_value
        doc = documents.AddWithDefaultSettings.return_value
        doc.SaveAs.side_effect = lambda path: Path(path).write_bytes(b"saved fixture") > 0
        documents.Open.return_value.Close.side_effect = ConnectionError("final Close")
        with patch.object(recipe.ksapi, "GetKompas", return_value=app), \
                patch.object(recipe, "build"), patch.object(recipe, "validate"), \
                self.assertRaisesRegex(ConnectionError, "final Close"):
            recipe.main([])
        doc.Close.assert_called_once()
        documents.Open.return_value.Close.assert_called_once()
        app.GetActiveDocument.return_value.SetActive.assert_not_called()

    def test_native_hole_success_closes_old_and_new_handles_once(self):
        recipe = load_recipe("13_native_hole")
        app = Mock()
        documents = app.GetDocuments.return_value
        doc = documents.AddWithDefaultSettings.return_value
        reopened = documents.Open.return_value
        doc.SaveAs.side_effect = lambda path: Path(path).write_bytes(b"saved fixture") > 0
        with patch.object(recipe.ksapi, "GetKompas", return_value=app), \
                patch.object(recipe, "build"), patch.object(recipe, "validate"):
            recipe.main([])
        doc.Close.assert_called_once()
        reopened.Close.assert_called_once()
        app.GetActiveDocument.return_value.SetActive.assert_called_once()


class IncrementalTests(unittest.TestCase):
    def setUp(self):
        self.recipe = load_recipe("incremental_edit")
        self.doc = Mock()
        self.doc.reference = 17
        self.doc.IsUndoContainer.return_value = False
        self.doc.IsEnableUndo.return_value = True
        self.doc.SetUndoContainer.side_effect = lambda value: setattr(
            self.doc.IsUndoContainer, "return_value", value
        )
        self.app = Mock()
        self.app.GetActiveDocument.return_value = self.doc

    def test_group_closes_on_exception_without_implicit_rollback(self):
        with self.assertRaisesRegex(ValueError, "edit"):
            with self.recipe.undo_group(self.doc):
                self.assertTrue(self.doc.IsUndoContainer())
                raise ValueError("edit")
        self.assertEqual([call.args for call in self.doc.SetUndoContainer.call_args_list],
                         [(True,), (False,)])
        self.doc.GetDocumentFrame.assert_not_called()
        self.doc.SetEnableUndo.assert_not_called()
        self.doc.ClearUndo.assert_not_called()

    def test_empty_group_does_not_dispatch_undo(self):
        with self.recipe.undo_group(self.doc):
            pass
        self.doc.GetDocumentFrame.assert_not_called()
        self.assertFalse(self.doc.IsUndoContainer())

    def test_reject_disabled_history_and_nested_group_without_mutation(self):
        for enabled, grouped in ((False, False), (True, True)):
            self.doc.IsEnableUndo.return_value = enabled
            self.doc.IsUndoContainer.return_value = grouped
            with self.subTest(enabled=enabled, grouped=grouped), self.assertRaises(RuntimeError):
                with self.recipe.undo_group(self.doc):
                    self.fail("must not enter")
            self.doc.SetUndoContainer.assert_not_called()

    def test_group_checks_none_returning_setter_state(self):
        self.doc.SetUndoContainer.side_effect = None
        self.doc.SetUndoContainer.return_value = None
        with self.assertRaisesRegex(RuntimeError, "не открылась"):
            with self.recipe.undo_group(self.doc):
                self.fail("must not enter")
        self.assertEqual(self.doc.SetUndoContainer.call_count, 2)

    def test_history_dispatches_synchronously_to_confirmed_target_frame(self):
        command = self.recipe.c.ksCMEditUndo
        self.recipe.history_command(self.app, self.doc, command)
        self.doc.SetActive.assert_called_once()
        self.doc.GetDocumentFrame.return_value.ExecuteKompasCommand.assert_called_once_with(command, False)

    def test_history_rejects_other_commands_and_open_group(self):
        for command, grouped in ((123, False), (self.recipe.c.ksCMEditUndo, True)):
            self.doc.IsUndoContainer.return_value = grouped
            with self.subTest(command=command), self.assertRaises(RuntimeError):
                self.recipe.history_command(self.app, self.doc, command)
            self.doc.SetActive.assert_not_called()
            self.doc.GetDocumentFrame.assert_not_called()

    def test_history_rejects_wrong_active_document_inactive_frame_and_disabled_command(self):
        frame = self.doc.GetDocumentFrame.return_value
        for failure in ("document", "frame", "disabled"):
            self.app.GetActiveDocument.return_value = (
                SimpleNamespace(reference=99) if failure == "document" else self.doc
            )
            frame.IsActive.return_value = failure != "frame"
            frame.IsKompasCommandEnable.return_value = failure != "disabled"
            with self.subTest(failure=failure), self.assertRaises(RuntimeError):
                self.recipe.history_command(self.app, self.doc, self.recipe.c.ksCMEditUndo)
            frame.ExecuteKompasCommand.assert_not_called()

    def test_failed_dispatch_is_not_retried(self):
        frame = self.doc.GetDocumentFrame.return_value
        frame.ExecuteKompasCommand.return_value = False
        with self.assertRaisesRegex(RuntimeError, "не повторять"):
            self.recipe.history_command(self.app, self.doc, self.recipe.c.ksCMEditUndo)
        self.assertEqual(frame.ExecuteKompasCommand.call_count, 1)

    def test_depth_edit_re_resolves_without_replacing_feature_or_profile(self):
        extrusions = self.doc.GetTopPart.return_value.GetModelContainer.return_value.GetExtrusions.return_value
        extrusions.GetCount.return_value = 1
        op = extrusions.GetExtrusion.return_value
        op.GetExtrusionType.return_value = self.recipe.c3d.etBlind
        op.GetDepth.side_effect = (15., 20.)
        self.recipe.change_depth(self.doc, 15.)
        self.recipe.change_depth(self.doc, 20.)
        self.assertEqual(extrusions.GetExtrusion.call_count, 2)
        self.assertEqual([call.args for call in op.SetDepth.call_args_list], [(True, 15.), (True, 20.)])
        extrusions.Add.assert_not_called()
        op.SetProfiles.assert_not_called()
        op.SetSideParameters.assert_not_called()

    def test_failed_edit_never_triggers_automatic_history_command(self):
        extrusions = self.doc.GetTopPart.return_value.GetModelContainer.return_value.GetExtrusions.return_value
        extrusions.GetCount.return_value = 1
        op = extrusions.GetExtrusion.return_value
        op.GetExtrusionType.return_value = self.recipe.c3d.etBlind
        op.Update.return_value = False
        with self.assertRaisesRegex(RuntimeError, "автоматической отмены нет"):
            self.recipe.change_depth(self.doc, 15.)
        self.doc.GetDocumentFrame.assert_not_called()
        op.GetDepth.assert_not_called()

    def test_invalid_depth_does_not_query_cad(self):
        for depth in (0., -1., float("nan"), float("inf")):
            with self.subTest(depth=depth), self.assertRaises(RuntimeError):
                self.recipe.change_depth(self.doc, depth)
        self.doc.GetTopPart.assert_not_called()

    def test_snapshot_checks_actual_solid_full_tree_and_geometry(self):
        part = self.doc.GetTopPart.return_value
        body = Mock()
        part.GetResultBodies.return_value = [body]
        body.GetGabarit.return_value = (True, 0., 0., 0., 20., 10., 15.)
        part.reference = 1
        part.GetObjectError.return_value = 0
        child = Mock()
        child.reference = 2
        child.GetObjectError.return_value = 0
        part.GetSubFeatures.return_value = [child, None]
        child.GetSubFeatures.return_value = [part]
        self.recipe.check_height(self.doc, 15.)
        child.GetSubFeatures.assert_called_once_with(self.recipe.c.ksOperTree, True, True)
        with self.assertRaisesRegex(RuntimeError, "Геометрия"):
            self.recipe.check_height(self.doc, 20.)
        child.GetObjectError.return_value = 54
        with self.assertRaisesRegex(RuntimeError, "Ошибка дерева"):
            self.recipe.snapshot(self.doc)

    def test_failure_closes_only_owned_scratch_and_restores_previous(self):
        previous = self.app.GetActiveDocument.return_value
        scratch = self.app.GetDocuments.return_value.AddWithDefaultSettings.return_value
        with patch.object(self.recipe.ksapi, "GetKompas", return_value=self.app), \
                patch.object(self.recipe, "make_extrusion", side_effect=ValueError("setup")):
            with self.assertRaisesRegex(ValueError, "setup"):
                self.recipe.main()
        scratch.Close.assert_called_once_with(self.recipe.c.kdDoNotSaveChanges)
        previous.SetActive.assert_called_once()
        previous.Close.assert_not_called()

    def test_main_undo_redo_and_empty_group_without_saving(self):
        scratch = self.app.GetDocuments.return_value.AddWithDefaultSettings.return_value
        scratch.IsEnableUndo.return_value = True
        scratch.IsUndoContainer.side_effect = (False, True, False, False, True, False)
        baseline, changed = (0, 0, 0, 20, 10, 10), (0, 0, 0, 20, 10, 20)
        with patch.object(self.recipe.ksapi, "GetKompas", return_value=self.app), \
                patch.object(self.recipe, "make_extrusion"), \
                patch.object(self.recipe, "change_depth") as change, \
                patch.object(self.recipe, "check_height", side_effect=(baseline, changed, baseline, changed, changed)), \
                patch.object(self.recipe, "history_command") as history:
            self.recipe.main()
        self.assertEqual([call.args for call in change.call_args_list], [(scratch, 15.), (scratch, 20.)])
        self.assertEqual([call.args[2] for call in history.call_args_list],
                         [self.recipe.c.ksCMEditUndo, self.recipe.c.ksCMEditRedo])
        scratch.Save.assert_not_called()
        scratch.SaveAs.assert_not_called()
        scratch.Close.assert_called_once()


class GeometricSelectionTests(unittest.TestCase):
    def setUp(self):
        self.recipe = load_recipe("geometric_selection")
        self.recipe.ksapi.IEdge = lambda obj: obj
        self.recipe.c3d.o3d_edge = 7
        self.recipe.c3d.o3d_axisOZ = 73
        self.body = Mock(reference=10)
        self.part = Mock()
        self.part.GetResultBodies.return_value = [self.body]
        self.options = {"length_tol": 1e-5, "angle_tol": 1e-7}

    def geometry(self, origin, axis, radius=5):
        obj = Mock()
        placement = obj.GetPlacement.return_value
        placement.GetOrigin.return_value = (True, *origin)
        placement.GetVector.return_value = (True, *axis)
        obj.GetCentre.return_value = (True, *origin)
        obj.GetRadius.return_value = radius
        return obj

    def face(self, origin=(0, 0, 10), axis=(0, 0, 1), *, planar=True, radius=5):
        face = Mock()
        face.GetBody.return_value = self.body
        face.IsPlanar.return_value = planar
        face.IsCylinder.return_value = not planar
        face.GetMathSurface.return_value = self.geometry(origin, axis, radius)
        face.GetRadius.return_value = radius
        return face

    def edge(self, center=(0, 0, 10), axis=(0, 0, 1), *, radius=5):
        edge = Mock()
        edge.GetBody.return_value = self.body
        edge.IsCircle.return_value = True
        edge.GetMathCurve.return_value = self.geometry(center, axis, radius)
        return edge

    def test_plane_uses_distance_normal_and_body_not_index(self):
        wanted = self.face(axis=(0, 0, -2))
        wrong_normal = self.face(axis=(1, 0, 0))
        foreign = self.face()
        foreign.GetBody.return_value = Mock(reference=20)
        self.part.GetModelObjects.return_value = [wrong_normal, foreign, self.face(origin=(0, 0, 0)), wanted]
        self.assertIs(self.recipe.select_plane(self.part, self.body, point=(5, 7, 10),
                                               normal=(0, 0, 3), **self.options), wanted)

    def test_ambiguous_and_missing_report_measured_candidates(self):
        self.part.GetModelObjects.return_value = [self.face(), self.face()]
        with self.assertRaisesRegex(ValueError, '"matches": 2') as error:
            self.recipe.select_plane(self.part, self.body, point=(0, 0, 10), normal=(0, 0, 1), **self.options)
        self.assertIn('"plane_distance"', str(error.exception))
        with self.assertRaisesRegex(ValueError, '"matches": 0'):
            self.recipe.select_plane(self.part, self.body, point=(0, 0, 15), normal=(0, 0, 1), **self.options)

    def test_circle_filters_center_radius_plane_and_rejects_arcs(self):
        wanted = self.edge(axis=(0, 0, -1))
        arc = self.edge()
        arc.IsCircle.return_value = False
        self.part.GetModelObjects.return_value = [arc, self.edge(radius=15), self.edge(center=(1, 0, 10)),
                                                  self.edge(axis=(1, 0, 0)), wanted]
        self.assertIs(self.recipe.select_circle(self.part, self.body, center=(0, 0, 10), radius=5,
                                                normal=(0, 0, 1), **self.options), wanted)
        arc.GetMathCurve.assert_not_called()

    def test_cylinder_axis_line_span_sign_and_radius(self):
        wanted = self.face(origin=(0, 0, 100), planar=False)
        wanted.GetLimitingEdges.return_value = [self.edge(center=(0, 0, 0)), self.edge()]
        self.part.GetModelObjects.return_value = [self.face(planar=False, radius=15),
                                                  self.face(origin=(2, 0, 0), planar=False), wanted]
        self.assertIs(self.recipe.select_cylinder(self.part, self.body, radius=5, axis_point=(0, 0, 20),
                                                  axis=(0, 0, -1), span=(10, 20), **self.options), wanted)
        with self.assertRaisesRegex(ValueError, '"matches": 0'):
            self.recipe.select_cylinder(self.part, self.body, radius=5, axis_point=(0, 0, 0),
                                         axis=(0, 0, 1), span=(0, 9), **self.options)

    def test_cylinder_rejects_unsupported_trim_instead_of_guessing_bbox(self):
        face = self.face(planar=False)
        arc = self.edge()
        arc.IsCircle.return_value = False
        arc.IsStraight.return_value = False
        face.GetLimitingEdges.return_value = [arc]
        self.part.GetModelObjects.return_value = [face]
        with self.assertRaisesRegex(ValueError, "Неподдерживаемая обрезка"):
            self.recipe.select_cylinder(self.part, self.body, radius=5, axis_point=(0, 0, 0),
                                         axis=(0, 0, 1), span=(0, 10), **self.options)

    def test_tilted_cylinder_and_straight_seam_project_to_requested_axis(self):
        s = self.recipe.math.sqrt(0.5)
        axis, origin = (s, 0, s), (10, 20, 30)
        end = tuple(p + 10 * n for p, n in zip(origin, axis))
        face = self.face(origin=origin, axis=axis, planar=False)
        seam = Mock()
        seam.IsCircle.return_value = False
        seam.IsStraight.return_value = True
        seam.GetPoint.side_effect = [(True, origin[0], origin[1] + 5, origin[2]),
                                     (True, end[0], end[1] + 5, end[2])]
        face.GetLimitingEdges.return_value = [self.edge(center=origin, axis=axis),
                                               self.edge(center=end, axis=axis), seam]
        self.part.GetModelObjects.return_value = [face]
        self.assertIs(self.recipe.select_cylinder(self.part, self.body, radius=5, axis_point=origin,
                                                  axis=axis, span=(0, 10), **self.options), face)

    def test_circle_and_cylinder_do_not_choose_first_identical_candidate(self):
        self.part.GetModelObjects.return_value = [self.edge(), self.edge()]
        with self.assertRaisesRegex(ValueError, '\"matches\": 2'):
            self.recipe.select_circle(self.part, self.body, center=(0, 0, 10), radius=5,
                                       normal=(0, 0, 1), **self.options)
        faces = [self.face(planar=False), self.face(planar=False)]
        for face in faces:
            face.GetLimitingEdges.return_value = [self.edge(center=(0, 0, 0)), self.edge()]
        self.part.GetModelObjects.return_value = faces
        with self.assertRaisesRegex(ValueError, '\"matches\": 2'):
            self.recipe.select_cylinder(self.part, self.body, radius=5, axis_point=(0, 0, 0),
                                         axis=(0, 0, 1), span=(0, 10), **self.options)

    def test_bad_status_nonfinite_zero_vector_and_tolerance_rejected(self):
        for result in ((False, 0, 0, 0), (True, float("nan"), 0, 0)):
            with self.assertRaises((RuntimeError, ValueError)):
                self.recipe.output_point(result, "readback")
        for vector in ((0, 0, 0), (float("inf"), 0, 0)):
            with self.assertRaises(ValueError):
                self.recipe.unit(vector)
        for length, angle in ((0, 1e-7), (-1, 1e-7), (1e-5, 0), (1e-5, float("nan"))):
            with self.assertRaises(ValueError):
                self.recipe.tolerances(length, angle)
        self.part.GetResultBodies.return_value = [Mock(reference=20)]
        with self.assertRaisesRegex(RuntimeError, "Тело не в текущем результате"):
            self.recipe.select_plane(self.part, self.body, point=(0, 0, 10), normal=(0, 0, 1), **self.options)

    def test_failure_closes_only_owned_document_and_restores_previous(self):
        app = Mock()
        with patch.object(self.recipe.ksapi, "GetKompas", return_value=app), \
                patch.object(self.recipe, "build", side_effect=ValueError("probe")):
            with self.assertRaisesRegex(ValueError, "probe"):
                self.recipe.main()
        app.GetDocuments.return_value.AddWithDefaultSettings.return_value.Close.assert_called_once_with(
            self.recipe.c.kdDoNotSaveChanges)
        previous = app.GetActiveDocument.return_value
        previous.SetActive.assert_called_once()
        previous.Close.assert_not_called()


if __name__ == "__main__":
    unittest.main()
