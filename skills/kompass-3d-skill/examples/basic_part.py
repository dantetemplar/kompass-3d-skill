# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Recipe: extruded plate or ring, optional circular pattern of blind/through holes.

Run through uv with the KsAPI environment; only attaches to an existing API session.
All geometry is in millimetres. No existing document is modified.
Cylindrical-wall validation is checked against real ring/holes in the example gallery.
Cuts from the lower XOY sketch require reverse direction and reverse-side depth.
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
Point2 = tuple[float, float]


def require(value: T | None, message: str) -> T:
    if not value:
        raise RuntimeError(message)
    return value


def connect() -> ksapi.IApplication:
    return require(ksapi.GetKompas(), "Нет API-сессии. Запустите КОМПАС командой из SKILL.md.")


def close_owned(owned: list[ksapi.IKompasDocument]) -> None:
    """Close only handles registered by this invocation, never infer ownership."""
    while owned:
        doc = owned[-1]
        require(doc.Close(c.kdDoNotSaveChanges), "Закрытие собственного документа")
        owned.pop()


def new_part(
    app: ksapi.IApplication, name: str, *, owned: list[ksapi.IKompasDocument] | None = None,
) -> tuple[ksapi.IKompasDocument, ksapi.IPart, ksapi.IModelContainer]:
    doc = require(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart, True), "Новая деталь")
    registry = [] if owned is None else owned
    registry.append(doc)  # Before GetTopPart or the first document mutation.
    try:
        part = require(ksapi.IKompasDocument3D(doc).GetTopPart(), "Верхний компонент")
        part.SetName(name)
        return doc, part, require(part.GetModelContainer(), "Контейнер модели")
    except Exception:
        if owned is None:
            close_owned(registry)
        raise


def feature_errors(part: ksapi.IPart) -> list[dict[str, list[str] | int]]:
    """Walk all operation-tree branches, including hidden sketches/components."""
    errors, seen = [], set()

    def visit(feature: ksapi.IFeature, path: Sequence[str]) -> None:
        if feature.reference in seen:
            return
        seen.add(feature.reference)
        path = [*path, feature.GetName()]
        error = feature.GetObjectError()
        if error:
            errors.append({"path": path, "error": error, "state": feature.GetState(),
                           "feature_type": feature.GetFeatureType()})
        for child in feature.GetSubFeatures(c.ksOperTree, True, True):
            if child:
                visit(child, path)

    visit(ksapi.IFeature(part), [])
    return errors


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


def arc(
    drawing: ksapi.IDrawingContainer, center: Point2, radius: float, a1: float, a2: float,
    *, clockwise: bool = False, tolerance: float = 1e-5,
) -> ksapi.IArc:
    """Create an IArc: input angles in radians, KsAPI angles in degrees.

    True means clockwise. Equal angles/full turns require a circle, not an arc.
    Check the actual sweep using its length and start/middle/end points.
    """
    if (not all(math.isfinite(v) for v in (*center, radius, a1, a2, tolerance))
            or radius <= 0 or tolerance <= 0):
        raise ValueError("Дуга: нужны конечные координаты, положительные радиус и допуск")
    sweep = ((a1 - a2) if clockwise else (a2 - a1)) % math.tau
    if sweep == 0:
        raise ValueError("Совпадающие углы: для полной окружности использовать circle")
    obj = require(drawing.GetArcs().Add(), "Дуга")
    obj.SetXc(center[0])
    obj.SetYc(center[1])
    obj.SetRadius(radius)
    obj.SetAngle1(math.degrees(a1) % 360)
    obj.SetAngle2(math.degrees(a2) % 360)
    obj.SetDirection(clockwise)
    require(obj.Update(), "Обновление дуги")
    curve = require(obj.GetCurve2D(), "Математическая дуга")
    length = curve.GetLength()
    require(math.isfinite(length) and abs(length - radius * sweep) <= tolerance,
            f"Неверная длина дуги: {length}; ожидалось {radius * sweep}")
    sign = -1 if clockwise else 1
    for fraction in (0.0, 0.5, 1.0):
        angle = a1 + sign * sweep * fraction
        point = (center[0] + radius * math.cos(angle), center[1] + radius * math.sin(angle))
        distance = curve.GetDistanceToPoint(*point)
        require(math.isfinite(distance) and 0 <= distance <= tolerance,
                f"Точка не лежит на ожидаемой дуге: {point}; расстояние {distance}")
    return obj


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


