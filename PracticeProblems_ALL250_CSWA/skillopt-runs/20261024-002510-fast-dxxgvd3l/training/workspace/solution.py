# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Practice Problem 1.1 (CSWA, MMGS): stepped block 60 x 28 x 75 with a through O12 hole.

Drawing reading (front view below, top view above => third angle):
  front view (X right, Z up, origin at its bottom-left): 60 wide, 75 tall,
      base height 30, middle level 30+20 = 50, third level 50-12 = 38,
      hole O12 centred 16 from the right face (X = 44) and 16 above the bottom (Z = 16).
  top view (X right, depth vertical, origin at its top-left corner): depth 28,
      staircase strip 20 deep on the origin side, 8 deep strip on the front face
      side, step risers at X = 20 / 32 / 48.
Axis agreement: X (right) and Z (up) come from the front view; the third axis is
derived from the right-handed frame of the XOZ sketch plane (u=+X, v=-Z, n=+Y),
so the material occupies Y = 0..28 with the origin's depth plane bordering the
staircase and the O12 face 28 away.  Ranges: X 0..60, Y 0..28, Z 0..75.
Expected volume = 60*28*30 + 48*20*8 + 32*20*12 + 20*20*25 - pi*6^2*28
= 72593.27 mm3 (task: 72593 mm3).
Tree: sketch "Base 60x30" (plate outline + through hole, driving dims) -> boss 28,
      sketch "Steps" (staircase profile, driving dims) -> boss 20.
