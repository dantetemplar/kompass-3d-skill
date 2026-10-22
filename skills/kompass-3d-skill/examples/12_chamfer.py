# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Пластина 60 × 40 × 10 мм с фасками 2 × 2 мм на четырёх вертикальных рёбрах."""
from __future__ import annotations

import argparse
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
import math
from pathlib import Path
from typing import TypeVar

import ksapi
from constants import constants as c
from constants3d import constants as c3d


TOLERANCE = 1e-5


T = TypeVar("T")
Point3D = tuple[float, float, float]
Bounds = tuple[float, float, float, float, float, float]


def require(value: T | None, message: str) -> T:
    if not value:
        raise RuntimeError(message)
    return value


@contextmanager
def sketch_xoy(part: ksapi.IPart, model: ksapi.IModelContainer) -> Iterator[tuple[ksapi.ISketch, ksapi.IDrawingContainer]]:
    sketch = require(model.GetSketchs().Add(), "Эскиз")
    sketch.SetPlane(require(part.GetDefaultObject(c3d.o3d_planeXOY), "Плоскость XOY"))
    require(sketch.Update(), "Плоскость эскиза")
    fragment = require(sketch.BeginEdit(False), "Редактирование эскиза")
    try:
        view = require(fragment.GetViewsAndLayersManager().GetViews().GetActiveView(), "Вид эскиза")
        yield sketch, require(ksapi.IDrawingContainer(view), "Геометрия эскиза")
    finally:
        require(sketch.EndEdit(), "Завершение эскиза")


def rectangle(drawing: ksapi.IDrawingContainer, x: float, y: float, width: float, height: float) -> ksapi.IRectangle:
    obj = require(drawing.GetRectangles().Add(), "Прямоугольник")
    obj.SetX(x)
    obj.SetY(y)
    obj.SetWidth(width)
    obj.SetHeight(height)
    require(obj.Update(), "Обновление прямоугольника")
    return obj


def extrude(model: ksapi.IModelContainer, sketch: ksapi.ISketch, depth: float) -> ksapi.IExtrusion:
    operation = require(model.GetExtrusions().Add(c3d.o3d_bossExtrusion), "Выдавливание")
    operation.SetProfiles([sketch])
    operation.SetDirection(c3d.dtNormal)
    require(operation.SetSideParameters(True, c3d.etBlind, depth, 0.0, False, None), "Глубина")
    require(operation.Update(), "Построение выдавливания")
    return operation


def feature_errors(part: ksapi.IPart) -> list[tuple[list[str], int]]:
    """Проверить все ветви дерева, включая скрытые эскизы."""
    errors, seen = [], set()

    def visit(feature: ksapi.IFeature, path: Sequence[str]) -> None:
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


def points_close(first: Sequence[float], second: Sequence[float], *, tolerance: float = TOLERANCE) -> bool:
    return len(first) == len(second) == 3 and all(
        math.isfinite(a) and math.isfinite(b) and abs(a - b) <= tolerance
        for a, b in zip(first, second)
    )


def edge_points(edge: ksapi.IEdge) -> list[Point3D]:
    points = []
    for start in (True, False):
        result = edge.GetPoint(start, 0, 0, 0)
        require(result[0], "Конечная точка ребра")
        point = tuple(result[1:])
        require(len(point) == 3 and all(math.isfinite(v) for v in point),
                f"Некорректная точка ребра: {point}")
        points.append(point)
    return points


def corner_edges(part: ksapi.IPart) -> list[ksapi.IEdge]:
    """Выбрать ровно четыре прямых ребра (±30, ±20, Z=0…10)."""
    feature = require(ksapi.IFeature(part), "Топология исходной пластины")
    found = {}
    for obj in feature.GetModelObjects([c3d.o3d_edge]):
        edge = require(ksapi.IEdge(obj), "Ребро")
        if not edge.IsStraight():
            continue
        first, last = sorted(edge_points(edge), key=lambda p: p[2])
        for sx in (-1, 1):
            for sy in (-1, 1):
                if (points_close(first, (sx * 30, sy * 20, 0))
                        and points_close(last, (sx * 30, sy * 20, 10))):
                    require((sx, sy) not in found, f"Дублированное ребро угла {(sx, sy)}")
                    found[sx, sy] = edge
    require(len(found) == 4, f"Ожидалось четыре вертикальных угловых ребра: {list(found)}")
    return list(found.values())


def build(part: ksapi.IPart, model: ksapi.IModelContainer) -> ksapi.IChamfer:
    """Выдавить пластину и снять 2 × 2 мм с каждого вертикального угла."""
    with sketch_xoy(part, model) as (profile, drawing):
        rectangle(drawing, -30, -20, 60, 40)
    extrude(model, profile, 10)
    require(part.RebuildModel(True), "Перестроение исходной пластины")
    edges = corner_edges(part)
    chamfer = require(model.GetChamfers().Add(), "Фаска")
    chamfer.SetBaseObjects(edges)
    chamfer.SetBuildingType(c3d.ksChamferTwoSides)
    chamfer.SetDistance1(2.0)
    chamfer.SetDistance2(2.0)
    chamfer.SetTangent(False)
    require(chamfer.Update(), "Построение фаски")
    return chamfer


