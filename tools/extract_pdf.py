# /// script
# requires-python = ">=3.11"
# dependencies = ["pymupdf>=1.27", "pillow"]
# ///
"""Извлечь чертёж (.jpg) и Markdown (.md) из каждого PDF указанной папки.

В этих одностраничных PDF чертёж — самое большое встроенное изображение;
меньшие изображения содержат логотипы. Извлекается исходное изображение,
без рендеринга страницы, обрезки, масштабирования или OCR. Размерные надписи,
встроенные в картинку, остаются в JPG. Markdown содержит текстовый слой PDF,
относительную ссылку на чертёж через ![](); исходные PDF не публикуются.

Запуск: uv run --script tools/extract_pdf.py ПАПКА
Повторная запись существующих результатов: добавить --overwrite.
Исходные PDF никогда не изменяются.
"""
from __future__ import annotations

import argparse
from io import BytesIO
from pathlib import Path
from os.path import relpath
import re
from urllib.parse import quote
from zipfile import ZipFile

from PIL import Image
import pymupdf


def extract(pdf: Path) -> tuple[Image.Image, str]:
    with pymupdf.open(pdf) as document:
        if len(document) != 1:
            raise ValueError(f"Ожидалась одна страница: {pdf}")
        page = document[0]
        images = {item[0]: item for item in page.get_images(full=True)}
        if not images:
            raise ValueError(f"Нет встроенных изображений: {pdf}")
        largest_area = max(item[2] * item[3] for item in images.values())
        drawings = [
            item for item in images.values()
            if item[2] * item[3] == largest_area
        ]
        if len(drawings) != 1:
            raise ValueError(f"Не удалось однозначно выбрать чертёж: {pdf}")
        xref, mask_xref, *_ = drawings[0]
        if not page.get_image_rects(xref):
            raise ValueError(f"Изображение не размещено на странице: {pdf}")

        image_data = document.extract_image(xref)
        with Image.open(BytesIO(image_data["image"])) as source:
            drawing = source.convert("RGB")
        if mask_xref:
            mask_data = document.extract_image(mask_xref)
            with Image.open(BytesIO(mask_data["image"])) as source_mask:
                mask = source_mask.convert("L")
            if mask.size != drawing.size:
                raise ValueError(f"Размер маски не совпадает с чертежом: {pdf}")
            background = Image.new("RGB", drawing.size, "white")
            background.paste(drawing, (0, 0), mask)
            drawing = background

        text = page.get_text("text").strip()
        if not text:
            raise ValueError(f"Пустой текстовый слой: {pdf}")
        return drawing, text + "\n"


