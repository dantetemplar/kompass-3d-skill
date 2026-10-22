# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Пластина 60 × 40 × 10 и JPEG текущего вида (изометрия, 640 × 480).

Нужен --output с новым путём .jpg. Не перезаписывает существующий файл.
"""
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


def rectangle(
    drawing: ksapi.IDrawingContainer, x: float, y: float, width: float, height: float,
) -> ksapi.IRectangle:
    obj = require(drawing.GetRectangles().Add(), "Прямоугольник")
    obj.SetX(x)
    obj.SetY(y)
    obj.SetWidth(width)
    obj.SetHeight(height)
    require(obj.Update(), "Обновление прямоугольника")
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
    errors: list[tuple[list[str], int]] = []
    seen: set[int] = set()

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


def build(part: ksapi.IPart, model: ksapi.IModelContainer) -> ksapi.IExtrusion:
    with sketch_xoy(part, model) as (profile, drawing):
        rectangle(drawing, -30, -20, 60, 40)
    return extrude(model, profile, 10)


def validate(part: ksapi.IPart) -> Bounds:
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


def save_view_jpeg(
    doc: ksapi.IKompasDocument, target: Path, width: int = 640, height: int = 480,
) -> Path:
    """JPEG текущего вида в новый путь: изометрия, shaded+wire, zoom all."""
    target = target.expanduser().absolute()
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"Не перезаписываем JPEG: {target}")
    require(target.suffix.lower() in {".jpg", ".jpeg"}, "Нужен путь .jpg")
    doc.SetActive()
    doc3d = ksapi.IKompasDocument3D(doc)
    manager = doc3d.GetViewProjectionManager()
    projections = [manager.GetViewProjection(i) for i in range(manager.GetCount())]
    isometric = [v for v in projections if v and v.GetViewProjectonType() == c3d.ksVPIsometric]
    require(len(isometric) == 1, "Не найдена стандартная изометрия")
    isometric[0].SetCurrent(True)
    require(isometric[0].IsCurrent(), "Изометрия не стала текущей")
    frame = require(doc.GetDocumentFrame(), "Окно документа")
    for command in (c.ksCMShadedWireframeMode, c.ksCMZoomEntireDocument):
        require(frame.IsKompasCommandEnable(command), f"Недоступна команда вида {command}")
        require(frame.ExecuteKompasCommand(command, False), f"Вид {command}")
    raw = require(doc.GetInterface(c.ksObjectRasterConvertParameters), "Параметры растра")
    parameters = ksapi.IRasterConvertParameters(raw)
    require(parameters.Clear(), "Параметры JPEG")
    parameters.SetRasterFormat(c.ksRasterFormatJPG)
    parameters.SetColorBPP(24)
    scale = parameters.CalcRasterScale(doc, width, height)
    require(math.isfinite(scale) and scale > 0, "Масштаб JPEG")
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"Путь JPEG занят во время подготовки: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    require(doc.SaveAsToRasterFormat(str(target), parameters), "Экспорт JPEG из КОМПАС")
    require(target.is_file() and target.stat().st_size > 0, "Нет JPEG")
    require(target.read_bytes()[:3] == b"\xff\xd8\xff", "Файл не JPEG")
    return target


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Новый файл .jpg")
    args = parser.parse_args(argv)
    output = args.output.expanduser().resolve()
    if output.suffix.lower() not in {".jpg", ".jpeg"}:
        parser.error("Нужен файл .jpg")
    if output.exists():
        parser.error(f"Файл уже существует: {output}")

    app = require(ksapi.GetKompas(), "Нет запущенной API-сессии КОМПАС")
    previous = app.GetActiveDocument()
    doc = None
    try:
        doc = require(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart, True), "Новая деталь")
        part = require(ksapi.IKompasDocument3D(doc).GetTopPart(), "Верхний компонент")
        part.SetName("17 — JPEG вида")
        model = require(part.GetModelContainer(), "Контейнер модели")
        build(part, model)
        bounds = validate(part)
        jpeg = save_view_jpeg(doc, output)
        print(f"Проверено: {bounds}; JPEG: {jpeg} ({jpeg.stat().st_size} байт)")
    finally:
        try:
            if doc is not None:
                require(doc.Close(c.kdDoNotSaveChanges), "Закрытие собственной детали")
        finally:
            if previous:
                previous.SetActive()


if __name__ == "__main__":
    main()