def verify_chamfer_faces(part: ksapi.IPart) -> None:
    """Проверить четыре диагональных прямоугольника по вершинам и площади."""
    feature = require(ksapi.IFeature(part), "Топология конечной детали")
    faces = feature.GetModelObjects([c3d.o3d_face])
    require(len(faces) == 10, f"Ожидалось десять граней, получено {len(faces)}")
    expected = {
        (sx, sy): [(sx * x, sy * y, z)
                   for x, y in ((30 - 2, 20), (30, 20 - 2)) for z in (0, 10)]
        for sx in (-1, 1) for sy in (-1, 1)
    }
    found = set()
    for obj in faces:
        face = require(ksapi.IFace(obj), "Грань")
        require(face.IsPlanar(), "В конечной пластине обнаружена неплоская грань")
        vertices = []
        edges = face.GetLimitingEdges()
        for edge in edges:
            require(edge.IsStraight(), "Граница плоской грани не прямая")
            for point in edge_points(edge):
                if not any(points_close(point, old) for old in vertices):
                    vertices.append(point)
        require(vertices, "Грань без вершин")
        spans = [max(p[i] for p in vertices) - min(p[i] for p in vertices) for i in range(3)]
        # Верх/низ и исходные боковые грани имеют постоянную координату.
        if any(span <= TOLERANCE for span in spans):
            continue
        matches = [corner for corner, wanted in expected.items()
                   if len(vertices) == len(wanted)
                   and all(sum(points_close(point, target) for point in vertices) == 1
                           for target in wanted)]
        require(len(matches) == 1 and len(edges) == 4,
                f"Неожиданная диагональная грань: {vertices}")
        corner = matches[0]
        require(corner not in found, f"Повторная грань фаски в углу {corner}")
        # IFace.GetArea принимает API7 ksLengthUnitsEnum: миллиметры — c.ksLUnMM.
        area = face.GetArea(c.ksLUnMM)
        expected_area = 2 * math.sqrt(2) * 10
        require(math.isfinite(area) and abs(area - expected_area) <= TOLERANCE,
                f"Площадь фаски {corner}: {area}, ожидалось {expected_area} мм²")
        found.add(corner)
    require(found == set(expected), f"Не подтверждены четыре фаски: {sorted(found)}")


def verify_volume(part: ksapi.IPart) -> None:
    """Рассчитать объём конечной детали через нативный интерфейс МЦХ."""
    inertia = require(ksapi.IMassInertiaParam(part), "Массово-центровочные характеристики")
    # Native IMassInertiaParam(part) соответствует API7: 1 = мм, 0 = см.
    inertia.SetLengthUnits(c.ksLUnMM)
    require(inertia.GetLengthUnits() == c.ksLUnMM, "Единицы МЦХ не миллиметры")
    require(inertia.Calculate(), "Расчёт объёма детали")
    require(inertia.IsActual(), "Объём детали не актуален")
    volume = inertia.GetVolume()
    expected = 60 * 40 * 10 - 4 * (2 * 2 / 2) * 10
    require(math.isfinite(volume) and abs(volume - expected) <= 1e-3,
            f"Объём: {volume}, ожидалось {expected} мм³")


def validate(part):
    """Проверить конечное тело, фаски, объём и дерево; вернуть кортеж габаритов."""
    require(part.RebuildModel(True), "Перестроение")
    bodies = require(ksapi.IFeature(part), "Топология детали").GetResultBodies()
    require(len(bodies) == 1, f"Ожидалось одно тело, получено {len(bodies)}")
    require(bodies[0].IsSolid(), "Тело не твёрдое")
    result = bodies[0].GetGabarit(0, 0, 0, 0, 0, 0)
    require(result[0], "Габариты")
    bounds = tuple(result[1:])
    expected = (-30, -20, 0, 30, 20, 10)
    require(len(bounds) == 6 and all(math.isfinite(a) and abs(a - b) <= TOLERANCE
                                   for a, b in zip(bounds, expected)), f"Габариты: {bounds}")
    verify_chamfer_faces(part)
    verify_volume(part)
    errors = feature_errors(part)
    require(not errors, f"Ошибки дерева операций: {errors}")
    return bounds


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Новый файл .m3d; без него — временная деталь")
    args = parser.parse_args(argv)
    output = args.output.expanduser().resolve() if args.output is not None else None
    if output is not None:
        if output.suffix.lower() != ".m3d":
            parser.error("Нужен файл .m3d")
        if output.exists():
            parser.error(f"Файл уже существует: {output}")

    app = require(ksapi.GetKompas(), "Нет запущенной API-сессии КОМПАС")
    previous = app.GetActiveDocument()
    doc = None
    try:
        doc = require(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart, True), "Новая деталь")
        part = require(ksapi.IKompasDocument3D(doc).GetTopPart(), "Верхний компонент")
        part.SetName("12 — Четыре фаски 2 × 2 мм")
        model = require(part.GetModelContainer(), "Контейнер модели")
        build(part, model)
        bounds = validate(part)
        if output is not None:
            if output.exists():
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
