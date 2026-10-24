"""Render isolated SkillOpt practice runs into the repository's PRACTICE.md."""
import argparse
import html
import json
import math
from pathlib import Path
import re
from typing import Any
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
CORPUS = "PracticeProblems_ALL250_CSWA"


def _text(value: object) -> str:
    text = html.escape(str(value)).replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"([\\`*\[\]_])", r"\\\1", text).replace("|", "&#124;").replace("\n", "<br>")


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _link(root: Path, path: Path, label: str) -> str:
    if not path.is_file():
        return ""
    return f"[{label}]({quote(path.relative_to(root).as_posix(), safe='/')})"


def _image(root: Path, path: Path, label: str) -> str:
    if not path.is_file():
        return ""
    url = quote(path.relative_to(root).as_posix(), safe="/")
    return _link(root, path, f'<img src="{url}" width="260" alt="{html.escape(label, quote=True)}">')


def _expected_minutes(sources: list[Path]) -> float | None:
    for source in sources:
        if source.suffix == ".md":
            match = re.search(r"Duration\s*\(min\)\s*:\s*(\d+(?:\.\d+)?)\b",
                              source.read_text(encoding="utf-8"), re.IGNORECASE)
            if match:
                return float(match[1])
    return None


def _timing(attempt: dict[str, Any], expected_minutes: float | None = None) -> str:
    seconds = attempt.get("worker_seconds")
    if seconds is None:
        return "Время: нет данных"
    minutes = math.floor(seconds / 60 + .5)
    if expected_minutes is not None:
        duration = f"{minutes} из {expected_minutes:g} мин"
    else:
        duration = f"{minutes} мин" if seconds >= 60 else f"{math.floor(seconds + .5)} с"
    warning = " ⚠️" if expected_minutes is not None and seconds > expected_minutes * 60 else ""
    return f"**{duration}** ({seconds:.3f}с){warning}"


def worker_usage(trace: Path) -> dict[str, Any] | None:
    """Sum worker request usage once; streamed deltas and agent_end copies are not requests."""
    if not trace.is_file():
        return None
    requests = 0
    totals = dict.fromkeys(("input", "output", "cacheRead", "cacheWrite", "totalTokens"), 0)
    tools: dict[str, int] = {}
    with trace.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get("type") == "tool_execution_start":
                name = event["toolName"]
                tools[name] = tools.get(name, 0) + 1
            message = event.get("message", {})
            if event.get("type") != "message_end" or message.get("role") != "assistant":
                continue
            usage = message.get("usage", {})
            count = usage.get("totalTokens")
            if type(count) is not int or count < 0:
                return None
            for key in totals:
                value = usage.get(key)
                if type(value) is int and value >= 0 and totals[key] is not None:
                    totals[key] += value
                else:
                    totals[key] = None
            requests += 1
    return dict(totals, requests=requests, tools=tools) if requests else None


def _tokens(trace: Path) -> str:
    usage = worker_usage(trace)
    return f"{usage['totalTokens'] / 1_000_000:.3f} млн. токенов" if usage else "Токены: нет данных"