def dependencies(pdf: Path, text: str) -> str:
    """Describe audited source components, prerequisite tasks and source errata."""
    problem = re.fullmatch(r"PracticeProblems_(\d+)_(\d+)([A-Z]?)_ENG", pdf.stem)
    if problem is None:
        return ""
    level, number, _ = problem.groups()
    sections = []
    archive_candidates = [pdf.with_suffix(".zip"),
                          pdf.with_name(f"PracticeProblems_{level}_{number}.zip"),
                          pdf.with_name(f"PracticeProblems_{level}_{number}A_ENG.zip")]
    archive = next((path for path in archive_candidates if path.is_file()), None)
    if archive is not None:
        with ZipFile(archive) as source:
            names = [item.filename for item in source.infolist() if not item.is_dir()]
        sections.append(
            "## Исходные компоненты\n\n"
            f"[Компоненты SOLIDWORKS (ZIP)]({quote(archive.name)}) — "
            f"{len(names)} файлов; архив хранится в Git LFS.\n\n"
            "Распакуйте все файлы в один каталог, сохранив имена и структуру. "
            "Это исходные детали/подсборки SOLIDWORKS (`.SLDPRT`, `.SLDASM`), "
            "не готовые модели КОМПАС. Совместимость импорта в КОМПАС здесь не проверена.\n\n"
            "Оригинальный ZIP сохранён без изменений и может включать PDF условия; "
            "отдельные PDF в Git не добавляются.\n\n"
            "Состав архива:\n" + "\n".join(f"- `{name}`" for name in names) + "\n"
        )
    if level == "15" and number == "7":
        sections.append("Общая стартовая модель без PDF: "
                        "[PracticeProblems_15_7.zip](PracticeProblems_15_7.zip).\n")
    related = sorted({path.with_suffix(".md")
                      for path in pdf.parent.glob(f"PracticeProblems_{level}_{number}[A-Z]_ENG.*")
                      if path.suffix in {".pdf", ".md"} and path.stem != pdf.stem})
    if related:
        sections.append("## Связанные этапы и листы\n\n" + ", ".join(
            f"[{path.stem.removeprefix('PracticeProblems_').removesuffix('_ENG').replace('_', '.')}]"
            f"({quote(path.with_suffix('.md').name)})" for path in related) + ".\n")
    explicit_dependencies = {
        "PracticeProblems_13_9B_ENG": ("13", "9A"),
        "PracticeProblems_14_4_ENG": ("13", "4"),
        "PracticeProblems_14_6B_ENG": ("14", "4"),
        "PracticeProblems_18_24_ENG": ("18", "1"),
        "PracticeProblems_18_25_ENG": ("18", "3"),
    }
    key = pdf.stem
    if key in explicit_dependencies:
        previous_level, previous_number = explicit_dependencies[key]
        targets = sorted({path.with_suffix(".md") for path in pdf.parent.parent.glob(
            f"Level{int(previous_level):02d}_*/PracticeProblems_{previous_level}_{previous_number}_ENG.*")
            if path.suffix in {".pdf", ".md"}})
        if len(targets) != 1:
            raise ValueError(f"Не найдено исходное задание: {key}")
        target = targets[0].with_suffix(".md")
        sections.append("## Исходное задание\n\n"
                        f"Используйте результат [{previous_level}.{previous_number}]"
                        f"({quote(relpath(target, pdf.parent))})"
                        + (" или стартовую модель из ZIP.\n" if archive else ".\n"))
    elif level == "18" and problem.group(3) == "B" and number in {"5", "6", "7", "8", "9", "12", "20"}:
        sections.append("## Предыдущее задание\n\n"
                        f"Измените деталь из [18.{number}A](PracticeProblems_18_{number}A_ENG.md).\n")
    previous = re.search(r"HINT:\s*Start with the (\d+)\.(\d+[ABC]?)\s+(assembly|part)\.", text)
    if previous:
        previous_level, previous_number, kind = previous.groups()
        if pdf.stem == "PracticeProblems_10_7C_ENG":
            previous_level, previous_number = "10", "7B"
        if previous_level != level:
            raise ValueError(f"Не проверена межуровневая зависимость: {pdf}")
        filename = f"PracticeProblems_{previous_level}_{previous_number}_ENG.md"
        if not pdf.with_name(filename).is_file():
            raise ValueError(f"Нет предыдущего задания: {filename}")
        model = "сборку" if kind == "assembly" else "деталь"
        sections.append(
            "## Предыдущее задание\n\n"
            f"Сначала выполните [{previous_level}.{previous_number}]({quote(filename)}), "
            f"затем изменяйте полученную {model}. Задание не является независимым.\n"
        )
    if pdf.stem == "PracticeProblems_10_7C_ENG":
        sections.append(
            "## Примечание к оригиналу\n\n"
            "В исходном условии написано «Start with the 9.7B part». "
            "Вероятная опечатка: имеется в виду деталь из 10.7B; "
            "исходная формулировка ниже сохранена без исправления.\n"
        )
    if pdf.stem == "PracticeProblems_9_10_ENG":
        sections.append(
            "## Примечание к оригиналу\n\n"
            "В исходном условии ошибочно указан раздел «Revolve Boss/Cut (Level 6)». "
            "По номеру, компонентам и операциям это задание на сборку Level 9; "
            "исходный заголовок ниже сохранён без исправления.\n"
        )
    return "\n".join(sections) + ("\n" if sections else "")


