#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Работа с активным документом в API-сессии КОМПАС.

Важно (нативный KsAPI):
  GetKompas() подключается к API-сессии, запущенной пользователем
  (kKompas -APIServer=...). Обычный запуск kompas-v25 из меню
  не создаёт API-сессию. Этот макрос новый процесс не запускает.

  Файлы из /run/user/.../doc/ (портал Flatpak/Telegram) read-only —
  КОМПАС не сможет сохранить. Копируй в обычную папку.

Запуск:
  ./run.sh touch_active.py
  ./run.sh touch_active.py ~/kompas-models/model.m3d
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

BIN = Path("/opt/ascon/kompas3d-v25/Bin")
sys.path.insert(0, str(BIN))

import ksapi  # noqa: E402
from constants import constants as c  # noqa: E402

DOC_NAMES = {
    c.ksDocumentDrawing: "чертёж",
    c.ksDocumentFragment: "фрагмент",
    c.ksDocumentPart: "деталь",
    c.ksDocumentAssembly: "сборка",
}

WRITABLE = Path.home() / "kompas-models"


def connect():
    app = ksapi.GetKompas()
    if not app:
        command = (
            f'LD_LIBRARY_PATH="{BIN}${{LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}}" '
            'LC_ALL="${LC_ALL:-C.UTF-8}" '
            f'"{BIN}/kKompas" -APIServer=10500'
        )
        raise RuntimeError(
            f"API-сессия КОМПАС недоступна. Запустите в отдельном терминале:\n{command}"
        )
    return app


def ensure_writable(path: Path) -> Path:
    s = str(path)
    if "/run/user/" in s and "/doc/" in s:
        WRITABLE.mkdir(parents=True, exist_ok=True)
        # A separate directory keeps the filename and cannot collide with an older copy.
        destination = Path(tempfile.mkdtemp(prefix="portal-", dir=WRITABLE))
        dest = destination / path.name
        shutil.copy2(path, dest)
        print(f"портал → скопировано в {dest}")
        return dest
    return path


def touch_part(part) -> list[str]:
    done = [
        f"деталь: {part.GetName() or '(без имени)'}",
        f"масса: {part.GetMass():.4g}",
        f"материал: {part.GetMaterial() or '(не задан)'}",
    ]
    variable = part.AddVariable("macro_touched", 1.0, "макрос touch_active")
    if not variable:
        raise RuntimeError("Не удалось создать переменную macro_touched")
    done.append("переменная macro_touched=1")

    pts = part.GetModelContainer().GetPoints3D()
    pt = pts.Add()
    if not pt:
        raise RuntimeError("Не удалось создать точку macro_point")
    pt.SetName("macro_point")
    pt.SetX(10.0)
    pt.SetY(20.0)
    pt.SetZ(30.0)
    if not pt.Update():
        raise RuntimeError("Не удалось обновить точку macro_point")
    if not part.RebuildModel(True):
        raise RuntimeError("Не удалось перестроить модель")
    done.append("точка macro_point (10, 20, 30)")
    return done


def touch_drawing(doc) -> list[str]:
    doc2d = ksapi.IKompasDocument2D(doc)
    view = doc2d.GetViewsAndLayersManager().GetViews().GetActiveView()
    container = ksapi.IDrawingContainer(view)
    circle = container.GetCircles().Add()
    if not circle:
        raise RuntimeError("Не удалось создать окружность")
    circle.SetXc(100.0)
    circle.SetYc(100.0)
    circle.SetRadius(25.0)
    if not circle.Update():
        raise RuntimeError("Не удалось обновить окружность")
    return ["на виде: окружность R25 в (100,100)"]


def main() -> int:
    app = connect()
    print(f"подключено: {app.GetApplicationName(True)}")

    docs = app.GetDocuments()
    doc = app.GetActiveDocument()

    if len(sys.argv) > 1:
        path = ensure_writable(Path(sys.argv[1]).expanduser().resolve())
        doc = docs.GetItemByFilePath(str(path)) or docs.Open(str(path), True, False)
    elif not doc:
        raise RuntimeError(
            "Нет активного документа. Открой модель в ЭТОМ окне КОМПАС "
            "(API-сессия) или: ./run.sh touch_active.py /path/to/file"
        )

    if not doc:
        raise RuntimeError("Не удалось открыть документ")

    dtype = doc.GetDocumentType()
    title = doc.GetName() or "(без имени)"
    print(f"документ: {title}")
    print(f"тип: {DOC_NAMES.get(dtype, dtype)}")
    print(f"путь: {doc.GetFullPath() or '(не сохранён)'}")

    if dtype in (c.ksDocumentPart, c.ksDocumentAssembly):
        part = ksapi.IKompasDocument3D(doc).GetTopPart()
        if not part:
            raise RuntimeError("GetTopPart() пустой")
        done = touch_part(part)
    elif dtype in (c.ksDocumentDrawing, c.ksDocumentFragment):
        done = touch_drawing(doc)
    else:
        raise RuntimeError(f"Неподдерживаемый тип документа: {dtype}")

    for line in done:
        print(line)

    app.ShowMessageBox(
        f"{title}\n" + "\n".join(done),
        "touch_active",
        0,
        1,
        False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
