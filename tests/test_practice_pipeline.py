"""Offline contracts for the real CAD optimization pilot."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / "tools/practice_pipeline.py"
spec = importlib.util.spec_from_file_location("practice_pipeline", PATH)
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)


class PipelineTests(unittest.TestCase):
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
                      dimensional_intent_checked=True, origin_checked=True)
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

    def test_review_requires_exact_teacher(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory, review, attempt = self.fixture(root)
            review["teacher_model"] = "auto"
            pipeline.write_json(directory / "teacher-review.json", review)
            with self.assertRaisesRegex(ValueError, "teacher_model"):
                pipeline.validated_review(root, attempt)

    def test_pass_requires_visual_dimensional_and_origin_check(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory, review, attempt = self.fixture(root)
            review["visual_checked"] = False
            pipeline.write_json(directory / "teacher-review.json", review)
            with self.assertRaisesRegex(ValueError, "Incomplete review"):
                pipeline.validated_review(root, attempt)

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

    def test_nonfinite_and_out_of_range_scores_rejected(self):
        for score in (float("nan"), float("inf"), -1, 2, True):
            with self.subTest(score=score), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                directory, review, attempt = self.fixture(root)
                review["score"] = score
                pipeline.write_json(directory / "teacher-review.json", review)
                with self.assertRaises(ValueError):
                    pipeline.validated_review(root, attempt)


if __name__ == "__main__":
    unittest.main()