"""
from __future__ import annotations

import argparse
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
import math
from pathlib import Path

import ksapi
from constants import constants as c
from constants3d import constants as c3d

EXPECTED_BOUNDS = (0.0, 0.0, 0.0, 60.0, 28.0, 75.0)
EXPECTED_VOLUME = 72593.27
TOL_BOUNDS = 1e-4
TOL_VOLUME = 1.0


def require(value, message):
    if not value:
        raise RuntimeError(message)
    return value


# --------------------------------------------------------------------------- sketch plane frame
class Frame:
    """Map global (X,0,Z) points of the XOZ plane to sketch-local (u, v)."""

    def __init__(self, sketch: ksapi.ISketch) -> None:
        p00 = require(sketch.GetPoint3D(0.0, 0.0, 0.0, 0.0, 0.0), "GetPoint3D(0,0)")
        pu = require(sketch.GetPoint3D(1.0, 0.0, 0.0, 0.0, 0.0), "GetPoint3D(1,0)")
        pv = require(sketch.GetPoint3D(0.0, 1.0, 0.0, 0.0, 0.0), "GetPoint3D(0,1)")
        require(p00[0] and pu[0] and pv[0], "GetPoint3D status")
        self.origin = p00[1:4]
        self.u = tuple(pu[i + 1] - p00[i + 1] for i in range(3))
        self.v = tuple(pv[i + 1] - p00[i + 1] for i in range(3))
        self.normal = (
            self.u[1] * self.v[2] - self.u[2] * self.v[1],
            self.u[2] * self.v[0] - self.u[0] * self.v[2],
            self.u[0] * self.v[1] - self.u[1] * self.v[0],
        )
        print(f"frame origin={self.origin} u={self.u} v={self.v} n={self.normal}", flush=True)

    def local(self, x: float, z: float) -> tuple[float, float]:
        """Global point (x, 0, z) -> sketch (u, v)."""
        gx, gy, gz = x - self.origin[0], -self.origin[1], z - self.origin[2]
        u = gx * self.u[0] + gy * self.u[1] + gz * self.u[2]
        v = gx * self.v[0] + gy * self.v[1] + gz * self.v[2]
        return u, v

    @property
    def material_normal(self) -> bool:
        """True when dtNormal pushes material towards -Y (planned build side)."""
        return self.normal[1] < 0.0


@contextmanager
def depth_sketch(part, model, name: str):
    sketch = require(model.GetSketchs().Add(), "Эскиз")
    sketch.SetName(name)
    sketch.SetPlane(require(part.GetDefaultObject(c3d.o3d_planeXOZ), "Плоскость XOZ"))
    require(sketch.Update(), "Плоскость эскиза")
    frame = Frame(sketch)
    fragment = require(sketch.BeginEdit(False), "BeginEdit")
    try:
        fragment.SetParametricMode(True)
        require(fragment.IsParametricMode(), "Параметрический режим")
        view = require(fragment.GetViewsAndLayersManager().GetViews().GetActiveView(), "Вид эскиза")
        yield sketch, frame, require(ksapi.IDrawingContainer(view), "Геометрия эскиза"), \
            require(ksapi.ISymbols2DContainer(view), "Размеры эскиза")
    finally:
        require(sketch.EndEdit(), "EndEdit")
    state = sketch.GetConstraintsState()
    print(f"sketch '{name}' constraints state = {state}", flush=True)
    require(state == c.ksStateWellConstrained, f"Эскиз '{name}' не полностью определён: {state}")
    return


# --------------------------------------------------------------------------- constraints / dimensions
def constraint(obj, kind: int, *, partners=(), index=None,
               partner_index=None, name=None, value=None):
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
    ok = item.Create()
    require(ok and item.IsValid(), f"Не создано ограничение {kind} {name or ''}")
    return item


def dimension(symbols, p1, p2, at, orientation, name: str, value: float):
    """Driving linear dimension between two witness points."""
    dim = require(symbols.GetLineDimensions().Add(), "Линейный размер")
    dim.SetX1(p1[0]); dim.SetY1(p1[1])
    dim.SetX2(p2[0]); dim.SetY2(p2[1])
    dim.SetX3(at[0]); dim.SetY3(at[1])
    dim.SetOrientation(orientation)
    require(dim.Update(), "Обновление размера")
    require(dim.Associate(), f"Привязка размера {name}")
    constraint(dim, c.ksCFixedDim)
    constraint(dim, c.ksCDimWithVariable, name=name, value=value)
    return dim


def poly_profile(frame, drawing, symbols, pts_xz: Sequence[tuple[float, float]],
                 dims):
    """Closed axis-aligned polygon: coincidence + H/V relations, one anchor, driving dims."""
    local = [frame.local(x, z) for x, z in pts_xz]
    lines = []
    for start, end in zip(local, local[1:] + local[:1]):
        line = require(drawing.GetLineSegments().Add(), "Отрезок")
        line.SetX1(start[0]); line.SetY1(start[1])
        line.SetX2(end[0]); line.SetY2(end[1])
        require(line.Update(), "Обновление отрезка")
        lines.append(line)
    count = len(lines)
    for i, line in enumerate(lines):
        constraint(line, c.ksCMergePoints, partners=[lines[(i + 1) % count]],
                   index=1, partner_index=0)
        horizontal = abs(local[i][1] - local[(i + 1) % count][1]) < 1e-9
        constraint(line, c.ksCHorizontal if horizontal else c.ksCVertical)
    constraint(lines[0], c.ksCFixedPoint, index=0)  # one anchor only
    for name, value, i1, i2, at, orientation in dims:
        dimension(symbols, local[i1], local[i2], at, orientation, name, value)
    return lines


def hole_in_plate(frame, drawing, symbols, center_xz, radius):
    """Through hole inside the base profile, positioned by driving dimensions
    (16 from the right edge, 16 above the bottom edge) and a driving radius."""
    cx, cy = frame.local(*center_xz)
    circle = require(drawing.GetCircles().Add(), "Окружность")
    circle.SetXc(cx); circle.SetYc(cy); circle.SetRadius(radius)
    require(circle.Update(), "Обновление окружности")
    right_edge_z0 = frame.local(60.0, 0.0)   # corner vertex 1 of the rectangle
    origin = frame.local(0.0, 0.0)           # anchored corner vertex 0
    dimension(symbols, right_edge_z0, (cx, cy), (frame.local(52.0, -8.0)),
              c.ksLinDHorizontal, "hole_x", 16.0)
    dimension(symbols, origin, (cx, cy), (frame.local(-9.0, 8.0)),
              c.ksLinDVertical, "hole_z", 16.0)
    radial = require(symbols.GetRadialDimensions().Add(), "Радиальный размер")
    radial.SetBaseObject(circle)
    radial.SetXc(cx); radial.SetYc(cy); radial.SetRadius(radius); radial.SetAngle(215.0)
    require(radial.Update(), "Обновление радиального размера")
    constraint(radial, c.ksCFixedDim)
    constraint(radial, c.ksCDimWithVariable, name="hole_radius", value=radius)
    return circle


# --------------------------------------------------------------------------- operations
def extrude(model, sketch, depth: float, *, cut: bool, normal: bool):
    operation = require(model.GetExtrusions().Add(
        c3d.o3d_cutExtrusion if cut else c3d.o3d_bossExtrusion), "Выдавливание")
    operation.SetProfiles([sketch])
    operation.SetDirection(c3d.dtNormal)
    require(operation.SetSideParameters(normal, c3d.etBlind, depth, 0.0, False, None), "Глубина")
    require(operation.Update(), "Построение операции")
    return operation


def bounds(part) -> tuple[float, ...]:
    body = require(ksapi.IFeature(part).GetResultBodies(), "Тела").pop()
    result = body.GetGabarit(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    require(result[0], "Габариты")
    return tuple(round(v, 6) for v in result[1:])


def volume_mm3(part) -> float:
    mass = require(ksapi.IMassInertiaParam(part), "МЦХ")
    mass.SetLengthUnits(c.ksLUnMM)
    require(mass.Calculate(), "Расчёт МЦХ")
    require(mass.IsActual(), "Неактуальный расчёт МЦХ")
    return float(mass.GetVolume())


def feature_errors(part) -> list:
    errors, seen = [], set()

    def visit(feature, path):
        if feature.reference in seen:
            return
        seen.add(feature.reference)
        path = [*path, feature.GetName()]
        if feature.GetObjectError():
            errors.append((path, feature.GetObjectError()))
        for child in feature.GetSubFeatures(c.ksOperTree, True, True):
            if child:
                visit(child, path)

    visit(require(ksapi.IFeature(part), "Дерево детали"), [])
    return errors


def build(part, model, normal: bool):
    """Base 60x30x28 with a through O12 hole, plus the 20 deep staircase."""
    operations = []
    with depth_sketch(part, model, "Base 60x30") as (sketch, frame, drawing, symbols):
        h, v = c.ksLinDHorizontal, c.ksLinDVertical
        poly_profile(frame, drawing, symbols,
                     [(0.0, 0.0), (60.0, 0.0), (60.0, 30.0), (0.0, 30.0)],
                     [("base_len", 60.0, 0, 1, frame.local(30.0, -8.0), h),
                      ("base_h", 30.0, 1, 2, frame.local(68.0, 15.0), v)])
        hole_in_plate(frame, drawing, symbols, (44.0, 16.0), 6.0)
    operations.append(extrude(model, sketch, 28.0, cut=False, normal=normal))

    with depth_sketch(part, model, "Steps") as (sketch, frame, drawing, symbols):
        h, v = c.ksLinDHorizontal, c.ksLinDVertical
        poly_profile(frame, drawing, symbols,
                     [(0.0, 30.0), (48.0, 30.0), (48.0, 38.0), (32.0, 38.0),
                      (32.0, 50.0), (20.0, 50.0), (20.0, 75.0), (0.0, 75.0)],
                     [("step_w1", 20.0, 6, 7, frame.local(10.0, 82.0), h),
                      ("step_w2", 12.0, 5, 4, frame.local(26.0, 56.0), h),
                      ("step_w3", 16.0, 3, 2, frame.local(40.0, 44.0), h),
                      ("col_h", 25.0, 6, 5, frame.local(-9.0, 62.5), v),
                      ("step_h2", 12.0, 4, 3, frame.local(25.0, 44.0), v),
                      ("step_h1", 8.0, 2, 1, frame.local(55.0, 34.0), v)])
    operations.append(extrude(model, sketch, 20.0, cut=False, normal=normal))

    return operations


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    output = args.output.expanduser().resolve() if args.output else None
    if output is not None and output.suffix.lower() != ".m3d":
        parser.error("Нужен файл .m3d")
    if output is not None and output.exists():
        parser.error(f"Файл уже существует: {output}")

    app = require(ksapi.GetKompas(), "Нет API-сессии КОМПАС")
    previous = app.GetActiveDocument()
    doc = None
    try:
        doc = require(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart, True), "Новая деталь")
        part = require(ksapi.IKompasDocument3D(doc).GetTopPart(), "Верхний компонент")
        part.SetName("Practice 1.1 — ступенчатый блок")
        model = require(part.GetModelContainer(), "Контейнер модели")

        # Planned side: material towards -Y (origin on the staircase-side depth plane).
        operations = build(part, model, True)
        require(part.RebuildModel(True), "Перестроение")
        b = bounds(part)
        print("bounds:", b, flush=True)
        v = volume_mm3(part)
        print("volume:", v, flush=True)
        errors = feature_errors(part)
        require(not errors, f"Ошибки дерева: {errors}")
        require(all(abs(a - e) <= TOL_BOUNDS for a, e in zip(b, EXPECTED_BOUNDS)),
                f"Габариты не совпали: {b}")
        require(abs(v - EXPECTED_VOLUME) <= TOL_VOLUME, f"Объём не совпал: {v}")
        print(f"Проверено: габариты {b}, объём {v:.2f} мм3", flush=True)
        if output is not None:
            require(doc.SaveAs(str(output)), "Сохранение")
            require(output.is_file() and output.stat().st_size > 0, "Файл не создан")
            print("сохранено:", output, flush=True)
    finally:
        try:
            if doc is not None:
                require(doc.Close(c.kdDoNotSaveChanges), "Закрытие своей детали")
        finally:
            if previous:
                previous.SetActive()


if __name__ == "__main__":
    main()
