# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Коробка 60 × 40 × 20 мм: оболочка внутрь 2 мм с открытым верхом Z=20.

Native KsAPI Linux v25. Полость: X=±28, Y=±18, дно Z=2.
Объём материала: 60*40*20 - 56*36*18 = 11712 мм³.
Проверка рассчитана на прямоугольные грани без скруглений и разбиений.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import math
from pathlib import Path

import ksapi
from constants import constants as c
from constants3d import constants as c3d


TOLERANCE = 1e-5


def require(value, message):
    if not value:
        raise RuntimeError(message)
    return value


def close_values(actual, expected, tolerance=TOLERANCE):
    return len(actual) == len(expected) and all(
        math.isfinite(a) and abs(a - b) <= tolerance for a, b in zip(actual, expected)
    )


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


def edge_points(edge):
    require(edge.IsStraight(), "Ожидалось прямое ребро коробки")
    points = []
    for start in (True, False):
        result = edge.GetPoint(start, 0, 0, 0)
        require(result[0], "Конец ребра")
        point = tuple(result[1:])
        require(len(point) == 3 and all(math.isfinite(v) for v in point),
                f"Неконечный конец ребра: {point}")
        points.append(point)
    return tuple(points)


def edges_bounds(edges):
    points = [point for edge in edges for point in edge_points(edge)]
    require(points, "Граница грани пуста")
    return tuple(min(p[i] for p in points) for i in range(3)) + tuple(
        max(p[i] for p in points) for i in range(3)
    )


def planar_faces(part):
    """Читать конечные грани детали заново после изменения топологии."""
    feature = require(ksapi.IFeature(part), "Топология детали")
    result = []
    for obj in feature.GetModelObjects([c3d.o3d_face]):
        face = require(ksapi.IFace(obj), "Грань")
        require(face.IsPlanar(), "Ожидались только плоские грани коробки")
        result.append((face, edges_bounds(face.GetLimitingEdges())))
    require(result, "Нет конечных граней детали")
    return result


def verify_rectangle_edges(edges, bounds):
    """Проверить четыре стороны именно заданного прямоугольника в 3D."""
    axes = [i for i in range(3) if abs(bounds[i + 3] - bounds[i]) > TOLERANCE]
    require(len(axes) == 2, f"Не прямоугольная плоская область: {bounds}")
    a, b = axes
    corners = []
    for high_a, high_b in ((False, False), (True, False), (True, True), (False, True)):
        point = list(bounds[:3])
        point[a] = bounds[a + 3] if high_a else bounds[a]
        point[b] = bounds[b + 3] if high_b else bounds[b]
        corners.append(tuple(point))
    expected = [(corners[i], corners[(i + 1) % 4]) for i in range(4)]
    require(len(edges) == 4, f"Ожидались четыре стороны: {bounds}")
    for edge in edges:
        p, q = edge_points(edge)
        matches = [i for i, (u, v) in enumerate(expected)
                   if (close_values(p, u) and close_values(q, v))
                   or (close_values(p, v) and close_values(q, u))]
        require(len(matches) == 1, f"Ребро {p, q} не принадлежит прямоугольнику {bounds}")
        expected.pop(matches[0])
    require(not expected, f"Неполный прямоугольник: {bounds}")


def verify_rectangle_face(face, bounds):
    loops = face.GetLoops()
    require(len(loops) == 1, f"Лишние отверстия в прямоугольной грани: {bounds}")
    verify_rectangle_edges(loops[0].GetEdges(), bounds)
    spans = [bounds[i + 3] - bounds[i] for i in range(3)
             if bounds[i + 3] - bounds[i] > TOLERANCE]
    area = face.GetArea(c.ksLUnMM)
    require(close_values((area,), (math.prod(spans),)), f"Площадь грани {bounds}: {area}")


def build(part, model):
    """Выдавить блок и удалить верхнюю грань нативной операцией IShell."""
    with sketch_xoy(part, model) as (profile, drawing):
        rectangle(drawing, -30, -20, 60, 40)
    extrusion = require(model.GetExtrusions().Add(c3d.o3d_bossExtrusion), "Выдавливание")
    extrusion.SetProfiles([profile])
    extrusion.SetDirection(c3d.dtNormal)
    require(extrusion.SetSideParameters(True, c3d.etBlind, 20, 0.0, False, None), "Глубина")
    require(extrusion.Update(), "Построение блока")
    require(part.RebuildModel(True), "Перестроение блока")
    top_bounds = (-30, -20, 20, 30, 20, 20)
    tops = [face for face, bounds in planar_faces(part) if close_values(bounds, top_bounds)]
    require(len(tops) == 1, "Не найдена единственная верхняя грань блока Z=20")
    verify_rectangle_face(tops[0], top_bounds)

    shell = require(model.GetShells().Add(), "Оболочка IShell")
    # Linux v25: SetDeletedFaces(faces, tangentFaces), не Windows SetFaces.
    # Эти setters возвращают None; bool-проверка нужна у Update(), не у setters.
    shell.SetDeletedFaces(tops, False)
    shell.SetThinType(c3d.dtReverse)  # Для тонкой стенки dtReverse означает внутрь.
    shell.SetThickness(2.0)
    require(shell.GetThinType() == c3d.dtReverse
            and close_values((shell.GetThickness(),), (2.0,)), "Параметры оболочки")
    require(len(shell.GetDeletedFaces()) == 1, "Не назначена удаляемая верхняя грань")
    require(shell.Update(), "Построение оболочки")
    return shell


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


