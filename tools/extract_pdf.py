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
import re
from urllib.parse import quote

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
    args = parser.parse_args(argv)
    directory = args.directory.expanduser().resolve()
    if not directory.is_dir():
        parser.error(f"Каталог не существует: {directory}")
    pdfs = sorted(
        (path for path in directory.iterdir()
         if path.is_file() and path.suffix.lower() == ".pdf"),
        key=lambda path: path.name,
    )
    if not pdfs:
        parser.error(f"В каталоге нет PDF: {directory}")

    for pdf in pdfs:
        for target in (pdf.with_suffix(".jpg"), pdf.with_suffix(".md")):
            if target.is_symlink():
                parser.error(f"Выходной путь — символическая ссылка: {target}")
            if target.exists() and (not args.overwrite or not target.is_file()):
                parser.error(f"Выход уже существует: {target}; используйте --overwrite")

    for pdf in pdfs:
        drawing, text = extract(pdf)
        image_path = pdf.with_suffix(".jpg")
        text_path = pdf.with_suffix(".md")
        with image_path.open("wb" if args.overwrite else "xb") as output:
            drawing.save(output, format="JPEG", quality=95, subsampling=0)
        with text_path.open("w" if args.overwrite else "x", encoding="utf-8") as output:
            output.write(markdown(pdf, text))
        print(f"{pdf.name} -> {image_path.name} ({drawing.width}x{drawing.height}), {text_path.name}")
    print(f"Готово: {len(pdfs)} JPG и {len(pdfs)} Markdown")


if __name__ == "__main__":
    main()