def line(drawing: ksapi.IDrawingContainer, p: Point2, q: Point2) -> ksapi.ILineSegment:
    obj = require(drawing.GetLineSegments().Add(), "Отрезок")
    obj.SetX1(p[0])
    obj.SetY1(p[1])
    obj.SetX2(q[0])
    obj.SetY2(q[1])
    require(obj.Update(), "Обновление отрезка")
    return obj


def blend_lines(
    p0: Point2, corner: Point2, p1: Point2, radius: float, *, tolerance: float = 1e-5,
) -> tuple[tuple[Point2, Point2], tuple[Point2, float, float, float, bool], tuple[Point2, Point2]]:
    """Trim p0->corner->p1 and insert a tangent circular arc; no extension.

    Return (segment_a, arc_parameters, segment_b), without CAD mutation.
    arc_parameters = (center, radius, a1, a2, clockwise), angles in radians.
    Radius is a caller-selected geometric input, not an engineering default.
    """
    if (not all(math.isfinite(v) for v in (*p0, *corner, *p1, radius, tolerance))
            or radius <= 0 or tolerance <= 0):
        raise ValueError("Сопряжение: нужны конечные данные, положительные радиус и допуск")
    la, lb = math.dist(p0, corner), math.dist(corner, p1)
    if min(la, lb) <= tolerance:
        raise ValueError("Нулевой или слишком короткий отрезок")
    u = tuple((corner[i] - p0[i]) / la for i in range(2))
    v = tuple((p1[i] - corner[i]) / lb for i in range(2))
    cross, dot = u[0] * v[1] - u[1] * v[0], sum(a * b for a, b in zip(u, v))
    if abs(cross) <= 1e-12:
        raise ValueError("Коллинеарные направления: единственная дуга не определена")
    turn = math.atan2(cross, dot)
    trim = radius * math.tan(abs(turn) / 2)
    if trim <= tolerance or min(la, lb) - trim <= tolerance:
        raise ValueError("Радиус не оставляет два ненулевых обрезанных отрезка")
    pa = tuple(corner[i] - trim * u[i] for i in range(2))
    pb = tuple(corner[i] + trim * v[i] for i in range(2))
    sign = 1 if cross > 0 else -1
    center = (pa[0] - sign * radius * u[1], pa[1] + sign * radius * u[0])
    require(abs(math.dist(center, pb) - radius) <= tolerance, "Невязка сопряжения")
    a1 = math.atan2(pa[1] - center[1], pa[0] - center[0])
    a2 = math.atan2(pb[1] - center[1], pb[0] - center[0])
    return (p0, pa), (center, radius, a1, a2, cross < 0), (pb, p1)


def bezier(
    drawing: ksapi.IDrawingContainer,
    nodes: Sequence[tuple[float, float, float, float, float, float]],
) -> ksapi.IBezier:
    """Nodes: (base_x, base_y, left_x, left_y, right_x, right_y), absolute coordinates."""
    obj = require(drawing.GetBeziers().Add(), "Кривая Безье")
    obj.SetClosed(False)
    for index, node in enumerate(nodes):
        result = obj.AddPoint(index, *node)
        require(result[0], "Узел Безье")
    require(obj.Update(), "Обновление Безье")
    return obj


def extrude(
    model: ksapi.IModelContainer, sketch: ksapi.ISketch, depth: float, *, cut: bool = False,
) -> ksapi.IExtrusion:
    operation = require(model.GetExtrusions().Add(
        c3d.o3d_cutExtrusion if cut else c3d.o3d_bossExtrusion
    ), "Операция выдавливания")
    operation.SetProfiles([sketch])
    # From the lower XOY sketch into Z>0: cuts use the reverse side.
    operation.SetDirection(c3d.dtReverse if cut else c3d.dtNormal)
    require(operation.SetSideParameters(not cut, c3d.etBlind, depth, 0.0, False, None), "Глубина")
    require(operation.Update(), "Построение операции")
    return operation


def solid_bounds(part: ksapi.IPart, operation: ksapi.IExtrusion) -> tuple[float, ...]:
    require(part.RebuildModel(True), "Перестроение")
    bodies = ksapi.IFeature(part).GetResultBodies()
    require(len(bodies) == 1, f"Ожидалось одно тело, получено {len(bodies)}")
    body = bodies[0]
    require(body.IsSolid(), "Тело не твёрдое")
    bounds = body.GetGabarit(0, 0, 0, 0, 0, 0)
    require(bounds[0], "Габариты")
    return bounds[1:]


