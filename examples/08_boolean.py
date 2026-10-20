# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Вычитание тел: из цилиндра Ø30 × 10 вычесть цилиндр Ø10 × 10.

Без аргументов — временная деталь; --output /новый/путь.m3d сохраняет её.
Каждый цилиндр создаётся отдельным телом, затем выполняется одна разность.
"""
import argparse
from pathlib import Path

import ksapi
from constants import constants as c
from constants3d import constants as c3d


def require(value, message):
    if not value:
        raise RuntimeError(message)
    return value


def cylinder(part, model, radius):
    sketch = require(model.GetSketchs().Add(), "Эскиз цилиндра")
    sketch.SetPlane(part.GetDefaultObject(c3d.o3d_planeXOY))
    require(sketch.Update(), "Плоскость эскиза")
    fragment = require(sketch.BeginEdit(False), "Открытие эскиза")
    try:
        view = fragment.GetViewsAndLayersManager().GetViews().GetActiveView()
        drawing = ksapi.IDrawingContainer(view)
        circle = require(drawing.GetCircles().Add(), "Окружность")
        circle.SetXc(0)
        circle.SetYc(0)
        circle.SetRadius(radius)
        require(circle.Update(), "Окружность")
    finally:
        require(sketch.EndEdit(), "Закрытие эскиза")
    operation = require(model.GetExtrusions().Add(c3d.o3d_bossExtrusion), "Цилиндр")
    operation.SetProfiles([sketch])
    operation.SetDirection(c3d.dtNormal)
    operation.SetOperationResult(c3d.ksOperationNewBody)
    require(operation.SetSideParameters(True, c3d.etBlind, 10, 0, False, None), "Высота")
    require(operation.Update(), "Построение цилиндра")
    bodies = ksapi.IFeature(operation).GetResultBodies()
    require(len(bodies) == 1, "Одно исходное тело")
    return bodies[0]


def build(part, model):
    base = cylinder(part, model, 15)
    tool = cylinder(part, model, 5)
    operation = require(model.GetBooleans().Add(), "Булева разность")
    operation.SetBaseObject(base)
    operation.SetModifyObjects([tool])
    operation.SetBooleanType(c.ksDifference)
    operation.SetSaveCopyBaseObject(False)
    operation.SetSaveCopyModifyObjects(False)
    require(operation.Update(), "Вычитание цилиндра")


def validate(part):
    require(part.RebuildModel(True), "Перестроение")
    bodies = ksapi.IFeature(part).GetResultBodies()
    require(len(bodies) == 1 and bodies[0].IsSolid(), "Должна остаться одна втулка")
    bounds = bodies[0].GetGabarit(0, 0, 0, 0, 0, 0)
    expected = (-15, -15, 0, 15, 15, 10)
    require(bounds[0] and all(abs(a - b) < 1e-5 for a, b in zip(bounds[1:], expected)), "Габариты")
    radii = sorted(ksapi.IFace(obj).GetRadius()
                   for obj in ksapi.IFeature(part).GetModelObjects([c3d.o3d_face])
                   if ksapi.IFace(obj).IsCylinder())
    require(len(radii) == 2 and all(abs(a - b) < 1e-5 for a, b in zip(radii, (5, 15))),
            "Нужны наружная стенка R15 и стенка сквозного отверстия R5")
    seen = set()

    def visit(feature):
        if feature.reference in seen:
            return
        seen.add(feature.reference)
        require(feature.GetObjectError() == 0, f"Ошибка: {feature.GetName()}")
        for child in feature.GetSubFeatures(c.ksOperTree, True, True):
            if child:
                visit(child)

    visit(ksapi.IFeature(part))
    return tuple(bounds[1:])


def main():
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
        print(f"PASS: булева разность; габариты {bounds}; отверстие R5")
    finally:
        if doc:
            require(doc.Close(c.kdDoNotSaveChanges), "Закрытие своей детали")
        if previous:
            previous.SetActive()


if __name__ == "__main__":
    main()
