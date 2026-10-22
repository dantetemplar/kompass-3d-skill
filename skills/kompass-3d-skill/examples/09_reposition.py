# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Повернуть тело 4 × 2 × 3 мм на 90° вокруг Z и перенести на (10,20,30).

Это операция внутри детали, не размещение вхождения сборки.
Без аргументов документ временный; --output сохраняет новый .m3d.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import TypeVar

import ksapi
from constants import constants as c
from constants3d import constants as c3d


T = TypeVar("T")
Bounds = tuple[float, float, float, float, float, float]


def require(value: T | None, message: str) -> T:
    if not value:
        raise RuntimeError(message)
    return value


def build(part: ksapi.IPart, model: ksapi.IModelContainer) -> None:
    sketch = require(model.GetSketchs().Add(), "Эскиз")
    sketch.SetPlane(part.GetDefaultObject(c3d.o3d_planeXOY))
    require(sketch.Update(), "Опора эскиза")
    fragment = require(sketch.BeginEdit(False), "Редактирование")
    try:
        view = fragment.GetViewsAndLayersManager().GetViews().GetActiveView()
        drawing = ksapi.IDrawingContainer(view)
        rectangle = require(drawing.GetRectangles().Add(), "Прямоугольник")
        rectangle.SetX(0)
        rectangle.SetY(0)
        rectangle.SetWidth(4)
        rectangle.SetHeight(2)
        require(rectangle.Update(), "Прямоугольник")
    finally:
        require(sketch.EndEdit(), "Завершение эскиза")
    extrusion = require(model.GetExtrusions().Add(c3d.o3d_bossExtrusion), "Выдавливание")
    extrusion.SetProfiles([sketch])
    extrusion.SetDirection(c3d.dtNormal)
    require(extrusion.SetSideParameters(True, c3d.etBlind, 3, 0, False, None), "Высота")
    require(extrusion.Update(), "Исходное тело")
    bodies = ksapi.IFeature(extrusion).GetResultBodies()
    require(len(bodies) == 1, "Исходное тело")

    operation = require(model.GetBodyRepositions().Add(), "Перемещение тела")
    operation.SetRepositionBody(bodies[0])
    operation.SetCopyBody(False)
    # Матрица 4×4: поворот +90° вокруг Z, затем перенос (10,20,30) мм.
    matrix = [0, 1, 0, 0, -1, 0, 0, 0, 0, 0, 1, 0, 10, 20, 30, 1]
    require(operation.GetPosition().InitByMatrix3D(matrix), "Матрица преобразования")
    require(operation.Update(), "Поворот и перенос")


def validate(part: ksapi.IPart) -> Bounds:
    require(part.RebuildModel(True), "Перестроение")
    bodies = ksapi.IFeature(part).GetResultBodies()
    require(len(bodies) == 1 and bodies[0].IsSolid(), "Одно твёрдое тело")
    bounds = bodies[0].GetGabarit(0, 0, 0, 0, 0, 0)
    expected = (8, 20, 30, 10, 24, 33)
    require(bounds[0] and all(abs(a - b) < 1e-5 for a, b in zip(bounds[1:], expected)), "Преобразованные габариты")
    seen = set()

    def visit(feature: ksapi.IFeature) -> None:
        if feature.reference in seen:
            return
        seen.add(feature.reference)
        require(feature.GetObjectError() == 0, f"Ошибка: {feature.GetName()}")
        for child in feature.GetSubFeatures(c.ksOperTree, True, True):
            if child:
                visit(child)

    visit(ksapi.IFeature(part))
    return tuple(bounds[1:])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output.expanduser().resolve() if args.output else None
    if output:
        require(output.suffix.lower() == ".m3d" and not output.exists(), "Нужен новый путь .m3d")
        output.parent.mkdir(parents=True, exist_ok=True)
    app = require(ksapi.GetKompas(), "Нет API-сессии КОМПАС")
    previous, doc = app.GetActiveDocument(), None
    try:
        doc = require(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart, True), "Деталь")
        part = ksapi.IKompasDocument3D(doc).GetTopPart()
        build(part, part.GetModelContainer())
        bounds = validate(part)
        if output:
            require(doc.SaveAs(str(output)), "Сохранение")
            require(output.is_file() and output.stat().st_size > 0, "Файл не записан")
        print(f"PASS: поворот и перенос; габариты {bounds}")
    finally:
        if doc:
            require(doc.Close(c.kdDoNotSaveChanges), "Закрытие своей детали")
        if previous:
            previous.SetActive()


if __name__ == "__main__":
    main()
