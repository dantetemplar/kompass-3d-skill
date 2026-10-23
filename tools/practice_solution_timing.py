# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Restore retrospective executor timing using explicit transcript timestamps only.

Only run.json's timing member is inserted; all other original bytes are retained.
No CAD access, model reads, filesystem timestamps, or preview work is involved.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRANSCRIPTS = Path(
    "/home/dante/.cursor/projects/home-dante-Projects-riki-tiki-tavi-coffee-grinder/"
    "agent-transcripts/1f8fdc67-5859-46a7-ac62-d2f948f56667"
)
PARENT_NAME = "1f8fdc67-5859-46a7-ac62-d2f948f56667.jsonl"
STAMP = re.compile(r"<timestamp>(.*?)</timestamp>")
SCOPE = "От первой передачи исполнителю до завершения; без экспорта превью"
# Reviewed parent launch and final-completion records; not the completion of a
# terminal command or an intermediate failed/blocked attempt.
EVIDENCE = {
    "1.1": (381, 397), "1.2": (404, 424), "1.3": (433, 441),
    "1.4": (450, 470), "1.5": (478, 486), "1.6": (492, 519),
    "1.7": (526, 542), "1.8": (549, 561), "1.9": (568, 580),
    "1.10": (587, 603), "1.11": (610, 638), "1.12": (643, 651),
    "1.13": (659, 663), "1.14": (671, 683), "1.15": (690, 715),
    "1.16": (722, 730), "1.17": (737, 741), "1.18": (748, 756),
    "1.19": (763, 771), "1.20": (778, 786),
    "2.1": (794, 811), "2.2": (818, 830), "2.3": (837, 857),
    "2.4": (864, 923), "2.5": (929, 948), "2.6": (955, 959),
    "2.7": (966, 982), "2.8": (988, 996), "2.9": (1002, 1013),
    "2.10": (1020, 1034), "2.11": (1046, 1060), "2.12": (1068, None),
}

# Final notification observed directly by the orchestrator before this turn was
# appended to the transcript; unlike EVIDENCE, this source has no line number yet.
FINAL_NOTIFICATIONS = {"2.12": "2026-10-21T13:59:00+03:00"}


def records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def texts(record: dict) -> str:
    return "\n".join(
        part.get("text", "")
        for part in record.get("message", {}).get("content", [])
        if part.get("type") == "text"
    )


def timestamp(record: dict) -> datetime | None:
    match = STAMP.search(texts(record))
    if not match:
        return None
    value = datetime.strptime(match[1], "%A, %b %d, %Y, %I:%M %p (UTC+3)")
    return value.replace(tzinfo=timezone(timedelta(hours=3)))


def task_calls(value):
    if isinstance(value, dict):
        if value.get("toolName") == "Task":
            yield value.get("arguments", {})
        if value.get("name") == "Task":
            args = value.get("input", {})
            yield json.loads(args) if isinstance(args, str) else args
        for child in value.values():
            yield from task_calls(child)
    elif isinstance(value, list):
        for child in value:
            yield from task_calls(child)


