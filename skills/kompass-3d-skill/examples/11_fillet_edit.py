# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Пластина 60 × 40 × 10: четыре скругления R3, затем правка того же признака на R5."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import math
from pathlib import Path

import ksapi
from constants import constants as c
from constants3d import constants as c3d


def require(value, message):
    if not value:
        raise RuntimeError(message)
    return value


@contextmanager
def sketch_xoy(part, model):
    sketch = require(model.GetSketchs().Add(), "Эскиз")
    sketch.SetPlane(require(part.GetDefaultObject(c3d.o3d_planeXOY), "XOY"))
    require(sketch.Update(), "Плоскость эскиза")
    fragment = require(sketch.BeginEdit(False), "Редактирование эскиза")
    try:
        view = fragment.GetViewsAndLayersManager().GetViews().GetActiveView()
        yield sketch, require(ksapi.IDrawingContainer(view), "Геометрия эскиза")
    finally:
        require(sketch.EndEdit(), "Завершение эскиза")


def feature_errors(part):
    errors, seen = [], set()

    def visit(feature):
        if feature.reference in seen:
            return
        seen.add(feature.reference)
        error = feature.GetObjectError()
        if error:
            errors.append((feature.GetName(), error))
        for child in feature.GetSubFeatures(c.ksOperTree, True, True):
            if child:
                visit(child)

    visit(require(ksapi.IFeature(part), "Дерево"))
    return errors


def vertical_corner_edges(part):
    """Выбрать исходные четыре ребра по двум концам, не по порядку коллекции."""
    selected = []
    for obj in ksapi.IFeature(part).GetModelObjects([c3d.o3d_edge]):
        edge = ksapi.IEdge(obj)
        if not edge.IsStraight():
            continue
        start = edge.GetPoint(True, 0, 0, 0)
        end = edge.GetPoint(False, 0, 0, 0)
        require(start[0] and end[0], "Концы ребра")
        p, q = start[1:], end[1:]
        if (abs(abs(p[0]) - 30) < 1e-5 and abs(abs(p[1]) - 20) < 1e-5
                and abs(p[0] - q[0]) < 1e-5 and abs(p[1] - q[1]) < 1e-5
                and abs(min(p[2], q[2])) < 1e-5
                and abs(max(p[2], q[2]) - 10) < 1e-5):
            selected.append(edge)
    require(len(selected) == 4, f"Нужно четыре угловых ребра, получено {len(selected)}")
    return selected


def verify_rounds(part, radius):
    """Проверить радиус, положение и четверть цилиндра у каждого угла."""
    faces = [ksapi.IFace(obj) for obj in ksapi.IFeature(part).GetModelObjects([c3d.o3d_face])]
    cylinders = [face for face in faces if face.IsCylinder()]
    require(len(cylinders) == 4, f"Цилиндрических граней: {len(cylinders)}, нужно 4")
    actual = []
    for face in cylinders:
        require(abs(face.GetRadius() - radius) <= 1e-5, "Радиус поверхности")
        require(abs(face.GetArea(c.ksLUnMM) - math.pi * radius * 10 / 2) <= 1e-5,
                "Площадь четверти цилиндра")
        bounds = face.GetMathSurface().GetGabarit(0, 0, 0, 0, 0, 0)
        require(bounds[0], "Габариты скругления")
        actual.append(tuple(bounds[1:]))
    for sx in (-1, 1):
        for sy in (-1, 1):
            xs, ys = sorted((sx * 30, sx * (30 - radius))), sorted((sy * 20, sy * (20 - radius)))
            expected = (xs[0], ys[0], 0, xs[1], ys[1], 10)
            matches = [i for i, box in enumerate(actual)
                       if all(math.isfinite(a) and abs(a - b) <= 1e-5 for a, b in zip(box, expected))]
            require(len(matches) == 1, f"Скругление расположено не у нужного угла: {expected}; {actual}")
            actual.pop(matches[0])


