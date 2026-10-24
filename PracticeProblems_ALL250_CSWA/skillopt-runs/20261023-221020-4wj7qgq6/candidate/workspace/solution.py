# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Practice Problem 1.1 - stepped block, native editable KsAPI model.

Geometry (mm), origin at the back-bottom-left corner marked in red:
  base            X 0..60, Y 0..28, Z 0..30
  upper step body X 0..48, Y 0..20, Z 30..75 (stepped profile)
  steps           tower 0..20 @ Z75, step 20..32 @ Z50, step 32..48 @ Z38
  hole            D12, axis +Y, centre X44 Z16, through the 28 mm base
Volume = 60*28*30 + 20*(20*45 + 12*20 + 16*8) - pi*6^2*28 = 72593.27 mm3
"""
from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
import math
from pathlib import Path
from typing import TypeVar

import ksapi
from constants import constants as c
from constants3d import constants as c3d

T = TypeVar("T")
TOL = 1e-4
EXPECTED_BOUNDS = (0.0, 0.0, 0.0, 60.0, 28.0, 75.0)
HOLE_VOLUME = math.pi * 6.0 * 6.0 * 28.0
EXPECTED_VOLUME = 60 * 28 * 30 + 20 * (20 * 45 + 12 * 20 + 16 * 8) - HOLE_VOLUME


def require(value: T | None, message: str) -> T:
    if not value:
        raise RuntimeError(message)
    return value


def close_values(actual: Sequence[float], expected: Sequence[float], message: str) -> None:
    if len(actual) != len(expected) or not all(
        math.isfinite(a) and abs(a - b) <= TOL for a, b in zip(actual, expected)
    ):
        raise RuntimeError(f"{message}: {actual}; expected {expected}")


@contextmanager
def edit(sketch: ksapi.ISketch) -> Iterator[tuple[ksapi.IKompasDocument2D, ksapi.IView]]:
    fragment = require(sketch.BeginEdit(False), "BeginEdit")
    try:
        fragment.SetParametricMode(True)
        require(fragment.IsParametricMode(), "Parametric mode")
        view = require(
            fragment.GetViewsAndLayersManager().GetViews().GetActiveView(),
            "Sketch view",
        )
        yield fragment, view
    finally:
        require(sketch.EndEdit(), "EndEdit")
    state = sketch.GetConstraintsState()
    print(f"sketch {sketch.GetName()}: constraints state={state}", flush=True)
    require(state == c.ksStateWellConstrained, f"Sketch not fully defined: {state}")


def new_sketch(
    part: ksapi.IPart, model: ksapi.IModelContainer, plane: int, name: str,
) -> ksapi.ISketch:
    sketch = require(model.GetSketchs().Add(), "Sketch")
    sketch.SetName(name)
    sketch.SetPlane(require(part.GetDefaultObject(plane), f"Plane {plane}"))
    require(sketch.Update(), "Sketch plane")
    return sketch


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
    require(item.Create() and item.IsValid(), f"Constraint failed: type={kind}, name={name}")
    return item


def driving_dimension(dim: T, name: str, value: float) -> T:
    # ksCFixedDim may be rejected when the solver already considers the value
    # redundant; the named variable is the driving link and is required.
    fixed = require(dim.NewConstraint(), "Fixed-dim constraint")  # type: ignore[attr-defined]
    fixed.SetConstraintType(c.ksCFixedDim)
    fixed.SetConstraintValue(value)
    if not (fixed.Create() and fixed.IsValid()):
        print(f"note: fixed-dim constraint skipped for {name}", flush=True)
    constraint(dim, c.ksCDimWithVariable, name=name, value=value)  # type: ignore[arg-type]
    return dim


def linear_dimension(
    symbols: ksapi.ISymbols2DContainer,
    points: Sequence[tuple[float, float]],
    orientation: int,
    partners: Sequence[tuple[ksapi.IDrawingObject, int]],
    name: str,
    value: float,
) -> ksapi.ILineDimension:
    dim = require(symbols.GetLineDimensions().Add(), "Linear dimension")
    (x1, y1), (x2, y2), (x3, y3) = points
    dim.SetX1(x1)
    dim.SetY1(y1)
    dim.SetX2(x2)
    dim.SetY2(y2)
    dim.SetX3(x3)
    dim.SetY3(y3)
    dim.SetOrientation(orientation)
    require(dim.Update(), f"Linear dimension update {name}")
    require(dim.Associate(), f"Associate linear dimension {name}")
    return driving_dimension(dim, name, value)


def add_line(
    drawing: ksapi.IDrawingContainer, start: tuple[float, float], end: tuple[float, float],
) -> ksapi.ILineSegment:
    line = require(drawing.GetLineSegments().Add(), "Line")
    line.SetX1(start[0])
    line.SetY1(start[1])
    line.SetX2(end[0])
    line.SetY2(end[1])
    require(line.Update(), "Line update")
    return line


def rectangle_network(
    drawing: ksapi.IDrawingContainer,
    vertices: Sequence[tuple[float, float]],
    widths: Sequence[tuple[int, float, str]],
    heights: Sequence[tuple[int, float, str]],
    anchor: tuple[float, float],
) -> None:
    """Closed rectilinear polygon: coincidence + H/V + one anchor + driving dims."""
    symbols = require(ksapi.ISymbols2DContainer(drawing), "Symbols")
    count = len(vertices)
    close = list(vertices[1:]) + list(vertices[:1])
    lines = [add_line(drawing, a, b) for a, b in zip(vertices, close)]
    for i, line in enumerate(lines):
        constraint(
            line, c.ksCMergePoints,
            partners=[lines[(i + 1) % count]], index=1, partner_index=0,
        )
        (x1, y1), (x2, y2) = vertices[i], close[i]
        horizontal = math.isclose(y1, y2)
        constraint(line, c.ksCHorizontal if horizontal else c.ksCVertical)
    anchor_line = next(
        (i for i, (a, b) in enumerate(zip(vertices, close))
         if math.isclose(a[0], anchor[0]) and math.isclose(a[1], anchor[1])),
        None,
    )
    require(anchor_line is not None, "Anchor point is not a polygon vertex")
    constraint(lines[anchor_line], c.ksCFixedPoint, index=0)
    for index, value, name in widths:
        (x1, y1), (x2, y2) = vertices[index], close[index]
        linear_dimension(
            symbols,
            [(x1, y1), (x2, y2), ((x1 + x2) / 2, y1 + (-8 if y1 > 0 else 8))],
            c.ksLinDHorizontal,
            [(lines[index], 0), (lines[index], 1)],
            name,
            value,
        )
    for index, value, name in heights:
        (x1, y1), (x2, y2) = vertices[index], close[index]
        linear_dimension(
            symbols,
            [(x1, y1), (x2, y2), (x1 + 10, (y1 + y2) / 2)],
            c.ksLinDVertical,
            [(lines[index], 0), (lines[index], 1)],
            name,
            value,
        )


def extrude(
    model: ksapi.IModelContainer, sketch: ksapi.ISketch, depth: float, *, cut: bool,
) -> ksapi.IExtrusion:
    kind = c3d.o3d_cutExtrusion if cut else c3d.o3d_bossExtrusion
    operation = require(model.GetExtrusions().Add(kind), "Extrusion")
    operation.SetProfiles([sketch])
    # Documented cut recipe: material on the boss side is cut with the
    # reversed direction and the opposite side flag.
    operation.SetDirection(c3d.dtReverse if cut else c3d.dtNormal)
    require(
        operation.SetSideParameters(
            not cut, c3d.etBlind, depth, 0.0, False, None,
        ),
        "Depth params",
    )
    require(operation.Update(), "Extrusion update")
    return operation


def build(part: ksapi.IPart, model: ksapi.IModelContainer) -> None:
    # 1) Base 60 x 28 x 30, bottom on XOY, origin at the back-bottom-left corner.
    base = new_sketch(part, model, c3d.o3d_planeXOY, "Base 60x28x30")
    with edit(base) as (_, view):
        drawing = require(ksapi.IDrawingContainer(view), "Drawing")
        rectangle_network(
            drawing,
            [(0.0, 0.0), (60.0, 0.0), (60.0, 28.0), (0.0, 28.0)],
            [(0, 60.0, "base_length")],
            [(1, 28.0, "base_depth")],
            (0.0, 0.0),
        )
    extrude(model, base, 30.0, cut=False)

    # 2) Stepped upper body, profile on XOZ. Local v maps to -Z, so use (x, -z).
    upper = new_sketch(part, model, c3d.o3d_planeXOZ, "Stepped upper body")
    with edit(upper) as (_, view):
        drawing = require(ksapi.IDrawingContainer(view), "Drawing")
        rectangle_network(
            drawing,
            [
                (0.0, -30.0), (0.0, -75.0), (20.0, -75.0), (20.0, -50.0),
                (32.0, -50.0), (32.0, -38.0), (48.0, -38.0), (48.0, -30.0),
            ],
            [
                (1, 20.0, "tower_width"),
                (3, 12.0, "mid_step_width"),
                (5, 16.0, "low_step_width"),
            ],
            [
                (0, 45.0, "tower_height_above_base"),
                (2, 25.0, "tower_to_mid_drop"),
                (4, 12.0, "mid_to_low_drop"),
                (6, 8.0, "low_step_height"),
            ],
            (0.0, -30.0),
        )
    extrude(model, upper, 20.0, cut=False)

    # 3) D12 through hole along Y: centre X44, Z16 (16 from right end, 16 above bottom).
    hole = new_sketch(part, model, c3d.o3d_planeXOZ, "D12 through hole")
    with edit(hole) as (_, view):
        drawing = require(ksapi.IDrawingContainer(view), "Drawing")
        symbols = require(ksapi.ISymbols2DContainer(drawing), "Symbols")
        anchor = require(drawing.GetPoints().Add(), "Anchor point")
        anchor.SetX(0.0)
        anchor.SetY(0.0)
        require(anchor.Update(), "Anchor update")
        constraint(anchor, c.ksCFixedPoint, index=0)
        circle = require(drawing.GetCircles().Add(), "Hole circle")
        circle.SetXc(44.0)
        circle.SetYc(-16.0)
        circle.SetRadius(6.0)
        require(circle.Update(), "Hole circle update")
        linear_dimension(
            symbols, [(0.0, 0.0), (44.0, -16.0), (22.0, 8.0)],
            c.ksLinDHorizontal, [(anchor, 0), (circle, 0)], "hole_x_from_origin", 44.0,
        )
        linear_dimension(
            symbols, [(0.0, 0.0), (44.0, -16.0), (-12.0, -11.0)],
            c.ksLinDVertical, [(anchor, 0), (circle, 0)], "hole_z_from_bottom", 16.0,
        )
        radial = require(symbols.GetRadialDimensions().Add(), "Radial dimension")
        radial.SetBaseObject(circle)
        radial.SetXc(44.0)
        radial.SetYc(-16.0)
        radial.SetRadius(6.0)
        radial.SetAngle(35.0)
        require(radial.Update(), "Radial dimension update")
        associations = [
            item for item in radial.GetConstraints()
            if item.GetConstraintType() == c.ksCAssociation
        ]
        require(len(associations) == 1 and associations[0].IsValid(), "Radial association")
        driving_dimension(radial, "hole_diameter_radius", 6.0)
    extrude(model, hole, 40.0, cut=True)

    require(part.RebuildModel(True), "RebuildModel")


def feature_errors(part: ksapi.IPart) -> list[tuple[list[str], int]]:
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

    visit(require(ksapi.IFeature(part), "Part feature"), [])
    return errors


def validate(part: ksapi.IPart) -> tuple[float, ...]:
    require(part.RebuildModel(True), "RebuildModel")
    root = require(ksapi.IFeature(part), "Part feature")
    bodies = root.GetResultBodies()
    require(len(bodies) == 1 and bodies[0].IsSolid(), "Expected one solid body")
    result = bodies[0].GetGabarit(0, 0, 0, 0, 0, 0)
    require(result[0], "Body bounds")
    bounds = tuple(result[1:])
    close_values(bounds, EXPECTED_BOUNDS, "Bounds")
    errors = feature_errors(part)
    require(not errors, f"Feature tree errors: {errors}")
    inertia = require(ksapi.IMassInertiaParam(part), "Mass-inertia")
    inertia.SetLengthUnits(c.ksLUnMM)
    require(inertia.Calculate() and inertia.IsActual(), "Volume calculation")
    volume = inertia.GetVolume()
    close_values((volume,), (EXPECTED_VOLUME,), "Volume")
    print(f"validated bounds={bounds} volume={volume:.3f}", flush=True)
    return bounds


def main() -> None:
    output = Path(__file__).resolve().with_name("model.m3d")
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"Refusing existing output: {output}")
    app = require(ksapi.GetKompas(), "No running KOMPAS API session; will not launch")
    previous = app.GetActiveDocument()
    doc = None
    try:
        doc = require(
            app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart, True),
            "New own part",
        )
        part = require(ksapi.IKompasDocument3D(doc).GetTopPart(), "Top part")
        part.SetName("Practice Problem 1.1 - stepped block")
        model = require(part.GetModelContainer(), "Model container")
        build(part, model)
        validate(part)
        if output.exists() or output.is_symlink():
            raise FileExistsError(f"Refusing existing output: {output}")
        require(doc.SaveAs(str(output)), "SaveAs model.m3d")
        require(output.is_file() and output.stat().st_size > 0, "Missing output file")
        print(f"saved {output} ({output.stat().st_size} bytes)", flush=True)
    finally:
        try:
            if doc is not None:
                require(doc.Close(c.kdDoNotSaveChanges), "Close own document")
        finally:
            if previous:
                previous.SetActive()


if __name__ == "__main__":
    main()
