"""Offline contracts for the real CAD optimization pilot."""
import importlib.util
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / "tools/practice_pipeline.py"
sys.path.insert(0, str(PATH.parent))
spec = importlib.util.spec_from_file_location("practice_pipeline", PATH)
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)


class PipelineTests(unittest.TestCase):
    def test_worker_gets_exact_learned_guidance_even_if_file_tail_truncated(self):
        from skillopt_sleep.memory import set_learned
        text = set_learned("# skill\n" + "long reference\n" * 5000, ["Reusable signed coordinate guidance"])
        prompt = pipeline.worker_prompt(text)
        self.assertIn("- Reusable signed coordinate guidance", prompt)
        self.assertNotIn("long reference", prompt)
        self.assertNotIn("Managed guidance", pipeline.worker_prompt("# no managed block"))

    def test_fast_prompt_contains_entire_snapshot_and_target(self):
        snapshot = "# Compact reusable skill\nNever guess missing dimensions."
        prompt = pipeline.worker_prompt(snapshot, profile="fast")
        self.assertIn(snapshot, prompt)
        self.assertIn("60–120 seconds", prompt)
        self.assertNotIn("Read skill/SKILL.md fully", prompt)
        self.assertIn("read old", prompt)
        self.assertIn("Never start, kill or restart Kompas", prompt)

    def test_fast_attached_inputs_prompt_avoids_duplicate_reads(self):
        prompt = pipeline.worker_prompt("compact skill", profile="fast", attached_inputs=True)
        self.assertIn("task text and drawing are attached", prompt)
        self.assertNotIn("Read input/task.md and input/drawing.jpg", prompt)
        self.assertIn("compact skill", prompt)
        self.assertNotIn("matching ALL dimensions and the indicated origin", prompt)
        self.assertIn("translations and proper rotations are allowed", prompt)
        self.assertIn("Reflections", prompt)
        self.assertIn("no previous solution", prompt)

    def test_visual_prompt_requires_real_image_read_and_fresh_outputs(self):
        prompt = pipeline.worker_prompt("same skill", profile="fast", attached_inputs=True,
                                        visual_self_check=True)
        self.assertIn("draft/model.m3d", prompt)
        self.assertIn("read IMAGE tool", prompt)
        self.assertIn("corrected/model.m3d", prompt)
        self.assertIn("self-check.json", prompt)
        self.assertIn("isometry alone cannot", prompt)
        self.assertIn("NOT teacher evidence", prompt)
        self.assertNotIn("Save your completed part exactly as model.m3d", prompt)
        self.assertNotIn("VISUAL SELF-CHECK", pipeline.worker_prompt("same skill"))

    def test_visual_evidence_needs_successful_image_delivery_not_claim(self):
        import json
        for image, error, outside in ((False, False, False), (True, True, False),
                                      (True, False, True), (True, False, False)):
            with self.subTest(image=image, error=error, outside=outside), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                workspace = root / "workspace"
                workspace.mkdir()
                preview = root / "outside.jpg" if outside else workspace / "preview.jpg"
                preview.write_bytes(b"pixels")
                pipeline.write_json(workspace / "self-check.json", {
                    "status": "matched", "final_preview": str(preview)})
                trace = root / "trace.jsonl"
                events = [
                    {"type": "tool_execution_start", "toolCallId": "read1", "toolName": "read",
                     "args": {"path": str(preview)}},
                    {"type": "tool_execution_end", "toolCallId": "read1", "isError": error,
                     "result": {"content": [{"type": "image", "data": "encoded"}] if image else
                                            [{"type": "text", "text": "I viewed it"}]}}]
                trace.write_text("\n".join(json.dumps(event) for event in events))
                result = pipeline.visual_self_check_evidence(workspace, trace)
                self.assertEqual(result["final_preview_pixels_delivered"], image and not error and not outside)
                self.assertEqual(result["worker_claim"]["status"], "matched")

    def test_prepared_candidate_resumes_without_reflection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pipeline.write_json(root / "run.json", {"state": "candidate_prepared"})
            (root / "candidate-skill.md").write_text("prepared skill")
            with patch.object(pipeline, "execute_attempt") as execute, patch.object(pipeline, "reflect") as reflect:
                pipeline.advance(root)
            reflect.assert_not_called()
            self.assertEqual(execute.call_args.args[2:], ("candidate", "prepared skill"))

    def test_correctness_first_efficiency_gate(self):
        def attempt(passed, seconds=100, tokens=1000):
            return {"hard": int(passed), "worker_seconds": seconds, "worker_usage": {"totalTokens": tokens}}
        cases = [(attempt(False), attempt(False, 1, 1), False, "candidate_incorrect"),
                 (attempt(False), attempt(True, 1000, 10000), True, "correctness_fixed"),
                 (attempt(True), attempt(False, 1, 1), False, "candidate_incorrect"),
                 (attempt(True), attempt(True, 90, 1000), True, "pareto_improvement"),
                 (attempt(True), attempt(True, 100, 900), True, "pareto_improvement"),
                 (attempt(True), attempt(True, 90, 1100), False, "no_pareto_improvement"),
                 (attempt(True), attempt(True), False, "no_pareto_improvement"),
                 (attempt(True), attempt(True, 90, None), False, "missing_efficiency_measurements")]
        for baseline, candidate, improved, reason in cases:
            with self.subTest(reason=reason, candidate=candidate):
                gate = pipeline.efficiency_gate(baseline, candidate)
                self.assertEqual(gate["improved"], improved)
                self.assertEqual(gate["reason"], reason)

    def test_redaction(self):
        key = "sk-abcdefghijklmnopqrstuvwxyz123456"
        self.assertNotIn(key, pipeline.redact(f"message {key}"))
        self.assertNotIn("private-value", pipeline.redact("private-value", ["private-value"]))

    def fixture(self, root):
        directory = root / "baseline"
        (directory / "verification").mkdir(parents=True)
        pipeline.write_json(directory / "verification/verification.json", {
            "status": "passed", "geometry_passed": True, "native_tree_passed": True,
            "sketches_fully_defined": True})
        (directory / "verification/model.jpg").write_bytes(b"test image")
        evidence_hash = pipeline.sha256(directory / "verification/verification.json")
        (directory / "workspace").mkdir()
        model = directory / "workspace/model.m3d"
        code = directory / "workspace/solution.py"
        model.write_bytes(b"test model")
        code.write_text("# test code\n")
        preview = directory / "verification/model.jpg"
        request = {"image_sha256": {str(preview): pipeline.sha256(preview)},
                   "teacher_model": pipeline.TEACHER,
                   "verification_sha256": evidence_hash, "model_sha256": pipeline.sha256(model),
                   "code_sha256": pipeline.sha256(code)}
        pipeline.write_json(directory / "teacher-request.json", request)
        review = dict(request, status="passed", passed=True, score=1, visual_checked=True,
                      dimensional_intent_checked=True)
        pipeline.write_json(directory / "teacher-review.json", review)
        return directory, review, {"directory": "baseline", "worker_exit_code": 0}

    def test_review_request_binds_report_camera_image(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory, _, attempt = self.fixture(root)
            preview = directory / "preview-iso90/model.jpg"
            preview.parent.mkdir()
            preview.write_bytes(b"upright image")
            attempt.update(id="baseline", report_preview={"path": "preview-iso90/model.jpg"})
            request = pipeline.review_request(root, {"task": "1.1"}, attempt)
            self.assertEqual(request["paths"]["preview"], str(preview))
            self.assertIn(str(preview), request["file_attachments"])
            self.assertEqual(request["image_sha256"][str(preview)], pipeline.sha256(preview))
            self.assertNotIn(str(directory / "verification/model.jpg"), request["image_sha256"])
            self.assertIn("right-handed", request["instructions"])
            self.assertIn("ignore absolute origin placement", request["instructions"])
            self.assertIn("reflection is forbidden", request["instructions"])
            self.assertNotIn("origin_checked(bool)", request["instructions"])
            self.assertEqual(request["placement_policy"], "rigid_motion_allowed_no_reflection")

    def test_review_requires_exact_teacher(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory, review, attempt = self.fixture(root)
            review["teacher_model"] = "auto"
            pipeline.write_json(directory / "teacher-review.json", review)
            with self.assertRaisesRegex(ValueError, "teacher_model"):
                pipeline.validated_review(root, attempt)

    def test_pass_requires_visual_and_dimensional_checks(self):
        for field in ("visual_checked", "dimensional_intent_checked"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                directory, review, attempt = self.fixture(root)
                review[field] = False
                pipeline.write_json(directory / "teacher-review.json", review)
                with self.assertRaisesRegex(ValueError, "Incomplete review"):
                    pipeline.validated_review(root, attempt)

    def test_origin_not_an_acceptance_check(self):
        for origin in (None, False, True):
            with self.subTest(origin=origin), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                directory, review, attempt = self.fixture(root)
                if origin is not None:
                    review["origin_checked"] = origin
                pipeline.write_json(directory / "teacher-review.json", review)
                self.assertTrue(pipeline.validated_review(root, attempt)["passed"])

    def test_pass_requires_successful_verifier_and_saved_preview(self):
        for missing in ("status", "preview", "errors"):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                directory, review, attempt = self.fixture(root)
                if missing == "preview":
                    (directory / "verification/model.jpg").unlink()
                else:
                    evidence_path = directory / "verification/verification.json"
                    evidence = pipeline.read_json(evidence_path)
                    if missing == "status":
                        evidence["status"] = "failed"
                    else:
                        evidence["errors"] = [{"error": "capture failed"}]
                    pipeline.write_json(evidence_path, evidence)
                    request = pipeline.read_json(directory / "teacher-request.json")
                    request["verification_sha256"] = pipeline.sha256(evidence_path)
                    pipeline.write_json(directory / "teacher-request.json", request)
                    review.update(request)
                    pipeline.write_json(directory / "teacher-review.json", review)
                with self.assertRaisesRegex(ValueError, "lacks independent evidence|Images changed"):
                    pipeline.validated_review(root, attempt)

    def test_stale_code_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory, _, attempt = self.fixture(root)
            (directory / "workspace/solution.py").write_text("# changed\n")
            with self.assertRaisesRegex(ValueError, "Artifacts changed"):
                pipeline.validated_review(root, attempt)

    def test_stale_evidence_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory, _, attempt = self.fixture(root)
            pipeline.write_json(directory / "verification/verification.json", {"status": "changed"})
            with self.assertRaisesRegex(ValueError, "Artifacts changed"):
                pipeline.validated_review(root, attempt)

    def test_valid_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, _, attempt = self.fixture(root)
            self.assertTrue(pipeline.validated_review(root, attempt)["passed"])
            self.assertEqual(attempt["status"], "passed")

    def blocked_review(self, root):
        directory, review, attempt = self.fixture(root)
        review.update(status="blocked", passed=False, score=None, visual_checked=False,
                      origin_checked=False, blockers=["Image pixels unavailable"])
        pipeline.write_json(directory / "teacher-review.json", review)
        return directory, review, attempt

    def test_blocked_review_has_no_training_score(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, _, attempt = self.blocked_review(root)
            attempt.update(score=.65, hard=0)
            pipeline.validated_review(root, attempt)
            self.assertEqual(attempt["status"], "review_blocked")
            self.assertNotIn("score", attempt)
            self.assertNotIn("hard", attempt)

    def test_blocked_review_stops_optimizer_and_gate(self):
        for state in ("baseline_review", "awaiting_reflection", "candidate_review"):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _, _, attempt = self.blocked_review(root)
                attempt["id"] = "baseline"
                pipeline.write_json(root / "run.json", {"state": state, "attempts": [attempt],
                                                       "gate": {"action": "old"}})
                with patch.object(pipeline, "report"), patch.object(pipeline, "reflect") as reflect, \
                        patch.object(pipeline, "execute_attempt") as execute, \
                        patch.object(pipeline, "evaluate_gate") as gate:
                    pipeline.advance(root)
                reflect.assert_not_called()
                execute.assert_not_called()
                gate.assert_not_called()
                data = pipeline.read_json(root / "run.json")
                self.assertEqual(data["state"], "review_blocked")
                self.assertNotIn("gate", data)

    def test_blocked_review_cannot_have_score_or_missing_reason(self):
        for fields in ({"score": .65}, {"blockers": []}, {"passed": True}):
            with self.subTest(fields=fields), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                directory, review, attempt = self.blocked_review(root)
                review.update(fields)
                pipeline.write_json(directory / "teacher-review.json", review)
                with self.assertRaises(ValueError):
                    pipeline.validated_review(root, attempt)

    def test_shape_failure_is_not_overridden_by_ignored_origin(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory, review, attempt = self.fixture(root)
            review.update(status="failed", passed=False, score=.75, origin_checked=False,
                          feedback="Mirrored ledge cannot align by translation and proper rotation")
            pipeline.write_json(directory / "teacher-review.json", review)
            pipeline.validated_review(root, attempt)
            self.assertEqual(attempt["status"], "failed")
            self.assertEqual(attempt["hard"], 0)

    def test_failed_model_remains_a_scored_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory, review, attempt = self.fixture(root)
            review.update(status="failed", passed=False, score=.2, visual_checked=False,
                          feedback="No saved CAD artifact; worker failed")
            pipeline.write_json(directory / "teacher-review.json", review)
            pipeline.validated_review(root, attempt)
            self.assertEqual(attempt["status"], "failed")
            self.assertEqual(attempt["score"], .2)

    def test_review_request_contains_direct_image_attachments(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory, _, attempt = self.fixture(root)
            drawing = root / "task.jpg"
            drawing.write_bytes(b"drawing pixels")
            with patch.object(pipeline, "SOURCE", root / "task.md"):
                request = pipeline.review_request(root, {"task": "1.1"}, dict(attempt, id="baseline"))
            self.assertEqual(request["file_attachments"], [str(drawing), str(directory / "verification/model.jpg")])
            self.assertEqual(request["image_sha256"][str(drawing)], pipeline.sha256(drawing))
            self.assertIn("Task", request["image_transport"])
            self.assertIn("score=null", request["instructions"])

    def test_changed_image_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory, _, attempt = self.fixture(root)
            (directory / "verification/model.jpg").write_bytes(b"other image")
            with self.assertRaisesRegex(ValueError, "Images changed"):
                pipeline.validated_review(root, attempt)

    def test_prepare_review_archives_old_optimizer_and_never_runs_cad(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory, _, attempt = self.fixture(root)
            attempt.update(id="baseline", score=.65, hard=0)
            pipeline.write_json(root / "run.json", {"state": "complete", "attempts": [attempt],
                                                   "gate": {"action": "no_change"}})
            pipeline.write_json(root / "proposal.json", [])
            pipeline.write_json(root / "reflection/pending.json", {"pending": []})
            with patch.object(pipeline, "request_teacher") as teacher, \
                    patch.object(pipeline, "execute_attempt") as execute:
                pipeline.prepare_review(root)
            execute.assert_not_called()
            data = teacher.call_args.args[1]
            self.assertNotIn("gate", data)
            self.assertNotIn("score", data["attempts"][0])
            history = root / data["review_history"][0]
            for name in ("teacher-review.json", "teacher-request.json", "proposal.json",
                         "reflection/pending.json", "run.json"):
                self.assertTrue((history / name).is_file(), name)
            self.assertFalse((directory / "teacher-review.json").exists())

    def test_targeted_regrade_preserves_order_models_and_optimizer_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory, _, attempt = self.fixture(root)
            attempt.update(id="baseline", status="failed", score=.85, hard=0)
            untouched = {"id": "newer", "directory": "newer", "status": "passed", "hard": 1}
            pipeline.write_json(root / "run.json", {"state": "complete", "attempts": [attempt, untouched],
                                                   "teacher_transport": "pi", "gate": {"accepted": False}})
            pipeline.write_json(root / "proposal.json", [])
            before = (directory / "workspace/model.m3d").read_bytes()
            with patch.object(pipeline, "request_teacher") as teacher, \
                    patch.object(pipeline, "validated_review", return_value={"status": "passed"}) as validate, \
                    patch.object(pipeline, "execute_attempt") as execute, patch.object(pipeline, "report"):
                pipeline.prepare_review(root, attempt_id="baseline")
            execute.assert_not_called()
            self.assertEqual(teacher.call_args.args[2]["id"], "baseline")
            validate.assert_called_once()
            data = pipeline.read_json(root / "run.json")
            self.assertEqual([item["id"] for item in data["attempts"]], ["baseline", "newer"])
            self.assertEqual(data["attempts"][1], untouched)
            self.assertEqual(data["state"], "complete")
            self.assertTrue((root / "proposal.json").is_file())
            self.assertEqual((directory / "workspace/model.m3d").read_bytes(), before)
            history = root / data["review_history"][0]
            self.assertTrue((history / "teacher-review.json").is_file())
            self.assertTrue((history / "proposal.json").is_file())

    def test_nonfinite_and_out_of_range_scores_rejected(self):
        for score in (float("nan"), float("inf"), -1, 2, True):
            with self.subTest(score=score), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                directory, review, attempt = self.fixture(root)
                review["score"] = score
                pipeline.write_json(directory / "teacher-review.json", review)
                with self.assertRaises(ValueError):
                    pipeline.validated_review(root, attempt)


class PlacementPolicyTests(unittest.TestCase):
    def test_world_bounds_are_diagnostic_not_a_rotation_or_translation_gate(self):
        import ast
        from unittest.mock import Mock
        source = PATH.with_name("practice_verify.py")
        tree = ast.parse(source.read_text())
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name in {"check", "inspect_geometry"}]
        namespace = {"ksapi": Mock(), "Report": dict, "Any": object}
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), "exec"), namespace)
        for bounds in ([100, 200, 300, 160, 228, 375], [-100, 2, 7, -20, 72, 82]):
            with self.subTest(bounds=bounds):
                namespace["body_bounds"] = lambda _: ([object()], bounds)
                report = {"checks": {}}
                namespace["inspect_geometry"](object(), report)
                self.assertTrue(report["checks"]["one_solid_body"]["passed"])
                self.assertIsNone(report["checks"]["extents_mm"]["passed"])
                self.assertEqual(report["bounds_mm"], bounds)
        namespace["body_bounds"] = lambda _: ([], None)
        report = {"checks": {}}
        namespace["inspect_geometry"](object(), report)
        self.assertFalse(report["checks"]["one_solid_body"]["passed"])


class PreviewSafetyTests(unittest.TestCase):
    def setUp(self):
        import ast
        import math
        from unittest.mock import Mock
        source = PATH.with_name("practice_preview.py")
        tree = ast.parse(source.read_text())
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name in {"require", "new_output", "capture"}]
        self.namespace = {"Path": Path, "math": math, "ksapi": Mock(), "c": Mock(), "c3d": Mock()}
        self.namespace["c3d"].ksVPSZ90AxonometricISO = 4
        self.namespace["c3d"].ksVPIsometric = 5
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), "exec"), self.namespace)
        self.doc = Mock()
        self.manager = self.namespace["ksapi"].IKompasDocument3D.return_value.GetViewProjectionManager.return_value
        self.manager.GetViewProjectionScheme.return_value = 4
        self.manager.GetCount.return_value = 1
        self.manager.GetViewProjection.return_value.GetViewProjectonType.return_value = 5
        self.parameters = self.namespace["ksapi"].IRasterConvertParameters.return_value
        self.parameters.CalcRasterScale.return_value = 1.0

    def test_existing_preview_or_dangling_link_never_touches_cad(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "preview.jpg"
            for symlink in (False, True):
                if symlink:
                    target.unlink()
                    target.symlink_to(Path(temporary) / "missing.jpg")
                else:
                    target.write_bytes(b"preserve")
                with self.assertRaises(FileExistsError):
                    self.namespace["capture"](self.doc, target)
                self.doc.SetActive.assert_not_called()

    def test_failed_scheme_stops_before_any_projection_or_export(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.manager.GetViewProjectionScheme.return_value = 2
            with self.assertRaisesRegex(RuntimeError, "scheme readback"):
                self.namespace["capture"](self.doc, Path(temporary) / "preview.jpg")
            self.manager.GetCount.assert_not_called()
            self.doc.SaveAsToRasterFormat.assert_not_called()
            self.doc.Close.assert_not_called()

    def test_export_writes_only_preview_not_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "preview.jpg"
            self.doc.SaveAsToRasterFormat.side_effect = lambda *_: target.write_bytes(b"\xff\xd8\xffjpeg")
            self.namespace["capture"](self.doc, target)
            self.manager.SetViewProjectionScheme.assert_called_once_with(4)
            self.parameters.CalcRasterScale.assert_called_once_with(self.doc, 960, 720)
            self.doc.Save.assert_not_called()
            self.doc.SaveAs.assert_not_called()
            self.doc.Close.assert_not_called()


if __name__ == "__main__":
    unittest.main()