def verify_cylindrical_walls(
    part: ksapi.IPart, expected: Sequence[tuple[float, float, float, float, float]],
    *, tolerance: float = 1e-5,
) -> None:
    """Check actual cylindrical faces and their circular rims for this simple recipe.

    Expected entries: (center_x, center_y, radius, z_min, z_max), in millimetres.
    Includes the ring's outer wall, so no extra cylindrical walls may go unnoticed.
    This is not a general validator for filleted, split or intersecting holes.
    """
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


def save_new(doc: ksapi.IKompasDocument, path: str | Path) -> Path:
    path = Path(path).expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"Не перезаписываем {path}")
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    require(doc.SaveAs(str(path)), "Сохранение")
    require(Path(doc.GetFullPath()).resolve() == path, "Неверный путь сохранённого документа")
    require(path.is_file() and path.stat().st_size > 0, "Файл результата отсутствует")
    return path


def positive(value: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError("Ожидается положительное конечное число")
    return result


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("shape", choices=["plate", "ring"])
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--thickness", type=positive, default=10.0)
    parser.add_argument("--width", type=positive, default=60.0)
    parser.add_argument("--height", type=positive, default=40.0)
    parser.add_argument("--outer-diameter", type=positive, default=50.0)
    parser.add_argument("--bore", type=positive, default=10.0)
    parser.add_argument("--holes", type=int, default=0)
    parser.add_argument("--pitch-radius", type=positive, default=15.0)
    parser.add_argument("--hole-diameter", type=positive, default=4.0)
    parser.add_argument("--cut-depth", type=positive, help="Default: full thickness; smaller value: blind holes")
    args = parser.parse_args(argv)
    output = args.output.expanduser().absolute()
    if output.exists() or output.is_symlink():
        parser.error(f"Файл уже существует: {output}")
    output = output.resolve()
    if args.holes < 0:
        parser.error("--holes не может быть отрицательным")
    if args.shape == "ring" and args.bore >= args.outer_diameter:
        parser.error("Отверстие должно быть меньше наружного диаметра")
    if args.cut_depth and args.cut_depth > args.thickness:
        parser.error("Глубина отверстий не должна превышать толщину")
    if args.holes:
        r, hole_r = args.pitch_radius, args.hole_diameter / 2
        if args.shape == "ring":
            inside = r - hole_r > args.bore / 2 and r + hole_r < args.outer_diameter / 2
        else:
            inside = r + hole_r < min(args.width, args.height) / 2
        if not inside:
            parser.error("Отверстия должны целиком находиться внутри материала")
        if args.holes > 1 and 2 * r * math.sin(math.pi / args.holes) <= 2 * hole_r:
            parser.error("Отверстия пересекаются или касаются")

    app = connect()
    previous = app.GetActiveDocument()
    owned = []
    try:
        doc, part, model = new_part(app, f"Recipe: {args.shape}", owned=owned)
        with sketch_xoy(part, model) as (profile, drawing):
            if args.shape == "plate":
                rectangle(drawing, -args.width / 2, -args.height / 2, args.width, args.height)
            else:
                circle(drawing, 0, 0, args.outer_diameter / 2)
                circle(drawing, 0, 0, args.bore / 2)
        operation = extrude(model, profile, args.thickness)
        walls = []
        if args.shape == "ring":
            walls.extend((0.0, 0.0, radius, 0.0, args.thickness)
                         for radius in (args.outer_diameter / 2, args.bore / 2))
        if args.holes:
            with sketch_xoy(part, model) as (holes, drawing):
                for i in range(args.holes):
                    angle = 2 * math.pi * i / args.holes
                    x, y = args.pitch_radius * math.cos(angle), args.pitch_radius * math.sin(angle)
                    circle(drawing, x, y, args.hole_diameter / 2)
                    walls.append((x, y, args.hole_diameter / 2, 0.0, args.cut_depth or args.thickness))
            operation = extrude(model, holes, args.cut_depth or args.thickness, cut=True)
        bounds = solid_bounds(part, operation)
        dimensions = [bounds[i + 3] - bounds[i] for i in range(3)]
        expected = ([args.width, args.height] if args.shape == "plate" else [args.outer_diameter] * 2)
        expected.append(args.thickness)
        require(all(abs(a - b) < 1e-5 for a, b in zip(dimensions, expected)), f"Габариты: {dimensions}")
        verify_cylindrical_walls(part, walls)
        require(not feature_errors(part), "Ошибки полного дерева операций")
        print(f"Сохранено: {save_new(doc, output)}; габариты: {dimensions}; стенки проверены: {len(walls)}")
    finally:
        # On a native disconnect stop here: do not reconnect/retry or close by tab name.
        close_owned(owned)
        if previous:
            previous.SetActive()


if __name__ == "__main__":
    main()
