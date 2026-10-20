# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Пластина 60 × 40 × 10 мм с массивом 3 × 2 сквозных отверстий Ø4."""
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
    sketch.SetPlane(require(part.GetDefaultObject(c3d.o3d_planeXOY), "Плоскость XOY"))
    require(sketch.Update(), "Плоскость эскиза")
    fragment = require(sketch.BeginEdit(False), "Редактирование эскиза")
    try:
        view = require(fragment.GetViewsAndLayersManager().GetViews().GetActiveView(), "Вид эскиза")
        yield sketch, require(ksapi.IDrawingContainer(view), "Геометрия эскиза")
    finally:
        require(sketch.EndEdit(), "Завершение эскиза")


def rectangle(drawing, x, y, width, height):
    obj = require(drawing.GetRectangles().Add(), "Прямоугольник")
    obj.SetX(x)
    obj.SetY(y)
    obj.SetWidth(width)
    obj.SetHeight(height)
    require(obj.Update(), "Обновление прямоугольника")
    return obj


def circle(drawing, x, y, radius):
    obj = require(drawing.GetCircles().Add(), "Окружность")
    obj.SetXc(x)
    obj.SetYc(y)
    obj.SetRadius(radius)
    require(obj.Update(), "Обновление окружности")
    return obj


def extrude(model, sketch, depth, *, cut=False):
    operation = require(model.GetExtrusions().Add(
        c3d.o3d_cutExtrusion if cut else c3d.o3d_bossExtrusion
    ), "Выдавливание")
    operation.SetProfiles([sketch])
    # Для выреза с нижней XOY в материал Z>0 нужна обратная сторона.
    operation.SetDirection(c3d.dtReverse if cut else c3d.dtNormal)
    require(operation.SetSideParameters(not cut, c3d.etBlind, depth, 0.0, False, None), "Глубина")
    require(operation.Update(), "Построение операции")
    return operation


def feature_errors(part):
    """Проверить все ветви дерева, включая скрытые эскизы."""
    errors, seen = [], set()

    def visit(feature, path):
        if feature.reference in seen:
            return
        seen.add(feature.reference)
        path = [*path, feature.GetName()]
        error = feature.GetObjectError()
        if error:
            errors.append((path, error))
        for child in feature.GetSubFeatures(c.ksOperTree, True, True):
            if child:
                visit(child, path)

    visit(require(ksapi.IFeature(part), "Дерево детали"), [])
    return errors


def verify_cylindrical_walls(part, expected, *, tolerance=1e-5):
    """Проверить радиусы, центры и высоту простых цилиндров вдоль Z."""
    feature = require(ksapi.IFeature(part), "Топология детали")
    actual = []
    for obj in feature.GetModelObjects([c3d.o3d_face]):
        face = require(ksapi.IFace(obj), "Грань")
        if not face.IsCylinder():
            continue
        rims = []
        for edge in face.GetLimitingEdges():
            if edge.IsCircle():
                curve = require(edge.GetMathCurve(), "Круговая граница цилиндра")
                bounds = curve.GetGabarit(0, 0, 0, 0, 0, 0)
                require(bounds[0], "Габариты круговой границы")
                rims.append(bounds[1:])
        require(len(rims) == 2, "Ожидались две круговые границы цилиндрической стенки")
        radius = face.GetRadius()
        centers = []
        for xmin, ymin, zmin, xmax, ymax, zmax in rims:
            require(all(math.isfinite(v) for v in (xmin, ymin, zmin, xmax, ymax, zmax)),
                    "Неконечные габариты границы")
            require(abs(zmax - zmin) <= tolerance
                    and abs((xmax - xmin) / 2 - radius) <= tolerance
                    and abs((ymax - ymin) / 2 - radius) <= tolerance,
                    "Граница не является окружностью в плоскости XY")
            centers.append(((xmin + xmax) / 2, (ymin + ymax) / 2, (zmin + zmax) / 2))
        require(math.dist(centers[0][:2], centers[1][:2]) <= tolerance,
                "Ось цилиндра не параллельна Z")
        actual.append((*centers[0][:2], radius,
                       min(p[2] for p in centers), max(p[2] for p in centers)))
    require(len(actual) == len(expected),
            f"Цилиндрические стенки: ожидалось {len(expected)}, получено {len(actual)}")
    for wall in expected:
        matches = [i for i, found in enumerate(actual)
                   if all(abs(a - b) <= tolerance for a, b in zip(found, wall))]
        require(len(matches) == 1, f"Не подтверждены центр, радиус или глубина стенки: {wall}")
        actual.pop(matches[0])


