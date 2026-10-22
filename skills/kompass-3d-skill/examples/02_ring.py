# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Кольцо R25 с отверстием R5, толщина 10 мм; без --output — временное."""
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


T = TypeVar("T")
Bounds = tuple[float, float, float, float, float, float]


def require(value: T | None, message: str) -> T:
    if not value:
        raise RuntimeError(message)
    return value


@contextmanager
def sketch_xoy(
    part: ksapi.IPart, model: ksapi.IModelContainer,
) -> Iterator[tuple[ksapi.ISketch, ksapi.IDrawingContainer]]:
    sketch = require(model.GetSketchs().Add(), "Эскиз")
    sketch.SetPlane(require(part.GetDefaultObject(c3d.o3d_planeXOY), "Плоскость XOY"))
    require(sketch.Update(), "Плоскость эскиза")
    fragment = require(sketch.BeginEdit(False), "Редактирование эскиза")
    try:
        view = require(fragment.GetViewsAndLayersManager().GetViews().GetActiveView(), "Вид эскиза")
        yield sketch, require(ksapi.IDrawingContainer(view), "Геометрия эскиза")
    finally:
        require(sketch.EndEdit(), "Завершение эскиза")


def circle(
    drawing: ksapi.IDrawingContainer, x: float, y: float, radius: float,
) -> ksapi.ICircle:
    obj = require(drawing.GetCircles().Add(), "Окружность")
    obj.SetXc(x)
    obj.SetYc(y)
    obj.SetRadius(radius)
    require(obj.Update(), "Обновление окружности")
    return obj


def extrude(
    model: ksapi.IModelContainer, sketch: ksapi.ISketch, depth: float,
) -> ksapi.IExtrusion:
    operation = require(model.GetExtrusions().Add(c3d.o3d_bossExtrusion), "Выдавливание")
    operation.SetProfiles([sketch])
    operation.SetDirection(c3d.dtNormal)
    require(operation.SetSideParameters(True, c3d.etBlind, depth, 0.0, False, None), "Глубина")
    require(operation.Update(), "Построение операции")
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


def verify_cylindrical_walls(
    part: ksapi.IPart, expected: Sequence[tuple[float, float, float, float, float]],
    *, tolerance: float = 1e-5,
) -> None:
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


def build(part: ksapi.IPart, model: ksapi.IModelContainer) -> ksapi.IExtrusion:
    """Выдавить эскиз с двумя концентрическими окружностями."""
    with sketch_xoy(part, model) as (profile, drawing):
        circle(drawing, 0, 0, 25)
        circle(drawing, 0, 0, 5)
    return extrude(model, profile, 10)


def validate(part: ksapi.IPart) -> Bounds:
    """Проверить тело, габариты, обе стенки и дерево; вернуть габариты."""
    require(part.RebuildModel(True), "Перестроение")
    bodies = require(ksapi.IFeature(part), "Топология детали").GetResultBodies()
    require(len(bodies) == 1, f"Ожидалось одно тело, получено {len(bodies)}")
    require(bodies[0].IsSolid(), "Тело не твёрдое")
    result = bodies[0].GetGabarit(0, 0, 0, 0, 0, 0)
    require(result[0], "Габариты")
    bounds = tuple(result[1:])
    expected = (-25, -25, 0, 25, 25, 10)
    require(len(bounds) == 6 and all(math.isfinite(a) and abs(a - b) <= 1e-5
                                   for a, b in zip(bounds, expected)), f"Габариты: {bounds}")
    verify_cylindrical_walls(part, [(0, 0, 25, 0, 10), (0, 0, 5, 0, 10)])
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
        part.SetName("02 — Кольцо")
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