def verify_cavity(part):
    """Проверить расположение полости и два контура открытого верхнего ободка."""
    remaining = planar_faces(part)
    # Пять внешних граней и пять внутренних: не только число, но координаты,
    # прямоугольные границы без отверстий и площадь каждой грани.
    rectangles = (
        (-30, -20, 0, 30, 20, 0),
        (-30, -20, 0, -30, 20, 20), (30, -20, 0, 30, 20, 20),
        (-30, -20, 0, 30, -20, 20), (-30, 20, 0, 30, 20, 20),
        (-28, -18, 2, 28, 18, 2),
        (-28, -18, 2, -28, 18, 20), (28, -18, 2, 28, 18, 20),
        (-28, -18, 2, 28, -18, 20), (-28, 18, 2, 28, 18, 20),
    )
    for expected in rectangles:
        matches = [i for i, (_, bounds) in enumerate(remaining) if close_values(bounds, expected)]
        require(len(matches) == 1, f"Не подтверждена грань коробки/полости: {expected}")
        face, _ = remaining.pop(matches[0])
        verify_rectangle_face(face, expected)

    # Плоская грань на Z=20 допустима и необходима: это ободок, а не крышка.
    require(len(remaining) == 1, "Ожидался только верхний ободок без лишних граней")
    rim, bounds = remaining[0]
    outer = (-30, -20, 20, 30, 20, 20)
    inner = (-28, -18, 20, 28, 18, 20)
    require(close_values(bounds, outer), f"Положение ободка: {bounds}")
    loops = list(rim.GetLoops())
    require(len(loops) == 2, "Ободок должен иметь внешний контур и открытое устье полости")
    for expected, is_outer in ((outer, True), (inner, False)):
        matches = [i for i, loop in enumerate(loops)
                   if close_values(edges_bounds(loop.GetEdges()), expected)]
        require(len(matches) == 1, f"Не подтверждён контур ободка: {expected}")
        loop = loops.pop(matches[0])
        require(bool(loop.IsOuter()) == is_outer, "Перепутаны внешний контур и устье полости")
        verify_rectangle_edges(loop.GetEdges(), expected)
    area = rim.GetArea(c.ksLUnMM)
    require(close_values((area,), (60 * 40 - 56 * 36,)), f"Площадь ободка: {area}")


def validate(part):
    """Проверить конечное тело, полость, объём и дерево; вернуть bounds tuple."""
    require(part.RebuildModel(True), "Перестроение")
    bodies = require(ksapi.IFeature(part), "Топология детали").GetResultBodies()
    require(len(bodies) == 1, f"Ожидалось одно конечное тело, получено {len(bodies)}")
    require(bodies[0].IsSolid(), "Тело не твёрдое")
    result = bodies[0].GetGabarit(0, 0, 0, 0, 0, 0)
    require(result[0], "Габариты")
    bounds = tuple(result[1:])
    require(close_values(bounds, (-30, -20, 0, 30, 20, 20)), f"Габариты: {bounds}")
    verify_cavity(part)
    mass = require(ksapi.IMassInertiaParam(part), "Массово-центровочные характеристики")
    # Native IMassInertiaParam(part) использует API7 ksLengthUnitsEnum: 1=мм.
    mass.SetLengthUnits(c.ksLUnMM)
    require(mass.GetLengthUnits() == c.ksLUnMM, "Единицы объёма: мм³")
    require(mass.Calculate(), "Расчёт объёма")
    require(mass.IsActual(), "Объём не актуален")
    volume = mass.GetVolume()
    expected_volume = 60 * 40 * 20 - 56 * 36 * 18  # 11712 мм³, не сумма AABB.
    require(close_values((volume,), (expected_volume,)), f"Объём: {volume}; нужно {expected_volume} мм³")
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
        part.SetName("14 — Оболочка внутрь 2 мм")
        model = require(part.GetModelContainer(), "Контейнер модели")
        build(part, model)
        bounds = validate(part)
        if output is not None:
            if output.exists():
                raise FileExistsError(f"Не перезаписываем {output}")
            output.parent.mkdir(parents=True, exist_ok=True)
            require(doc.SaveAs(str(output)), "Сохранение")
            require(output.is_file() and output.stat().st_size > 0, "Файл результата отсутствует")
        print(f"Проверено: {bounds}; объём: 11712 мм³; файл: {output or 'временная деталь'}")
    finally:
        try:
            if doc is not None:
                require(doc.Close(c.kdDoNotSaveChanges), "Закрытие собственной детали")
        finally:
            if previous:
                previous.SetActive()


if __name__ == "__main__":
    main()