def build(part, model):
    with sketch_xoy(part, model) as (profile, drawing):
        rectangle = require(drawing.GetRectangles().Add(), "Прямоугольник")
        rectangle.SetX(-30)
        rectangle.SetY(-20)
        rectangle.SetWidth(60)
        rectangle.SetHeight(40)
        require(rectangle.Update(), "Прямоугольник")
    extrusion = require(model.GetExtrusions().Add(c3d.o3d_bossExtrusion), "Выдавливание")
    extrusion.SetProfiles([profile])
    extrusion.SetDirection(c3d.dtNormal)
    require(extrusion.SetSideParameters(True, c3d.etBlind, 10, 0, False, None), "Глубина")
    require(extrusion.Update(), "Выдавливание")
    require(part.RebuildModel(True), "Исходная пластина")
    fillet = require(model.GetFillets().Add(), "Скругление")
    fillet.SetBaseObjects(vertical_corner_edges(part))
    fillet.SetBuildingType(c3d.ksFilletCircleArc)
    fillet.SetRadius1(3)
    fillet.SetTangent(False)
    require(fillet.Update(), "Скругление R3")
    require(part.RebuildModel(True), "Перестроение R3")
    verify_rounds(part, 3)
    # Не пересоздаём операцию и не предъявляем старые рёбра тела после перестроения.
    reference = fillet.reference
    fillet = require(model.GetFillets().GetFillet(0), "Живой признак")
    require(fillet.reference == reference, "Правка должна сохранить признак")
    fillet.SetRadius1(5)
    require(fillet.Update(), "Правка R3 → R5")
    validate(part)
    return fillet


def validate(part):
    require(part.RebuildModel(True), "Перестроение")
    bodies = ksapi.IFeature(part).GetResultBodies()
    require(len(bodies) == 1 and bodies[0].IsSolid(), "Нужно одно твёрдое тело")
    result = bodies[0].GetGabarit(0, 0, 0, 0, 0, 0)
    require(result[0], "Габариты")
    bounds = tuple(result[1:])
    require(len(bounds) == 6 and all(math.isfinite(a) and abs(a - b) <= 1e-5
            for a, b in zip(bounds, (-30, -20, 0, 30, 20, 10))), f"Габариты: {bounds}")
    verify_rounds(part, 5)
    # МЦХ считаем впервые после финальной правки: промежуточный расчёт может остаться в кэше.
    inertia = require(ksapi.IMassInertiaParam(part), "МЦХ детали")
    inertia.SetLengthUnits(c.ksLUnMM)
    require(inertia.Calculate(), "Расчёт объёма")
    volume = inertia.GetVolume()
    expected_volume = 60 * 40 * 10 - 4 * (1 - math.pi / 4) * 5**2 * 10
    require(math.isfinite(volume) and abs(volume - expected_volume) <= 1e-5,
            f"Объём: {volume}; ожидалось {expected_volume}")
    fillets = part.GetModelContainer().GetFillets()
    require(fillets.GetCount() == 1, "Признак скругления должен остаться единственным")
    fillet = require(fillets.GetFillet(0), "Скругление")
    require(abs(fillet.GetRadius1() - 5) <= 1e-5 and len(fillet.GetBaseObjects()) == 4,
            "Параметры скругления")
    errors = feature_errors(part)
    require(not errors, f"Ошибки дерева: {errors}")
    return bounds


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Новый файл .m3d; без него — временная деталь")
    args = parser.parse_args(argv)
    output = args.output.expanduser().resolve() if args.output is not None else None
    if output is not None and (output.suffix.lower() != ".m3d" or output.exists()):
        parser.error("Нужен новый файл .m3d")
    app = require(ksapi.GetKompas(), "Нет запущенной API-сессии КОМПАС")
    previous, doc = app.GetActiveDocument(), None
    try:
        doc = require(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart, True), "Новая деталь")
        part = require(ksapi.IKompasDocument3D(doc).GetTopPart(), "Деталь")
        part.SetName("11 — Скругление с правкой радиуса")
        build(part, part.GetModelContainer())
        bounds = validate(part)
        if output is not None:
            if output.exists():
                raise FileExistsError(output)
            output.parent.mkdir(parents=True, exist_ok=True)
            require(doc.SaveAs(str(output)), "Сохранение")
            require(output.is_file() and output.stat().st_size > 0, "Нет файла результата")
        print(f"Проверено: {bounds}; файл: {output or 'временная деталь'}")
    finally:
        try:
            if doc is not None:
                require(doc.Close(c.kdDoNotSaveChanges), "Закрытие своей детали")
        finally:
            if previous:
                previous.SetActive()


if __name__ == "__main__":
    main()
