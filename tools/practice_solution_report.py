# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Обновить сводку фактических результатов решений Practice Problems Level 1–3."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "PracticeProblems_ALL250_CSWA"
SOLUTIONS = CORPUS / "solutions"
LEVELS = {
    1: ("Level01_BasicSketch", 20, "Basic Sketch and Extrusion"),
    2: ("Level02_SketchTools_EndConditions", 20, "Sketch Tools / End Conditions"),
    3: ("Level03_GlobalVariables_SketchPatterns", 8, "Global Variables / Sketch Patterns"),
}
STATUS = {"passed": "Пройдено", "partial": "С оговорками", "failed": "Не пройдено",
          "blocked": "Заблокировано", "running": "В работе", "pending": "Не начато"}


def cell(value):
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def timing_cell(run, status):
    timing = run.get("timing", {})
    timing_status = timing.get("status")
    seconds = timing.get("elapsed_seconds")
    if seconds is not None:
        minutes = max(0, round(seconds / 60))
        hours, minutes = divmod(minutes, 60)
        duration = f"{hours} ч {minutes} мин" if hours else f"{minutes} мин"
        label = f"≈ {duration}" if timing_status == "estimated" else duration
        if timing_status == "incomplete":
            label += " (неполный интервал)"
    elif timing_status == "running" or status == "running":
        label = "В работе"
    elif status == "pending":
        label = "—"
    else:
        label = "Нет достоверного интервала"
    if timing.get("note"):
        label += f"<br>{cell(timing['note'])}"
    return label


def main():
    lines = [
        "# Решения Practice Problems — Level 1–3", "",
        "Цель — решить все 48 заданий первых трёх уровней нативно в КОМПАС-3D v25/Linux, "
        "сохранить самостоятельные макросы, редактируемые модели и изображения из CAD. "
        "Таблица обновляется после каждой попытки; незавершённые и неподтверждённые решения не считаются успехом.", "",
        "Исходники: [SOLIDWORKS Practice Problems](https://www.solidworks.com/solution/education/practice-problems). "
        "Скилл зафиксирован на коммите `a89d91a75518d74e979d78ca213b38966f10f1fc`; в ходе прохода не изменяется.", "",
        "Каждую задачу решает отдельный свежий контекст; CAD-писатель только один. "
        "Исполнители получают условие, готовый JPG и общий скилл, без прошлых решений. "
        "Файловая песочница не применяется. Из `v1.zip` взят только образец оформления сводки, не решения.", "",
        "Критерий: нативное дерево, осмысленные связи и управляющие размеры, отсутствие ошибок операций, "
        "итоговый объём с проверкой интервала округления эталона, сохранённая `.m3d`. "
        "Затем оркестратор отдельно экспортирует JPEG из сохранённой модели и проверяет его визуально. "
        "Полнота параметризации, соответствие начала координат и любые расхождения отмечаются отдельно; "
        "испытания изменения размеров и повторные расчёты после открытия не требуются.", "",
        "По просьбе пользователя проход останавливается после 2.12; следующие задачи не запускаются.", "",
        "Время восстановлено ретроспективно по журналам: от первой передачи задачи исполнителю "
        "до окончательного завершения, включая неудачные попытки, продолжения и паузы. "
        "Подготовка исходников и отдельный экспорт превью в этот интервал не входят. "
        "Знак ≈ обозначает оценку; неполные или недостоверные интервалы отмечаются явно. "
        "Это календарная длительность, не активное время моделирования и не чистый benchmark. "
        "Источники и границы интервала сохранены в `run.json`; ID контекстов приведены для трассировки в Cursor.", "",
    ]
    counts = {status: 0 for status in STATUS}
    for level, (source, count, title) in LEVELS.items():
        lines += [f"## Level {level} — {title}", "",
                  "| Задание и дерево | Файлы | Проверки и ограничения | Время решения | Трейс | Результат из КОМПАС |",
                  "| --- | --- | --- | --- | --- | --- |"]
        for number in range(1, count + 1):
            task = f"{level}.{number}"
            directory = SOLUTIONS / f"Level{level:02}" / f"{level}_{number}"
            prefix = directory.relative_to(SOLUTIONS).as_posix()
            result_path = directory / "result.json"
            run_path = directory / "run.json"
            result = json.loads(result_path.read_text()) if result_path.is_file() else {}
            run = json.loads(run_path.read_text()) if run_path.is_file() else {}
            status = result.get("status", run.get("status", "pending"))
            counts[status] += 1
            label = f"**{task}. {cell(result.get('title', ''))}**".rstrip()
            if result.get("tree"):
                label += f"<br>{cell(result['tree'])}"
            files = [f"[Условие](../{source}/PracticeProblems_{level}_{number}_ENG.md)"]
            for key, text in (("script", "Код"), ("model", "Модель")):
                if result.get(key):
                    files.append(f"[{text}]({prefix}/{result[key]})")
            checks = [f"**{STATUS[status]}**"]
            if result.get("volume_mm3") is not None:
                checks.append(f"CAD: {result['volume_mm3']:.6f} мм³")
            if result.get("reference_volume") is not None:
                checks.append(f"Эталон: {result['reference_volume']} {result.get('reference_units', '')}")
            checks += [cell(item) for item in result.get("checks", [])]
            checks += [f"Оговорка: {cell(item)}" for item in result.get("limitations", [])]
            agent = run.get("agent_id")
            trace = f"[Решение {task}]({agent})<br>`{agent}`" if agent else "—"
            preview_path = directory / "preview.json"
            preview = json.loads(preview_path.read_text()) if preview_path.is_file() else {}
            image = "—"
            if preview.get("file"):
                url = f"{prefix}/{preview['file']}"
                image = f"[![{task}]({url})]({url})<br>{preview.get('visual_status', 'Визуально не проверено')}"
            lines.append("| " + " | ".join((label, " · ".join(files), "<br>".join(checks),
                                            timing_cell(run, status), trace, image)) + " |")
        lines.append("")
    lines += ["## Текущий итог", "", "; ".join(f"{STATUS[key]}: **{value}**" for key, value in counts.items()) + ".", "",
              "`result.json` содержит фактические проверки исполнителя; `preview.json` — результат отдельного "
              "экспорта оркестратора. Наличие изображения не подтверждает геометрическую точность.", ""]
    SOLUTIONS.mkdir(parents=True, exist_ok=True)
    (SOLUTIONS / "README.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