def build(part, model):
    """Выдавить пластину, вырезать seed и размножить операцию по OX/OY."""
    with sketch_xoy(part, model) as (profile, drawing):
        rectangle(drawing, -30, -20, 60, 40)
    extrude(model, profile, 10)
    with sketch_xoy(part, model) as (hole, drawing):
        circle(drawing, -20, -10, 2)
    seed = extrude(model, hole, 10, cut=True)

    feature = require(model.GetFeaturePatterns().Add(c3d.o3d_meshCopy), "Массив операций по сетке")
    pattern = require(ksapi.ILinearPattern(feature), "Линейный массив")
    # Сначала источник и оси; только затем параметры сетки.
    pattern.SetInitialObjects([seed])
    pattern.SetAxis1(require(part.GetDefaultObject(c3d.o3d_axisOX), "Ось OX"))
    pattern.SetAxis2(require(part.GetDefaultObject(c3d.o3d_axisOY), "Ось OY"))
    pattern.SetStep1(20.0)
    pattern.SetCount1(3)  # Число экземпляров включает исходную операцию.
    pattern.SetDirection1(True)
    pattern.SetBoundaryInstancesStepFactor1(False)
    pattern.SetStep2(20.0)
    pattern.SetCount2(2)
    pattern.SetDirection2(True)
    pattern.SetBoundaryInstancesStepFactor2(False)
    # Angle2 не задан: сохраняем штатные 90°, а не сводим оба направления к одной оси.
    pattern.SetBuildingType(c.ksLPSaveAll)
    pattern.SetGeometryPattern(False)
    require(pattern.Update(), "Построение линейного массива")
    return pattern


def validate(part):
    """Проверить итоговое тело, габариты, шесть стенок и дерево; вернуть габариты."""
    require(part.RebuildModel(True), "Перестроение")
    bodies = require(ksapi.IFeature(part), "Топология детали").GetResultBodies()
    require(len(bodies) == 1, f"Ожидалось одно тело, получено {len(bodies)}")
    require(bodies[0].IsSolid(), "Тело не твёрдое")
    result = bodies[0].GetGabarit(0, 0, 0, 0, 0, 0)
    require(result[0], "Габариты")
    bounds = tuple(result[1:])
    expected = (-30, -20, 0, 30, 20, 10)
    require(len(bounds) == 6 and all(math.isfinite(a) and abs(a - b) <= 1e-5
                                   for a, b in zip(bounds, expected)), f"Габариты: {bounds}")
    verify_cylindrical_walls(part, [(x, y, 2, 0, 10)
                                    for x in (-20, 0, 20) for y in (-10, 10)])
    inertia = require(ksapi.IMassInertiaParam(part), "МЦХ детали")
    inertia.SetLengthUnits(c.ksLUnMM)
    require(inertia.Calculate(), "Расчёт объёма")
    volume = inertia.GetVolume()
    expected_volume = 60 * 40 * 10 - 6 * math.pi * 2**2 * 10
    require(math.isfinite(volume) and abs(volume - expected_volume) <= 1e-5,
            f"Объём: {volume}; ожидалось {expected_volume}")
    errors = feature_errors(part)
    require(not errors, f"Ошибки дерева операций: {errors}")
    return bounds


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Новый файл .m3d; без него — временная деталь")
    args = parser.parse_args(argv)
    output = args.output.expanduser().absolute() if args.output is not None else None
    if output is not None:
        if output.suffix.lower() != ".m3d":
            parser.error("Нужен файл .m3d")
        if output.exists() or output.is_symlink():
            parser.error(f"Файл уже существует: {output}")

    app = require(ksapi.GetKompas(), "Нет запущенной API-сессии КОМПАС")
    previous = app.GetActiveDocument()
    doc = None
    try:
        doc = require(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart, True), "Новая деталь")
        part = require(ksapi.IKompasDocument3D(doc).GetTopPart(), "Верхний компонент")
        part.SetName("15 — Линейный массив отверстий")
        model = require(part.GetModelContainer(), "Контейнер модели")
        build(part, model)
        bounds = validate(part)
        if output is not None:
            if output.exists() or output.is_symlink():
                raise FileExistsError(f"Не перезаписываем {output}")
            output.parent.mkdir(parents=True, exist_ok=True)
            require(doc.SaveAs(str(output)), "Сохранение")
            require(output.is_file() and output.stat().st_size > 0, "Файл результата отсутствует")
        print(f"Проверено: {bounds}; файл: {output or 'временная деталь'}")
    finally:
        try:
            if doc is not None:
                require(doc.Close(c.kdDoNotSaveChanges), "Закрытие собственной детали")
        finally:
            if previous:
                previous.SetActive()


if __name__ == "__main__":
    main()
