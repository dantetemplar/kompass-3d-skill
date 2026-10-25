# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Practice Problem 1.1 — stepped bracket (CSWA, MMGS).

Native KsAPI part, two dimension-driven sketches on the front plane (XOZ):

  * stepped front profile (60 wide, 75 tall, steps at 20/32/48 mm and
    30/38/50/75 mm) extruded 20 mm  -> rear stepped structure;
  * 60 x 30 rectangle with a Ø12 hole (44, 16) extruded 28 mm -> base block.

Both bosses are extruded in the same direction from the same plane, so the
stepped structure is always flush with one 28 mm face of the base and the base
always protrudes 8 mm on the opposite side (the drawing's design intent).
Reference volume: 72593 mm³.
"""
from __future__ import annotations

import argparse
import math
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import TypeVar

import ksapi
from constants import constants as c
from constants3d import constants as c3d

T = TypeVar("T")
DrawingT = TypeVar("DrawingT", bound=ksapi.IDrawingObject)
Point2 = tuple[float, float]

# --- dimensions of the part (mm), taken from the drawing ---------------------
W = 60.0        # overall length
D = 28.0        # base depth
H_BASE = 30.0   # base height
D_UP = 20.0     # depth of the stepped structure
COL_W = 20.0    # tall column length
COL_H = 75.0    # overall height
X2, Z2 = 32.0, 50.0   # second step edge / top
X3, Z3 = 48.0, 38.0   # third step edge / top
HOLE_D = 12.0   # hole diameter
HOLE_X = 44.0   # 60 - 16
HOLE_Z = 16.0
EXPECTED_VOLUME = 72593.0


def require(value: T | None, message: str) -> T:
    if not value:
        raise RuntimeError(message)
    return value


@contextmanager
def sketch_xoz(
    part: ksapi.IPart, model: ksapi.IModelContainer, name: str,
) -> Iterator[tuple[ksapi.ISketch, ksapi.IDrawingContainer, ksapi.ISymbols2DContainer]]:
    sketch = require(model.GetSketchs().Add(), "Эскиз")
    sketch.SetName(name)
    sketch.SetPlane(require(part.GetDefaultObject(c3d.o3d_planeXOZ), "Плоскость XOZ"))
    require(sketch.Update(), "Плоскость эскиза")
    fragment = require(sketch.BeginEdit(False), "Редактирование эскиза")
    try:
        fragment.SetParametricMode(True)
        view = require(
            fragment.GetViewsAndLayersManager().GetViews().GetActiveView(), "Вид эскиза"
        )
        yield (
            sketch,
            require(ksapi.IDrawingContainer(view), "Геометрия эскиза"),
            require(ksapi.ISymbols2DContainer(view), "Обозначения эскиза"),
        )
    finally:
        require(sketch.EndEdit(), "Завершение эскиза")
    state = sketch.GetConstraintsState()
    require(state == c.ksStateWellConstrained, f"Эскиз «{name}» не определён: state={state}")


def add_line(drawing: ksapi.IDrawingContainer, a: Point2, b: Point2) -> ksapi.ILineSegment:
    line = require(drawing.GetLineSegments().Add(), "Отрезок")
    line.SetX1(a[0])
    line.SetY1(a[1])
    line.SetX2(b[0])
    line.SetY2(b[1])
    require(line.Update(), "Обновление отрезка")
    return line


def constraint(
    obj: ksapi.IDrawingObject,
    kind: int,
    *,
    partners: Sequence[ksapi.IDrawingObject] = (),
    index: int | None = None,
    partner_index: int | None = None,
    name: str | None = None,
    value: float | None = None,
) -> ksapi.IParametricConstraint:
    item = require(obj.NewConstraint(), "NewConstraint")
    item.SetConstraintType(kind)
    if index is not None:
        item.SetIndex(index)
    if partner_index is not None:
        item.SetPartnerIndex(partner_index)
    if partners:
        item.SetPartners(list(partners))
    if name is not None:
        item.SetVariable(name)
    if value is not None:
        item.SetConstraintValue(value)
    result = item.Create()
    require(result and item.IsValid(), f"Не создана связь type={kind} name={name}")
    return item


def driving_dimension(dim: DrawingT, name: str, value: float) -> DrawingT:
    constraint(dim, c.ksCFixedDim)
    constraint(dim, c.ksCDimWithVariable, name=name, value=value)
    return dim


def linear_dimension(
    symbols: ksapi.ISymbols2DContainer,
    p1: Point2,
    p2: Point2,
    place: Point2,
    orientation: int,
    partners: Sequence[tuple[ksapi.IDrawingObject, int]],
    name: str,
    value: float,
) -> ksapi.ILineDimension:
    dim = require(symbols.GetLineDimensions().Add(), "Линейный размер")
    dim.SetX1(p1[0])
    dim.SetY1(p1[1])
    dim.SetX2(p2[0])
    dim.SetY2(p2[1])
    dim.SetX3(place[0])
    dim.SetY3(place[1])
    dim.SetOrientation(orientation)
    require(dim.Update(), "Обновление размера")
    require(dim.Associate(), f"Привязка размера {name}")
    for dimension_index, (partner, point_index) in enumerate(partners):
        require(
            any(
                item.IsValid()
                and item.GetConstraintType() == c.ksCMergePoints
                and item.GetIndex() == dimension_index
                and item.GetPartnerIndex() == point_index
                and any(obj.GetId() == partner.GetId() for obj in item.GetPartners())
                for item in dim.GetConstraints()
            ),
            f"Нет привязки размера {name}/{dimension_index}",
        )
    return driving_dimension(dim, name, value)


def radial_dimension(
    symbols: ksapi.ISymbols2DContainer,
    circle: ksapi.ICircle,
    center: Point2,
    radius: float,
    name: str,
) -> ksapi.IRadialDimension:
    dim = require(symbols.GetRadialDimensions().Add(), "Радиальный размер")
    dim.SetBaseObject(circle)
    dim.SetXc(center[0])
    dim.SetYc(center[1])
    dim.SetRadius(radius)
    dim.SetAngle(35.0)
    require(dim.Update(), "Обновление радиального размера")
    associated = [
        item for item in dim.GetConstraints() if item.GetConstraintType() == c.ksCAssociation
    ]
    require(len(associated) == 1 and associated[0].IsValid(), f"Привязка радиуса {name}")
    return driving_dimension(dim, name, radius)


def extrude(
    model: ksapi.IModelContainer,
    sketch: ksapi.ISketch,
    depth: float,
    name: str,
    cut: bool = False,
) -> ksapi.IExtrusion:
    operation = require(
        model.GetExtrusions().Add(c3d.o3d_cutExtrusion if cut else c3d.o3d_bossExtrusion),
        "Выдавливание",
    )
    operation.SetName(name)
    operation.SetProfiles([sketch])
    operation.SetDirection(c3d.dtNormal)
    require(
        operation.SetSideParameters(True, c3d.etBlind, depth, 0.0, False, None), "Глубина"
    )
    require(operation.Update(), "Построение операции")
    require(not ksapi.IFeature(operation).GetObjectError(), f"Ошибка операции «{name}»")
    return operation


def build(part: ksapi.IPart, model: ksapi.IModelContainer) -> list[ksapi.ISketch]:
    # front profile of the stepped structure above the base (z >= 30), CCW
    vertices: list[Point2] = [
        (0.0, H_BASE), (X3, H_BASE), (X3, Z3), (X2, Z3),
        (X2, Z2), (COL_W, Z2), (COL_W, COL_H), (0.0, COL_H),
    ]
    with sketch_xoz(part, model, "Ступенчатый профиль") as (sketch1, drawing, symbols):
        lines = [
            add_line(drawing, a, b)
            for a, b in zip(vertices, vertices[1:] + vertices[:1])
        ]
        for i, line in enumerate(lines):
            constraint(
                line,
                c.ksCMergePoints,
                partners=[lines[(i + 1) % len(lines)]],
                index=1,
                partner_index=0,
            )
            constraint(line, c.ksCHorizontal if i % 2 == 0 else c.ksCVertical)
        constraint(lines[0], c.ksCFixedPoint, index=0)

        a, b, cc, d, e, f, g, h = lines
        origin = vertices[0]
        # horizontal: step positions measured from the anchored corner
        linear_dimension(symbols, origin, (COL_W, Z2), (28.0, 18.0),
                         c.ksLinDHorizontal, [(a, 0), (f, 0)], "step1_x", COL_W)
        linear_dimension(symbols, origin, (X2, Z3), (28.0, 28.0),
                         c.ksLinDHorizontal, [(a, 0), (d, 0)], "step2_x", X2)
        linear_dimension(symbols, origin, (X3, H_BASE), (28.0, 38.0),
                         c.ksLinDHorizontal, [(a, 0), (b, 0)], "step3_x", X3)
        # vertical: step heights measured from the base top (z = 30)
        linear_dimension(symbols, origin, (X3, Z3), (56.0, 34.0),
                         c.ksLinDVertical, [(a, 0), (b, 1)], "step3_h", Z3 - H_BASE)
        linear_dimension(symbols, origin, (X2, Z2), (64.0, 40.0),
                         c.ksLinDVertical, [(a, 0), (d, 1)], "step2_h", Z2 - H_BASE)
        linear_dimension(symbols, origin, (COL_W, COL_H), (72.0, 52.0),
                         c.ksLinDVertical, [(a, 0), (f, 1)], "column_h", COL_H - H_BASE)
    extrude(model, sketch1, D_UP, "Ступенчатая стойка")

    # base block 60 x 30 section with the Ø12 through hole
    rect: list[Point2] = [(0.0, 0.0), (W, 0.0), (W, H_BASE), (0.0, H_BASE)]
    with sketch_xoz(part, model, "Основание с отверстием") as (sketch2, drawing, symbols):
        lines = [
            add_line(drawing, p, q) for p, q in zip(rect, rect[1:] + rect[:1])
        ]
        for i, line in enumerate(lines):
            constraint(
                line,
                c.ksCMergePoints,
                partners=[lines[(i + 1) % len(lines)]],
                index=1,
                partner_index=0,
            )
            constraint(line, c.ksCHorizontal if i % 2 == 0 else c.ksCVertical)
        constraint(lines[0], c.ksCFixedPoint, index=0)

        hole = require(drawing.GetCircles().Add(), "Окружность")
        hole.SetXc(HOLE_X)
        hole.SetYc(HOLE_Z)
        hole.SetRadius(HOLE_D / 2.0)
        require(hole.Update(), "Обновление окружности")

        a, b, cc, d = lines
        origin = rect[0]
        linear_dimension(symbols, origin, (W, 0.0), (30.0, -12.0),
                         c.ksLinDHorizontal, [(a, 0), (a, 1)], "base_len", W)
        linear_dimension(symbols, origin, (W, H_BASE), (-12.0, 15.0),
                         c.ksLinDVertical, [(a, 0), (b, 1)], "base_h", H_BASE)
        linear_dimension(symbols, origin, (HOLE_X, HOLE_Z), (22.0, -22.0),
                         c.ksLinDHorizontal, [(a, 0), (hole, 0)], "hole_x", HOLE_X)
        linear_dimension(symbols, origin, (HOLE_X, HOLE_Z), (-22.0, 10.0),
                         c.ksLinDVertical, [(a, 0), (hole, 0)], "hole_z", HOLE_Z)
        radial_dimension(symbols, hole, (HOLE_X, HOLE_Z), HOLE_D / 2.0, "hole_radius")
    extrude(model, sketch2, D, "Основание")
    return [sketch1, sketch2]


def validate(part: ksapi.IPart, sketches: Sequence[ksapi.ISketch]) -> dict[str, object]:
    require(part.RebuildModel(True), "RebuildModel")
    bodies = require(ksapi.IFeature(part), "Дерево детали").GetResultBodies()
    require(len(bodies) == 1, f"Ожидалось одно тело, получено {len(bodies)}")
    require(bodies[0].IsSolid(), "Тело не твёрдое")
    raw = bodies[0].GetGabarit(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    require(raw[0], "Габариты")
    bounds = tuple(raw[1:])
    size = sorted(bounds[3 + i] - bounds[i] for i in range(3))
    require(
        all(abs(a - b) <= 1e-5 for a, b in zip(size, sorted([W, D, COL_H]))),
        f"Габариты {bounds}",
    )
    mass = require(ksapi.IMassInertiaParam(part), "МЦХ")
    mass.SetLengthUnits(c.ksLUnMM)
    require(mass.Calculate(), "Расчёт МЦХ")
    volume = mass.GetVolume()
    require(abs(volume - EXPECTED_VOLUME) < 1.0, f"Объём {volume}, ожидалось {EXPECTED_VOLUME}")

    # hole wall: cylindrical face Ø12 through the full 28 mm depth
    cylinders = []
    for obj in ksapi.IFeature(part).GetModelObjects([c3d.o3d_face]):
        face = require(ksapi.IFace(obj), "Грань")
        if face.IsCylinder():
            rims = []
            for edge in face.GetLimitingEdges():
                if edge.IsCircle():
                    result = require(edge.GetMathCurve(), "Кривая").GetGabarit(0, 0, 0, 0, 0, 0)
                    require(result[0], "Габарит кромки")
                    rims.append(tuple(result[1:]))
            require(len(rims) == 2, f"Кромки отверстия: {len(rims)}")
            centers = [((r[0] + r[3]) / 2.0, r[1], (r[2] + r[5]) / 2.0) for r in rims]
            depth = abs(centers[0][1] - centers[1][1])
            cylinders.append((centers[0][0], centers[0][2], face.GetRadius(), depth))
    require(len(cylinders) == 1, f"Цилиндрические стенки: {cylinders}")
    cx, cz, radius, depth = cylinders[0]
    require(abs(radius - HOLE_D / 2.0) < 1e-5, f"Радиус отверстия {radius}")
    require(abs(depth - D) < 1e-4, f"Глубина отверстия {depth}")
    require(abs(cx - HOLE_X) < 1e-4 and abs(cz + HOLE_Z) < 1e-4,
            f"Положение отверстия {(cx, cz)}")

    errors, seen = [], set()

    def visit(feature: ksapi.IFeature, path: Sequence[str]) -> None:
        if feature.reference in seen:
            return
        seen.add(feature.reference)
        path = [*path, feature.GetName()]
        if feature.GetObjectError():
            errors.append((path, feature.GetObjectError()))
        for child in feature.GetSubFeatures(c.ksOperTree, True, True):
            if child:
                visit(child, path)

    visit(require(ksapi.IFeature(part), "Дерево"), [])
    require(not errors, f"Ошибки дерева: {errors}")
    require(
        all(s.GetConstraintsState() == c.ksStateWellConstrained for s in sketches),
        "Не все эскизы определены",
    )
    return {
        "bounds": bounds,
        "volume": volume,
        "hole": (cx, cz, radius, depth),
        "sketches_defined": len(sketches),
    }


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Новый файл .m3d")
    args = parser.parse_args(argv)
    output = args.output.expanduser().absolute()
    if output.suffix.lower() != ".m3d":
        parser.error("Нужен файл .m3d")
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"Файл уже существует: {output}")

    app = require(ksapi.GetKompas(), "Нет запущенной API-сессии КОМПАС")
    previous = app.GetActiveDocument()
    doc = None
    try:
        doc = require(
            app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart, True), "Новая деталь"
        )
        part = require(ksapi.IKompasDocument3D(doc).GetTopPart(), "Верхний компонент")
        part.SetName("PracticeProblems 1.1")
        model = require(part.GetModelContainer(), "Контейнер модели")
        sketches = build(part, model)
        result = validate(part, sketches)
        output.parent.mkdir(parents=True, exist_ok=True)
        require(not output.exists() and not output.is_symlink(), "Файл появился до сохранения")
        require(doc.SaveAs(str(output)), "Сохранение")
        require(output.is_file() and output.stat().st_size > 0, "Файл результата отсутствует")
        print(f"OK {result} -> {output} ({output.stat().st_size} bytes)")
    finally:
        try:
            if doc is not None:
                require(doc.Close(c.kdDoNotSaveChanges), "Закрытие собственной детали")
        finally:
            if previous:
                previous.SetActive()


if __name__ == "__main__":
    main()
