"""Offline report tests: concise cells, recorded timings and failure evidence."""
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest
from urllib.parse import unquote

from tools.practice_pipeline_report import _timing, _tokens, render_report


class PracticePipelineReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.corpus = self.root / "PracticeProblems_ALL250_CSWA"
        self.run = self.corpus / "skillopt-runs/run one"
        self.data = {"id": "run one", "task": "1.1", "title": "Деталь | размер\nстрока",
                     "worker_model": "deepseek-flash", "teacher_model": "qgm-6.1-sol(high)",
                     "state": "running", "skill_sha256": "abc123", "started_at": "2026-10-24",
                     "attempts": [{"id": "baseline", "directory": "baseline", "status": "done",
                                   "worker_seconds": 12.5, "verification_seconds": 2.25, "worker_exit_code": 0},
                                  {"id": "candidate", "directory": "candidate", "status": "pending"}]}

    def write(self, path: Path, value: object = "artifact") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else str(value),
                        encoding="utf-8")

    def render(self) -> str:
        self.write(self.run / "run.json", self.data)
        result = render_report(self.root)
        self.assertEqual(result, self.root / "PRACTICE.md")
        return result.read_text(encoding="utf-8")

    def passed_evidence(self) -> tuple[dict, dict]:
        self.data["attempts"][0]["status"] = "passed"
        self.write(self.run / "baseline/verification/model.jpg")
        review = {"passed": True, "score": 0.95, "visual_checked": True, "dimensional_intent_checked": True,
                  "origin_checked": True, "notes": ["подробные замечания"], "feedback": "проверено"}
        verification = {"geometry_passed": True, "native_tree_passed": True, "sketches_fully_defined": True,
                        "status": "passed", "volume_mm3": 120, "warnings": ["нет heldout"],
                        "checks": {"объём": {"passed": True, "actual": 120, "expected": 120}}}
        self.write(self.run / "baseline/teacher-review.json", review)
        self.write(self.run / "baseline/verification/verification.json", verification)
        return review, verification

    def test_distinct_attempts_guard_missing_links_and_escape_cells(self) -> None:
        self.write(self.run / "baseline/workspace/solution.py")
        self.write(self.run / "baseline/trace.jsonl", "")
        self.write(self.corpus / "solutions/old/run.json", {"task": "99.99"})
        text = self.render()
        self.assertIn("| Задание | Решение | Результат | Предполагаемый результат |", text)
        rows = [line for line in text.splitlines() if line.startswith("| **")]
        self.assertEqual(len(rows), 2)
        self.assertIn("baseline/workspace/solution.py", rows[0])
        self.assertIn("Время: нет данных", rows[1])
        self.assertTrue(all(line.count("|") == 5 for line in rows))
        self.assertIn("Деталь &#124; размер<br>строка", text)
        self.assertNotIn("99.99", text)
        self.assertNotIn("<img", text)
        self.assertNotIn("model.m3d", text)
        self.assertIn("[run.json]", text)
        self.assertIn("[Трейс]", text)
        for url in re.findall(r"\]\(([^)]+)\)", text):
            self.assertTrue((self.root / unquote(url)).is_file(), url)

    def test_existing_sources_expected_and_actual_images(self) -> None:
        source = self.corpus / "Level01_BasicSketch/PracticeProblems_1_1"
        for suffix in ("_ENG.md", "_ENG.pdf", "_preview.jpg"):
            self.write(source.with_name(source.name + suffix))
        for name in ("workspace/model.m3d", "verification/model.jpg"):
            self.write(self.run / "baseline" / name)
        text = self.render()
        self.assertIn("[Условие]", text)
        self.assertIn("[PDF]", text)
        self.assertIn("[Модель CAD]", text)
        self.assertIn('[<img src="PracticeProblems_ALL250_CSWA/skillopt-runs/run%20one/baseline/verification/model.jpg" width="260"', text)
        self.assertIn("PracticeProblems_1_1_preview.jpg", text)

    def test_worker_timing_format(self) -> None:
        for seconds, expected in ((1836.101, "**31 мин** (1836.101с)"),
                                  (546.509, "**9 мин** (546.509с)"),
                                  (12.5, "**13 с** (12.500с)"),
                                  (60, "**1 мин** (60.000с)"),
                                  (0, "**0 с** (0.000с)")):
            with self.subTest(seconds=seconds):
                self.assertEqual(_timing({"worker_seconds": seconds}), expected)
        self.assertEqual(_timing({"teacher_seconds": 100}), "Время: нет данных")

    def test_worker_tokens_sum_only_final_request_usage(self) -> None:
        trace = self.run / "baseline/trace.jsonl"
        usage = {"input": 1000, "output": 200, "cacheRead": 3000, "cacheWrite": 500, "totalTokens": 4700}
        message = {"role": "assistant", "usage": usage}
        events = [{"type": "message_start", "message": message},
                  {"type": "message_update", "usage": usage},
                  {"type": "message_end", "message": message},
                  {"type": "message_end", "message": {"role": "toolResult"}},
                  {"type": "message_end", "message": {"role": "assistant", "usage": {"totalTokens": 7600}}},
                  {"type": "agent_end", "messages": [message]}]
        self.write(trace, "\n".join(json.dumps(event) for event in events) + "\n")
        self.assertEqual(_tokens(trace), "0.012 млн. токенов")
        self.write(self.run / "baseline/teacher-pi/trace.jsonl",
                   json.dumps({"type": "message_end", "message": message}))
        row = next(line for line in self.render().splitlines() if line.startswith("| **"))
        self.assertIn("**13 с** (12.500с)<br>0.012 млн. токенов<br>[run.json]", row)

    def test_missing_token_usage_is_not_reported_as_zero_or_partial(self) -> None:
        trace = self.run / "baseline/trace.jsonl"
        self.assertEqual(_tokens(trace), "Токены: нет данных")
        self.write(trace, "")
        self.assertEqual(_tokens(trace), "Токены: нет данных")
        events = [{"type": "message_end", "message": {"role": "assistant", "usage": {"totalTokens": 1000}}},
                  {"type": "message_end", "message": {"role": "assistant"}}]
        self.write(trace, "\n".join(json.dumps(event) for event in events))
        self.assertEqual(_tokens(trace), "Токены: нет данных")
        self.write(trace, json.dumps({"type": "message_end", "message": {
            "role": "assistant", "usage": {"totalTokens": 0}}}))
        self.assertEqual(_tokens(trace), "0.000 млн. токенов")

    def test_timing_budget_and_exact_overrun(self) -> None:
        for seconds, expected in ((1836.101, "**31 из 15 мин** (1836.101с) ⚠️"),
                                  (899.999, "**15 из 15 мин** (899.999с)"),
                                  (900, "**15 из 15 мин** (900.000с)"),
                                  (900.001, "**15 из 15 мин** (900.001с) ⚠️"),
                                  (12.5, "**0 из 15 мин** (12.500с)")):
            with self.subTest(seconds=seconds):
                self.assertEqual(_timing({"worker_seconds": seconds}, 15), expected)
        self.assertEqual(_timing({}, 15), "Время: нет данных")

    def test_report_reads_duration_from_task_markdown(self) -> None:
        source = self.corpus / "Level01_BasicSketch/PracticeProblems_1_1_ENG.md"
        self.write(source, "# Task\n- Duration (min): 5  \nVolume: 72593 mm3\n")
        self.data["attempts"][0]["worker_seconds"] = 546.509
        row = next(line for line in self.render().splitlines() if line.startswith("| **"))
        self.assertIn("**9 из 5 мин** (546.509с) ⚠️", row)
        self.data["attempts"][0]["worker_seconds"] = 300
        row = next(line for line in self.render().splitlines() if line.startswith("| **"))
        self.assertIn("**5 из 5 мин** (300.000с)", row)
        self.assertNotIn("⚠️", row)
        self.write(source, "- Duration (min): 2.5\n")
        self.assertIn("**5 из 2.5 мин** (300.000с) ⚠️", self.render())
        self.write(source, "# No duration specified\n")
        self.assertIn("**5 мин** (300.000с)", self.render())

    def test_no_false_pass_without_teacher_and_no_fabricated_timings(self) -> None:
        self.write(self.run / "baseline/verification/verification.json",
                   {"geometry_passed": True, "native_tree_passed": True, "sketches_fully_defined": True})
        text = self.render()
        self.assertIn("Ожидает проверки учителя", text)
        self.assertNotIn("✅", text)
        self.assertIn("**13 с** (12.500с)", text)
        self.assertIn("Время: нет данных", text)
        self.assertNotIn("Верификация: 2.25 с", text)
        self.assertNotIn("Общий интервал:", text)

    def test_running_and_worker_failure(self) -> None:
        attempt = self.data["attempts"][0]
        attempt.update(status="running", skill_sha256="attempt-specific")
        text = self.render()
        self.assertIn("Моделирование выполняется", text)
        self.assertNotIn("SHA-256", text)
        attempt.update(status="blocked", error="Worker timeout", worker_exit_code=124)
        text = self.render()
        self.assertIn("❌ **Не пройдено**", text)
        self.assertIn("Worker timeout", text)
        self.assertIn("Исполнитель завершился с кодом 124", text)

    def test_pass_shows_only_image_and_status_with_links_in_solution(self) -> None:
        self.passed_evidence()
        self.data["attempts"][0].update(teacher_seconds=4.5, elapsed_seconds=21.0)
        self.data["gate"] = {"action": "no_change", "accepted": False}
        text = self.render()
        row = next(line for line in text.splitlines() if line.startswith("| **"))
        solution, result = row.split(" | ")[1:3]
        self.assertTrue(solution.startswith("**13 с** (12.500с)<br>Токены: нет данных<br>[run.json]"))
        self.assertIn("[Верификация JSON]", solution)
        self.assertIn("[Рецензия JSON]", solution)
        self.assertTrue(result.startswith('[<img src="'))
        self.assertTrue(result.endswith("<br>✅ **Пройдено**"))
        self.assertEqual(result.count("<br>"), 1)
        for clutter in ("score=", "подробные замечания", "проверено", "факт:", "Объём:", "<details>",
                        "SHA-256", "Gate", "thinking:", "Статус исполнителя:", "Общий интервал:"):
            self.assertNotIn(clutter, text)

    def test_report_preview_does_not_replace_teacher_evidence(self) -> None:
        self.passed_evidence()
        self.data["attempts"][0]["report_preview"] = {"path": "preview-iso90/model.jpg"}
        self.write(self.run / "baseline/preview-iso90/model.jpg")
        self.write(self.run / "baseline/report-preview.json", {"view_scheme": "ksVPSZ90AxonometricISO"})
        text = self.render()
        self.assertIn('baseline/preview-iso90/model.jpg" width=', text)
        self.assertNotIn('baseline/verification/model.jpg" width=', text)
        self.assertIn("[Превью JSON]", text)
        self.assertIn("✅ **Пройдено**", text)
        (self.run / "baseline/verification/model.jpg").unlink()
        self.assertNotIn("✅", self.render())

    def test_incomplete_or_failed_checks_never_pass(self) -> None:
        review, verification = self.passed_evidence()
        review["origin_checked"] = False
        self.write(self.run / "baseline/teacher-review.json", review)
        text = self.render()
        self.assertNotIn("✅", text)
        self.assertIn("Начало координат не подтверждено", text)
        review["origin_checked"] = True
        self.write(self.run / "baseline/teacher-review.json", review)
        verification["errors"] = [{"error": "preview failure"}]
        self.write(self.run / "baseline/verification/verification.json", verification)
        text = self.render()
        self.assertNotIn("✅", text)
        self.assertIn("preview failure", text)
        verification["errors"] = []
        self.write(self.run / "baseline/verification/verification.json", verification)
        self.data["attempts"][0]["status"] = "done"
        self.assertNotIn("✅", self.render())
        self.data["attempts"][0]["status"] = "passed"
        verification["native_tree_passed"] = False
        self.write(self.run / "baseline/verification/verification.json", verification)
        text = self.render()
        self.assertNotIn("✅", text)
        self.assertIn("Ошибки нативного дерева", text)

    def test_failure_explains_only_failed_checks_and_teacher_feedback(self) -> None:
        review, verification = self.passed_evidence()
        self.data["attempts"][0]["status"] = "failed"
        review.update(passed=False, feedback="Отверстие не там", notes=["размер | связь\nограничение"])
        verification["checks"]["ширина"] = {"passed": False, "actual": 50, "expected": 60}
        self.write(self.run / "baseline/teacher-review.json", review)
        self.write(self.run / "baseline/verification/verification.json", verification)
        text = self.render()
        self.assertIn("❌ **Не пройдено**", text)
        self.assertIn("Отверстие не там", text)
        self.assertIn("размер &#124; связь<br>ограничение", text)
        self.assertIn("ширина: факт 50; ожидалось 60", text)
        self.assertNotIn("факт 120", text)
        self.assertNotIn("score=", text)

    def test_blocked_teacher_is_not_a_model_failure_or_score(self) -> None:
        self.data["attempts"][0]["status"] = "review_blocked"
        self.write(self.run / "baseline/teacher-review.json", {
            "status": "blocked", "passed": False, "score": None,
            "blockers": ["Недоступны пиксели"], "visual_checked": False})
        text = self.render()
        self.assertIn("❌ **Проверка заблокирована**", text)
        self.assertIn("Недоступны пиксели", text)
        self.assertNotIn("❌ **Не пройдено**", text)
        self.assertNotIn("score=", text)

    def test_harness_blocker_without_review_and_run_errors_are_visible(self) -> None:
        self.data["attempts"][0].update(status="review_blocked", review_blockers=["Teacher timeout"])
        self.data["error"] = "Pipeline error | detail"
        text = self.render()
        self.assertIn("❌ **Проверка заблокирована**", text)
        self.assertIn("Teacher timeout", text)
        self.assertIn("Pipeline error &#124; detail", text)

    def test_empty_runs(self) -> None:
        text = render_report(self.root).read_text(encoding="utf-8")
        self.assertIn("Изолированных попыток пока нет", text)
        self.assertIn("Автоматического принятия скилла нет", text)
        self.assertIn("CAD выполняется последовательно", text)


if __name__ == "__main__":
    unittest.main()
