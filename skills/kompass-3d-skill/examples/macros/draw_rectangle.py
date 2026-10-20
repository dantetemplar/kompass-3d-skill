#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Макрос: новый чертёж + прямоугольник 100×60 мм + две диагонали.

Запуск (API-сессия уже запущена пользователем):
  ./run.sh draw_rectangle.py
"""

from __future__ import annotations

import sys
from pathlib import Path

BIN = Path("/opt/ascon/kompas3d-v25/Bin")
sys.path.insert(0, str(BIN))

import ksapi  # noqa: E402
from constants import constants as c  # noqa: E402


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


def add_line(container, x1, y1, x2, y2):
    lines = container.GetLineSegments()
    seg = lines.Add()
    if not seg:
        raise RuntimeError("Не удалось создать отрезок")
    seg.SetX1(x1)
    seg.SetY1(y1)
    seg.SetX2(x2)
    seg.SetY2(y2)
    if not seg.Update():
        raise RuntimeError("Не удалось обновить отрезок")
    return seg


def main() -> int:
    app = connect()
    docs = app.GetDocuments()
    doc = docs.AddWithDefaultSettings(c.ksDocumentDrawing, True)
    if not doc:
        raise RuntimeError("Не удалось создать чертёж")

    doc2d = ksapi.IKompasDocument2D(doc)
    views = doc2d.GetViewsAndLayersManager().GetViews()
    view = views.GetActiveView()
    if not view:
        raise RuntimeError("Нет активного вида")

    # IView → IDrawingContainer через QueryInterface внутри конструктора
    container = ksapi.IDrawingContainer(view)

    # Прямоугольник объектом Rectangle
    rects = container.GetRectangles()
    rect = rects.Add()
    if not rect:
        raise RuntimeError("Не удалось создать прямоугольник")
    rect.SetX(50.0)
    rect.SetY(50.0)
    rect.SetWidth(100.0)
    rect.SetHeight(60.0)
    if not rect.Update():
        raise RuntimeError("Не удалось обновить прямоугольник")

    # Диагонали отрезками
    add_line(container, 50, 50, 150, 110)
    add_line(container, 50, 110, 150, 50)

    app.ShowMessageBox(
        "Чертёж готов: прямоугольник 100×60 и две диагонали.",
        "draw_rectangle",
        0,
        1,
        True,
    )
    print("OK: чертёж создан")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
