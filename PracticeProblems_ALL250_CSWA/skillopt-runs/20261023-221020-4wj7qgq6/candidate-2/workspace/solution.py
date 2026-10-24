# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Practice Problem 1.1 (CSWA, Level 1): base 60 x 28 x 30 with a 3-step
staircase block (column 20 wide, steps 12 wide, total height 75, depth 28/20)
and a through hole D12 at 16 from the right end and 16 above the bottom.

Origin (red in the drawing): bottom corner at the sketch plane of the front
view, i.e. (0, 0, 0) with X = length, Y = extrusion depth, Z = height.

Native, editable tree: base sketch (rectangle 60 x 30 + hole circle) ->
boss extrusion 28; staircase sketch (6 dimensioned edges) -> boss extrusion 20.
Sketches are dimension-driven and fully defined (one anchored point each).
"""
from __future__ import annotations

import argparse
import math
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

import ksapi
from constants import constants as c
from constants3d import constants as c3d

if TYPE_CHECKING:  # annotation-only names (not exported at runtime in v25)
    from constants import ksConstraintTypeEnum, ksLineDimensionOrientationEnum

T = TypeVar("T")
Point2 = tuple[float, float]

# Drawing dimensions (mm).
BASE_LEN, BASE_DEPTH, BASE_H = 60.0, 28.0, 30.0
TOTAL_H = 75.0
COL_W, COL_H = 20.0, TOTAL_H - BASE_H          # 20 wide, 45 above the base
STEP2_W, STEP2_UP = 12.0, 20.0                 # 20 above base -> Z=50
STEP3_DROP, STEP3_X = 12.0, 60.0 - 12.0        # Z=38, right edge at X=48
STAIR_DEPTH = 20.0
HOLE_D, HOLE_FROM_RIGHT, HOLE_FROM_BOTTOM = 12.0, 16.0, 16.0
HOLE_R = HOLE_D / 2.0
HOLE_X = BASE_LEN - HOLE_FROM_RIGHT            # 44


def require(value: T | None, message: str) -> T:
    if not value:
        raise RuntimeError(message)
    return value


class PlaneBasis:
    """Mapping from world points on a sketch plane to local sketch (u, v)."""

    def __init__(self, sketch: ksapi.ISketch) -> None:
        self.origin = self._point(sketch, 0.0, 0.0, "sketch origin")
        self.eu = self._delta(self.origin, self._point(sketch, 1.0, 0.0, "u axis"))
        self.ev = self._delta(self.origin, self._point(sketch, 0.0, 1.0, "v axis"))

    @staticmethod
    def _point(sketch: ksapi.ISketch, u: float, v: float, label: str) -> tuple[float, float, float]:
        status, x, y, z = sketch.GetPoint3D(u, v, 0.0, 0.0, 0.0)
        require(status, f"GetPoint3D {label}")
        return (x, y, z)

    @staticmethod
    def _delta(a: Sequence[float], b: Sequence[float]) -> tuple[float, float, float]:
        return (b[0] - a[0], b[1] - a[1], b[2] - a[2])

    def local(self, x: float, z: float) -> Point2:
        d = (x - self.origin[0], -self.origin[1], z - self.origin[2])
        u = sum(p * q for p, q in zip(d, self.eu)) / sum(p * p for p in self.eu)
        v = sum(p * q for p, q in zip(d, self.ev)) / sum(p * p for p in self.ev)
        return (u, v)


def new_sketch(
    part: ksapi.IPart, model: ksapi.IModelContainer, name: str,
) -> tuple[ksapi.ISketch, PlaneBasis]:
    sketch = require(model.GetSketchs().Add(), f"Sketch {name}")
    sketch.SetName(name)
    sketch.SetPlane(require(part.GetDefaultObject(c3d.o3d_planeXOZ), "Plane XOZ"))
    require(sketch.Update(), f"Sketch plane {name}")
    return sketch, PlaneBasis(sketch)


@contextmanager
def edit(sketch: ksapi.ISketch) -> Generator[tuple[ksapi.IView, ksapi.IDrawingContainer,
                                                     ksapi.ISymbols2DContainer], None, None]:
    fragment = require(sketch.BeginEdit(False), "BeginEdit")
    try:
        fragment.SetParametricMode(True)
        require(fragment.IsParametricMode(), "Parametric mode")
        view = require(fragment.GetViewsAndLayersManager().GetViews().GetActiveView(), "Sketch view")
        yield (
            view,
            require(ksapi.IDrawingContainer(view), "Drawing container"),
            require(ksapi.ISymbols2DContainer(view), "Symbols container"),
        )
    finally:
        require(sketch.EndEdit(), "EndEdit")
    state = sketch.GetConstraintsState()
    print(f"  {sketch.GetName()}: constraints state = {state}", flush=True)
    require(state == c.ksStateWellConstrained, f"Sketch {sketch.GetName()} not fully defined: {state}")


def segment(drawing: ksapi.IDrawingContainer, a: Point2, b: Point2) -> ksapi.ILineSegment:
    line = require(drawing.GetLineSegments().Add(), "Line segment")
    line.SetX1(a[0])
    line.SetY1(a[1])
    line.SetX2(b[0])
    line.SetY2(b[1])
    require(line.Update(), "Line segment Update")
    return line


def constraint(
    obj: ksapi.IDrawingObject,
    kind: ksConstraintTypeEnum,
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
    created = item.Create()
    require(created and item.IsValid(), f"Constraint failed: type={kind}, name={name}")
    return item


def driving(name: str, value: float):
    def apply(dim: ksapi.IDrawingObject) -> None:
        item = require(dim.NewConstraint(), f"Fixed dimension {name}")
        item.SetConstraintType(c.ksCFixedDim)
        if not (item.Create() and item.IsValid()):
            print(f"  warning: ksCFixedDim rejected for {name}; variable still drives", flush=True)
        constraint(dim, c.ksCDimWithVariable, name=name, value=value)
    return apply


def linear(
    symbols: ksapi.ISymbols2DContainer,
    p1: Point2,
    p2: Point2,
    at: Point2,
    orientation: ksLineDimensionOrientationEnum,
    name: str,
    value: float,
) -> ksapi.ILineDimension:
    dim = require(symbols.GetLineDimensions().Add(), f"Dimension {name}")
    dim.SetX1(p1[0])
    dim.SetY1(p1[1])
    dim.SetX2(p2[0])
    dim.SetY2(p2[1])
    dim.SetX3(at[0])
    dim.SetY3(at[1])
    dim.SetOrientation(orientation)
    require(dim.Update(), f"Dimension update {name}")
    require(dim.Associate(), f"Dimension associate {name}")
    driving(name, value)(dim)
    return dim


def radial(
    symbols: ksapi.ISymbols2DContainer, circle: ksapi.ICircle, name: str, value: float,
) -> ksapi.IRadialDimension:
    dim = require(symbols.GetRadialDimensions().Add(), f"Dimension {name}")
    dim.SetBaseObject(circle)
    dim.SetXc(circle.GetXc())
    dim.SetYc(circle.GetYc())
    dim.SetRadius(value)
    dim.SetAngle(35.0)
    require(dim.Update(), f"Dimension update {name}")
    require(any(item.IsValid() and item.GetConstraintType() == c.ksCAssociation
                for item in dim.GetConstraints()), f"Radial association {name}")
    driving(name, value)(dim)
    return dim


def build_base(part: ksapi.IPart, model: ksapi.IModelContainer) -> ksapi.ISketch:
    sketch, basis = new_sketch(part, model, "Base 60x30 + hole D12")
    x0, z0, x1, z1 = 0.0, 0.0, BASE_LEN, BASE_H
    with edit(sketch) as (_view, drawing, symbols):
        corners = [(x0, z0), (x1, z0), (x1, z1), (x0, z1)]
        lines = [segment(drawing, basis.local(*a), basis.local(*b))
                 for a, b in zip(corners, corners[1:] + corners[:1])]
        for i, line in enumerate(lines):
            constraint(line, c.ksCMergePoints, partners=[lines[(i + 1) % 4]], index=1, partner_index=0)
            constraint(line, c.ksCHorizontal if i % 2 == 0 else c.ksCVertical)
        constraint(lines[0], c.ksCFixedPoint, index=0)      # anchor at the origin
        linear(symbols, basis.local(x0, z0), basis.local(x1, z0), basis.local(BASE_LEN / 2, -8),
               c.ksLinDHorizontal, "base_length", BASE_LEN)
        linear(symbols, basis.local(x1, z0), basis.local(x1, z1), basis.local(BASE_LEN + 8, BASE_H / 2),
               c.ksLinDVertical, "base_height", BASE_H)
        circle = require(drawing.GetCircles().Add(), "Hole circle")
        circle.SetXc(basis.local(HOLE_X, HOLE_FROM_BOTTOM)[0])
        circle.SetYc(basis.local(HOLE_X, HOLE_FROM_BOTTOM)[1])
        circle.SetRadius(HOLE_R)
        require(circle.Update(), "Circle update")
        linear(symbols, basis.local(BASE_LEN, 0.0), basis.local(HOLE_X, HOLE_FROM_BOTTOM),
               basis.local(HOLE_X + HOLE_FROM_RIGHT / 2, -16), c.ksLinDHorizontal,
               "hole_from_right", HOLE_FROM_RIGHT)
        linear(symbols, basis.local(0.0, 0.0), basis.local(HOLE_X, HOLE_FROM_BOTTOM),
               basis.local(HOLE_X - 14, HOLE_FROM_BOTTOM / 2), c.ksLinDVertical,
               "hole_from_bottom", HOLE_FROM_BOTTOM)
        radial(symbols, circle, "hole_radius", HOLE_R)
    return sketch


def build_staircase(part: ksapi.IPart, model: ksapi.IModelContainer) -> ksapi.ISketch:
    sketch, basis = new_sketch(part, model, "Staircase 20/12/12 x 45")
    x_a, z_b = COL_W, BASE_H + STEP2_UP          # 20, 50
    x_b = COL_W + STEP2_W                        # 32
    z_c = z_b - STEP3_DROP                       # 38
    profile = [
        (0.0, BASE_H), (0.0, TOTAL_H), (x_a, TOTAL_H), (x_a, z_b),
        (x_b, z_b), (x_b, z_c), (STEP3_X, z_c), (STEP3_X, BASE_H),
    ]
    with edit(sketch) as (_view, drawing, symbols):
        pts = [basis.local(*p) for p in profile]
        lines = [segment(drawing, a, b) for a, b in zip(pts, pts[1:] + pts[:1])]
        for i, line in enumerate(lines):
            constraint(line, c.ksCMergePoints, partners=[lines[(i + 1) % len(lines)]],
                       index=1, partner_index=0)
            constraint(line, c.ksCHorizontal if i % 2 == 1 else c.ksCVertical)
        constraint(lines[0], c.ksCFixedPoint, index=0)    # anchor at (0, 30) on the base top
        # Horizontal: column width 20, second step 12 wide, right edge at 60-12.
        linear(symbols, basis.local(0.0, TOTAL_H), basis.local(x_a, TOTAL_H), basis.local(x_a / 2, 82),
               c.ksLinDHorizontal, "column_width", COL_W)
        linear(symbols, basis.local(x_a, z_b), basis.local(x_b, z_b), basis.local((x_a + x_b) / 2, 90),
               c.ksLinDHorizontal, "step2_width", STEP2_W)
        linear(symbols, basis.local(0.0, BASE_H), basis.local(STEP3_X, BASE_H), basis.local(STEP3_X / 2, 98),
               c.ksLinDHorizontal, "right_edge_x", STEP3_X)
        # Vertical: column height 75-30, second step 20 above base, 12 drop to third step.
        linear(symbols, basis.local(0.0, BASE_H), basis.local(0.0, TOTAL_H), basis.local(-8, (BASE_H + TOTAL_H) / 2),
               c.ksLinDVertical, "column_height", COL_H)
        linear(symbols, basis.local(0.0, BASE_H), basis.local(x_a, z_b), basis.local(39, (BASE_H + z_b) / 2),
               c.ksLinDVertical, "step2_up", STEP2_UP)
        linear(symbols, basis.local(x_b, z_b), basis.local(x_b, z_c), basis.local(39, (z_b + z_c) / 2),
               c.ksLinDVertical, "step3_drop", STEP3_DROP)
    return sketch


def extrude(model: ksapi.IModelContainer, sketch: ksapi.ISketch, depth: float) -> ksapi.IExtrusion:
    operation = require(model.GetExtrusions().Add(c3d.o3d_bossExtrusion), "Boss extrusion")
    operation.SetProfiles([sketch])
    operation.SetDirection(c3d.dtNormal)
    require(operation.SetSideParameters(True, c3d.etBlind, depth, 0.0, False, None), "Depth")
    require(operation.Update(), "Extrusion update")
    return operation


def feature_errors(part: ksapi.IPart) -> list[tuple[list[str], int]]:
    errors: list[tuple[list[str], int]] = []
    seen: set[int] = set()

    def visit(item: ksapi.IFeature, path: Sequence[str]) -> None:
        if item.reference in seen:
            return
        seen.add(item.reference)
        path = [*path, item.GetName()]
        error = item.GetObjectError()
        if error:
            errors.append((path, error))
        for child in item.GetSubFeatures(c.ksOperTree, True, True):
            if child:
                visit(child, path)

    visit(require(ksapi.IFeature(part), "Part tree"), [])
    return errors


def validate(part: ksapi.IPart) -> tuple[tuple[float, float, float, float, float, float], int]:
    require(part.RebuildModel(True), "RebuildModel")
    feature = require(ksapi.IFeature(part), "Part feature")
    bodies = feature.GetResultBodies()
    require(len(bodies) == 1, f"One body expected, got {len(bodies)}")
    require(bodies[0].IsSolid(), "Body is not solid")
    raw = bodies[0].GetGabarit(0, 0, 0, 0, 0, 0)
    require(raw[0], "Gabarit")
    bounds = tuple(raw[1:])
    require(len(bounds) == 6 and all(math.isfinite(v) for v in bounds), f"Bounds {bounds}")
    holes = 0
    hole_centers: list[tuple[float, float, float]] = []
    for obj in feature.GetModelObjects([c3d.o3d_face]):
        face = ksapi.IFace(obj)
        if not (face.IsCylinder() and abs(face.GetRadius() - HOLE_R) < 1e-4):
            continue
        holes += 1
        rims = []
        for edge in face.GetLimitingEdges():
            if edge.IsCircle():
                raw_rim = require(edge.GetMathCurve(), "Rim curve").GetGabarit(0, 0, 0, 0, 0, 0)
                require(raw_rim[0], "Rim gabarit")
                rims.append(tuple(raw_rim[1:]))
        require(len(rims) == 2, "Two circular hole rims")
        for rim in rims:
            hole_centers.append(((rim[0] + rim[3]) / 2, (rim[1] + rim[4]) / 2, (rim[2] + rim[5]) / 2))
    require(holes == 1, f"Expected one D{HOLE_D:g} cylindrical wall, got {holes}")
    require(len(hole_centers) == 2, f"Hole rims: {hole_centers}")
    for cx, cy, cz in hole_centers:
        require(abs(cx - HOLE_X) < 1e-4 and abs(cz - HOLE_FROM_BOTTOM) < 1e-4,
                f"Hole axis at {(cx, cz)}, expected {(HOLE_X, HOLE_FROM_BOTTOM)}")
    require(abs(min(c[1] for c in hole_centers)) < 1e-4
            and abs(max(c[1] for c in hole_centers) - BASE_DEPTH) < 1e-4,
            f"Hole does not pass through the base depth: {hole_centers}")
    print(f"  hole: D{HOLE_D:g} axis at X={HOLE_X:g}, Z={HOLE_FROM_BOTTOM:g}, through Y 0..{BASE_DEPTH:g}")
    errors = feature_errors(part)
    require(not errors, f"Feature tree errors: {errors}")
    return bounds, holes


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Practice Problem 1.1 - stepped block")
    parser.add_argument("--output", type=Path, required=True, help="New .m3d file")
    args = parser.parse_args(argv)
    output = args.output.expanduser().absolute()
    if output.suffix.lower() != ".m3d":
        parser.error("--output must be .m3d")
    if output.exists() or output.is_symlink():
        parser.error(f"Refusing existing output: {output}")

    app = require(ksapi.GetKompas(), "No running KOMPAS API session (will not launch one)")
    previous = app.GetActiveDocument()
    doc = None
    try:
        doc = require(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart, True), "New part")
        part = require(ksapi.IKompasDocument3D(doc).GetTopPart(), "Top part")
        part.SetName("Practice Problem 1.1 - stepped block")
        model = require(part.GetModelContainer(), "Model container")
        base = build_base(part, model)
        stair = build_staircase(part, model)
        extrude(model, base, BASE_DEPTH)
        extrude(model, stair, STAIR_DEPTH)
        bounds, holes = validate(part)
        volume = (BASE_LEN * BASE_DEPTH * BASE_H
                  - math.pi * HOLE_R ** 2 * BASE_DEPTH
                  + COL_W * STAIR_DEPTH * COL_H
                  + STEP2_W * STAIR_DEPTH * STEP2_UP
                  + (STEP3_X - COL_W - STEP2_W) * STAIR_DEPTH * (STEP2_UP - STEP3_DROP))
        print(f"bounds={bounds} cylindrical_hole_walls={holes}")
        print(f"analytic volume={volume:.2f} mm3 (reference 72593)")
        require(abs(volume - 72593) < 60, f"Volume off: {volume}")
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists() or output.is_symlink():
            raise FileExistsError(f"Refusing existing output: {output}")
        require(doc.SaveAs(str(output)), "SaveAs")
        require(output.is_file() and output.stat().st_size > 0, "Saved file missing")
        print(f"saved: {output} ({output.stat().st_size} bytes)")
    finally:
        try:
            if doc is not None:
                require(doc.Close(c.kdDoNotSaveChanges), "Close own document")
        finally:
            if previous:
                previous.SetActive()


if __name__ == "__main__":
    main()
