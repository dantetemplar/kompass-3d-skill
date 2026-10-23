# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow"]
# ///
"""Экспортировать preview уже сохранённого решения без повторного построения."""
import argparse
import json
from pathlib import Path
from tempfile import mkdtemp

import ksapi
from constants import constants as c
from run_examples import capture, require


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    directory = args.directory.resolve()
    result = json.loads((directory / "result.json").read_text())
    model = (directory / result["model"]).resolve()
    require(model.is_file(), "Нет модели")
    app = require(ksapi.GetKompas(), "Нет действующей API-сессии; запуск запрещён")
    previous = app.GetActiveDocument()
    documents = app.GetDocuments()
    doc = documents.GetItemByFilePath(str(model))
    owned = not bool(doc)
    if owned:
        doc = require(documents.Open(str(model), True, False), "Открытие сохранённой модели")
    try:
        require(Path(doc.GetFullPath()).resolve() == model, "Открыта другая модель")
        output = Path(mkdtemp(prefix="preview-", dir=directory)) / "model.jpg"
        preview = capture(doc, output)
        preview["file"] = output.relative_to(directory).as_posix()
        preview["visual_status"] = "Визуально не проверено"
        (directory / "preview.json").write_text(json.dumps(preview, ensure_ascii=False, indent=2) + "\n")
        print(output, flush=True)
    finally:
        if owned:
            require(doc.Close(c.kdDoNotSaveChanges), "Закрытие своего документа после экспорта")
        if previous:
            previous.SetActive()


if __name__ == "__main__":
    main()