def markdown(pdf: Path, text: str) -> str:
    title = pdf.stem.replace("_", " ")
    text = re.sub(
        r"©\s*\d{4}\s+Dassault Systèmes\..*?Cannot be reproduced for sale nor incorporated\.",
        "", text, flags=re.DOTALL,
    ).strip()
    text = re.sub(r"(?m)^[ \t]*•[ \t]*\n[ \t]*", "• ", text)
    lines = []
    design_intent = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("• "):
            line = "- " + line[2:]
            design_intent = "Design Intent:" in line
        elif design_intent and line.startswith("o "):
            line = "\t- " + line[2:]
        elif (design_intent and line and line[0].islower()
              and lines and lines[-1].startswith("\t- ")):
            lines[-1] += " " + line
            continue
        elif line:
            design_intent = False
        lines.append(line)
    lines = [
        line for line in lines
        if line.strip() not in {"- The part is symmetric.", "- The part is asymmetric."}
    ]
    body = "  \n".join(lines)
    return (
        f"# {title}\n\n"
        f"![Чертёж]({quote(pdf.with_suffix('.jpg').name)})\n\n"
        f"{dependencies(pdf, text)}"
        f"## Текст задания\n\n{body}\n"
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "directory", type=Path,
        help="Папка с PDF выбранного уровня",
    )
    parser.add_argument(
        "--overwrite", action="store_true",
        help="Перезаписать ранее извлечённые JPG и Markdown",
    )
    parser.add_argument("--markdown-only", action="store_true",
                        help="Обновить только Markdown, не извлекая JPEG повторно")
    parser.add_argument("--exclude", action="append", default=[], metavar="FILENAME",
                        help="Явно исключить исходник по имени, например защищённый паролем PDF")
    args = parser.parse_args(argv)
    directory = args.directory.expanduser().resolve()
    if not directory.is_dir():
        parser.error(f"Каталог не существует: {directory}")
    pdfs = sorted(
        (path for path in directory.iterdir()
         if path.is_file() and path.suffix.lower() == ".pdf" and path.name not in args.exclude),
        key=lambda path: path.name,
    )
    if not pdfs:
        parser.error(f"В каталоге нет PDF: {directory}")

    for pdf in pdfs:
        targets = (pdf.with_suffix(".md"),) if args.markdown_only else (pdf.with_suffix(".jpg"), pdf.with_suffix(".md"))
        for target in targets:
            if target.is_symlink():
                parser.error(f"Выходной путь — символическая ссылка: {target}")
            if target.exists() and (not args.overwrite or not target.is_file()):
                parser.error(f"Выход уже существует: {target}; используйте --overwrite")

    for pdf in pdfs:
        image_path = pdf.with_suffix(".jpg")
        text_path = pdf.with_suffix(".md")
        if args.markdown_only:
            if not image_path.is_file():
                parser.error(f"Нет ранее извлечённого JPEG: {image_path}")
            with pymupdf.open(pdf) as document:
                text = "\n".join(page.get_text("text") for page in document).strip()
            if not text:
                parser.error(f"Пустой текстовый слой: {pdf}")
        else:
            drawing, text = extract(pdf)
            with image_path.open("wb" if args.overwrite else "xb") as output:
                drawing.save(output, format="JPEG", quality=95, subsampling=0)
        with text_path.open("w" if args.overwrite else "x", encoding="utf-8") as output:
            output.write(markdown(pdf, text))
        print(f"{pdf.name} -> {text_path.name}" if args.markdown_only else
              f"{pdf.name} -> {image_path.name} ({drawing.width}x{drawing.height}), {text_path.name}")
    print(f"Готово: {len(pdfs)} Markdown" if args.markdown_only else
          f"Готово: {len(pdfs)} JPG и {len(pdfs)} Markdown")


if __name__ == "__main__":
    main()