def restore(run: dict, parent: list[dict], transcript_dir: Path) -> dict:
    task = run["task"]
    launch, completion = EVIDENCE[task]
    calls = list(task_calls(parent[launch - 1]))
    assert any(task in call.get("description", "") and not call.get("resume") for call in calls), task
    child_name = f"subagents/{run['agent_id']}.jsonl"
    child = records(transcript_dir / child_name)
    start = timestamp(child[0])
    assert start is not None and child[0]["role"] == "user", task
    initial_parent_stamp = next(
        ((n, timestamp(parent[n - 1])) for n in range(launch - 1, 0, -1)
         if timestamp(parent[n - 1]) is not None),
        None,
    )
    finish = None
    if completion is not None:
        event = parent[completion - 1]
        assert event["role"] == "user" and "subagent completion above" in texts(event), task
        finish = timestamp(event)
        assert finish is not None and finish >= start, task
        assert any(record.get("role") == "assistant" and texts(record).strip() for record in child), task
    if completion is None and task in FINAL_NOTIFICATIONS:
        finish = datetime.fromisoformat(FINAL_NOTIFICATIONS[task])
        assert finish >= start, task
    resumes = [
        (n, timestamp(record).isoformat())
        for n, record in enumerate(child, 1)
        if n > 1 and record.get("role") == "user" and timestamp(record) is not None
    ]
    note = (
        "Ретроспективная оценка: начало — минутная метка первой передачи в журнале "
        "исполнителя; конец — минутная метка уведомления оркестратору о финальном завершении. "
        "Точные секунды не записаны: квантование каждой границы до 60 с, разности до 120 с; "
        "дополнительная задержка передачи/доставки уведомления неизвестна и в эту погрешность не входит. "
        "Включены все попытки, продолжения, ожидания и паузы; экспорт превью исключён."
    )
    if resumes:
        note += " Возобновления не обнуляют начало: " + ", ".join(value for _, value in resumes) + "."
    if task == "1.15":
        note += " Включены первоначальная blocked-попытка и продолжение после повторной передачи изображений."
    if task == "2.10":
        note += (
            " Включены обрыв потока, возобновление в 08:33 и многочасовой промежуток до 13:22; "
            "активную работу и простой внутри него журнал не позволяет разделить."
        )
    if finish is None:
        note = (
            "Начало восстановлено ретроспективно по минутной метке первой передачи исполнителю "
            "(13:35 UTC+3, квантование до 60 с; задержка передачи неизвестна). "
            "На момент реконструкции финальное завершение не подтверждено: конец и длительность "
            "неизвестны. Исполнитель не прерывался; текущее время не подставлено вместо конца."
        )
    source = f"{PARENT_NAME}:L{launch}"
    if completion is not None:
        source += f",L{completion}"
    source += f"; {child_name}:L1"
    if completion is None and finish is not None:
        source += f"; final completion notification timestamp {finish.isoformat()} (orchestrator turn)"
    return {
        "status": "estimated" if finish is not None else "running",
        "started_at": start.isoformat(),
        "finished_at": finish.isoformat() if finish else None,
        "elapsed_seconds": int((finish - start).total_seconds()) if finish else None,
        "scope": SCOPE,
        "source": source,
        "note": note,
        "evidence": {
            "timestamp_resolution_seconds": 60,
            "additional_notification_delay_seconds": None,
            "start_event": "initial_executor_task_delivery",
            "finish_event": "final_executor_completion_notification" if finish else None,
            "parent_launch_line": launch,
            "parent_completion_line": completion,
            "preceding_parent_timestamp_line": initial_parent_stamp[0] if initial_parent_stamp else None,
            "preceding_parent_timestamp": initial_parent_stamp[1].isoformat() if initial_parent_stamp else None,
            "executor_initial_timestamp_line": 1,
            "executor_resume_timestamps": [
                {"line": line, "timestamp": value} for line, value in resumes
            ],
        },
    }


def insert_timing(path: Path, timing: dict) -> None:
    original = path.read_text()
    before = json.loads(original)
    if "timing" in before:
        raise ValueError(f"timing already exists; refusing to overwrite: {path}")
    closing = original.rfind("}")
    prefix = original[:closing].rstrip()
    separator = "," if before else ""
    member = json.dumps({"timing": timing}, ensure_ascii=False, indent=2)[1:-1].strip("\n")
    updated = prefix + separator + "\n" + member + "\n" + original[closing:]
    after = json.loads(updated)
    assert after.pop("timing") == timing
    assert after == before
    path.write_text(updated)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transcripts", type=Path, default=DEFAULT_TRANSCRIPTS)
    parser.add_argument("--write", action="store_true", help="Insert timing; default is a dry run")
    args = parser.parse_args()
    parent = records(args.transcripts / PARENT_NAME)
    paths = list((ROOT / "PracticeProblems_ALL250_CSWA/solutions").glob("**/run.json"))
    paths.sort(key=lambda path: tuple(map(int, path.parent.name.split("_"))))
    counts = Counter()
    for path in paths:
        run = json.loads(path.read_text())
        timing = restore(run, parent, args.transcripts)
        if args.write:
            insert_timing(path, timing)
        elif "timing" in run:
            assert run["timing"] == timing, f"Stored timing differs from transcript evidence: {path}"
        counts[timing["status"]] += 1
        elapsed = timing["elapsed_seconds"]
        print(run["task"], timing["status"], timing["started_at"], timing["finished_at"],
              f"{elapsed // 60} min" if elapsed is not None else "unknown")
    assert len(paths) == len(EVIDENCE) == 32
    print(json.dumps(dict(counts), ensure_ascii=False))


if __name__ == "__main__":
    main()
