# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Пластина 60 × 40 × 10 мм; без --output документ временный."""
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


def extrude(model, sketch, depth):
    operation = require(model.GetExtrusions().Add(c3d.o3d_bossExtrusion), "Выдавливание")
    operation.SetProfiles([sketch])
    operation.SetDirection(c3d.dtNormal)
    require(operation.SetSideParameters(True, c3d.etBlind, depth, 0.0, False, None), "Глубина")
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


def build(part, model):
    """Построить редактируемые эскиз и выдавливание."""
    with sketch_xoy(part, model) as (profile, drawing):
        rectangle(drawing, -30, -20, 60, 40)
    return extrude(model, profile, 10)


def validate(part):
    """Проверить тело, координаты габаритов и дерево; вернуть габариты."""
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
    errors = feature_errors(part)
    require(not errors, f"Ошибки дерева операций: {errors}")
    return bounds


def main(argv=None):
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
        part.SetName("01 — Пластина")
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