def _result(root: Path, workspace: Path, attempt: dict[str, Any], run_error: str | None = None) -> str:
    verification_path = workspace / "verification/verification.json"
    review_path = workspace / "teacher-review.json"
    verification, review = _read(verification_path), _read(review_path)
    verified = all(verification.get(key) is True for key in
                   ("geometry_passed", "native_tree_passed", "sketches_fully_defined"))
    passed = (all(review.get(key) is True for key in
                  ("passed", "visual_checked", "dimensional_intent_checked", "origin_checked"))
              and verified and verification.get("status") == "passed"
              and not verification.get("errors") and (workspace / "verification/model.jpg").is_file()
              and attempt.get("status") == "passed" and attempt.get("worker_exit_code") == 0)
    blocked = review.get("status") == "blocked" or attempt.get("status") == "review_blocked"
    if passed:
        status = "✅ **Пройдено**"
    elif blocked:
        status = "❌ **Проверка заблокирована**"
    elif not review and attempt.get("status") == "running":
        status = "Моделирование выполняется"
    elif not review and attempt.get("status") not in {"blocked", "failed"}:
        status = "Ожидает проверки учителя"
    else:
        status = "❌ **Не пройдено**"
    preview = workspace / attempt.get("report_preview", {}).get("path", "verification/model.jpg")
    parts = [_image(root, preview, "Результат CAD"), status]
    if not passed:
        reasons = []
        if blocked:
            reasons.extend(review.get("blockers", []) or attempt.get("review_blockers", []))
        elif review.get("passed") is False:
            if review.get("feedback"):
                reasons.append(review["feedback"])
            reasons.extend(review.get("notes", []))
        for name, check in verification.get("checks", {}).items():
            if check.get("passed") is False:
                reasons.append(f"{name}: факт {check.get('actual')}; ожидалось {check.get('expected')}")
        for error in verification.get("errors", []):
            reasons.append(f"{error.get('stage', 'Проверка')}: {error.get('error', error)}"
                           if isinstance(error, dict) else str(error))
        if not blocked:
            for key, label in (("geometry_passed", "Геометрия не прошла проверку"),
                               ("native_tree_passed", "Ошибки нативного дерева"),
                               ("sketches_fully_defined", "Эскизы определены не полностью")):
                if verification.get(key) is False:
                    reasons.append(label)
            for key, label in (("visual_checked", "Визуальная проверка не завершена"),
                               ("dimensional_intent_checked", "Замысел размеров не проверен"),
                               ("origin_checked", "Начало координат не подтверждено")):
                if review.get(key) is False:
                    reasons.append(label)
        if attempt.get("worker_exit_code") not in (None, 0):
            reasons.append(f"Исполнитель завершился с кодом {attempt['worker_exit_code']}")
        if attempt.get("error"):
            reasons.append(attempt["error"])
        if run_error:
            reasons.append(run_error)
        if status == "❌ **Не пройдено**" and not reasons:
            reasons.append("Проверки неполны или итог попытки не подтверждён; подробности в JSON")
        parts.extend(_text(reason) for reason in dict.fromkeys(reasons))
    return "<br>".join(part for part in parts if part)


def render_report(root: Path) -> Path:
    """Write PRACTICE.md using only isolated runs and existing local artifacts."""
    root = root.resolve()
    corpus = root / CORPUS
    lines = ["# Практика · эксперимент SkillOpt", "",
             "Эксперимент только на одном задании; независимой heldout-выборки нет. "
             "Обобщение качества не доказано. Автоматического принятия скилла нет: решение принимает человек. "
             "CAD выполняется последовательно, один исполнитель за раз.", "",
             "Время — длительность работы исполнителя из времени, отведённого в задании; ⚠️ — превышение. "
             "Токены — все запросы исполнителя, включая кэш. Подробности проверок доступны по ссылкам на JSON.", "",
             "| Задание | Решение | Результат | Предполагаемый результат |",
             "| --- | --- | --- | --- |"]
    for run_path in sorted((corpus / "skillopt-runs").glob("*/run.json")):
        run = _read(run_path)
        task = str(run["task"])
        stem = f"PracticeProblems_{task.replace('.', '_')}"
        sources = [path for suffix in ("_ENG.md", "_ENG.pdf")
                   for path in sorted(corpus.glob(f"Level*/{stem}{suffix}"))]
        task_cell = f"**{_text(task)} · {_text(run.get('title', ''))}**"
        task_cell += "".join("<br>" + _link(root, path, "PDF" if path.suffix == ".pdf" else "Условие")
                             for path in sources)
        expected = "<br>".join(_image(root, path, f"Ожидаемый результат {task}")
                              for path in sorted(corpus.glob(f"Level*/{stem}_preview.jpg")) if path.is_file()) or "—"
        expected_minutes = _expected_minutes(sources)
        for attempt in run.get("attempts", []):
            workspace = run_path.parent / attempt["directory"]
            solution = [_timing(attempt, expected_minutes), _tokens(workspace / "trace.jsonl")]
            for path, label in ((run_path, "run.json"), (workspace / "workspace/solution.py", "Код"),
                                (workspace / "workspace/model.m3d", "Модель CAD"), (workspace / "trace.jsonl", "Трейс"),
                                (workspace / "teacher-pi/trace.jsonl", "Трейс учителя"),
                                (workspace / "teacher-pi/harness.json", "Harness учителя"),
                                (workspace / "verification/verification.json", "Верификация JSON"),
                                (workspace / "teacher-review.json", "Рецензия JSON"),
                                (workspace / "report-preview.json", "Превью JSON")):
                solution.append(_link(root, path, label))
            cells = (task_cell, "<br>".join(part for part in solution if part),
                     _result(root, workspace, attempt, run.get("error")), expected)
            lines.append("| " + " | ".join(cells) + " |")
    if len(lines) == 8:
        lines.append("| — | Изолированных попыток пока нет | Успех не подтверждён | — |")
    destination = root / "PRACTICE.md"
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="Repository root")
    print(render_report(parser.parse_args().root))


if __name__ == "__main__":
    main()
