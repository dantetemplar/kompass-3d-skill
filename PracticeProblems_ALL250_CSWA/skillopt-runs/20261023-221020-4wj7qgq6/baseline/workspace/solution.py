# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Practice Problem 1.1 - stepped block, native KsAPI part.

Geometry (mm, origin at back-left-bottom as indicated in red):
  base            60 x 28 x 30
  tower           X 0..20,  Y 0..20, Z 30..75
  step 1          X 20..32, Y 0..20, Z 30..50
  step 2          X 32..48, Y 0..20, Z 30..38
  through hole    D12 on the front face, centre 16 from right edge, 16 above bottom,
                  axis along Y through the 28 mm base.
Volume = 60*28*30 + 20*20*45 + 12*20*20 + 16*20*8 - pi*6^2*28 = 72593.27 mm3.

Sketches are fully defined with native driving dimensions (sizes + hole offsets)
and one minimal fixed-point anchor each, not frozen geometry.
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
DrawingT = TypeVar("DrawingT", bound=ksapi.IDrawingObject)
Point2 = tuple[float, float]
Point3 = tuple[float, float, float]
Bounds = tuple[float, float, float, float, float, float]

OUT = Path(__file__).resolve().parent / "model.m3d"
TOL = 1e-5

BASE_W, BASE_D, BASE_H = 60.0, 28.0, 30.0
TOWER_W, STEP1_W, STEP2_W = 20.0, 12.0, 16.0
UPPER_D = 20.0
TOWER_ABOVE = 45.0          # 75 - 30
STEP1_ABOVE = 20.0          # 50 - 30
STEP2_ABOVE = 8.0           # 38 - 30
HOLE_R = 6.0
HOLE_FROM_RIGHT = 16.0
HOLE_FROM_BOTTOM = 16.0


def require(value: T | None, message: str) -> T:
    if not value:
        raise RuntimeError(message)
    return value


def dot(a: Point3, b: Point3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def require_close(actual: float, expected: float, message: str) -> None:
    if not (math.isfinite(actual) and abs(actual - expected) <= TOL):
        raise RuntimeError(f"{message}: {actual}; expected {expected}")


@contextmanager
def edit(sketch: ksapi.ISketch) -> Iterator[tuple[ksapi.ISketch, ksapi.IKompasDocument2D, ksapi.IView]]:
    require(sketch.Update(), "Sketch plane")
    fragment = require(sketch.BeginEdit(False), "BeginEdit")
    try:
        fragment.SetParametricMode(True)
        require(fragment.IsParametricMode(), "Parametric mode")
        view = require(fragment.GetViewsAndLayersManager().GetViews().GetActiveView(), "Sketch view")
        yield sketch, fragment, view
    finally:
        require(sketch.EndEdit(), "EndEdit")
    state = sketch.GetConstraintsState()
    require(state == c.ksStateWellConstrained, f"Sketch not fully defined: {state}")


def plane_map(sketch: ksapi.ISketch) -> tuple[Point3, Point3, Point3]:
    r0 = sketch.GetPoint3D(0.0, 0.0, 0.0, 0.0, 0.0)
    ru = sketch.GetPoint3D(1.0, 0.0, 0.0, 0.0, 0.0)
    rv = sketch.GetPoint3D(0.0, 1.0, 0.0, 0.0, 0.0)
    require(r0[0] and ru[0] and rv[0], f"Sketch plane query failed: {r0} {ru} {rv}")
    return (r0[1], r0[2], r0[3]), (ru[1], ru[2], ru[3]), (rv[1], rv[2], rv[3])


def uv(p0: Point3, eu: Point3, ev: Point3, point: Point3) -> Point2:
    d = (point[0] - p0[0], point[1] - p0[1], point[2] - p0[2])
    return dot(d, eu) / dot(eu, eu), dot(d, ev) / dot(ev, ev)


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
    item.SetConstraintType(kind)  # type: ignore[arg-type]
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
    require(result and item.IsValid(), f"Constraint creation failed: type={kind}, name={name}")
    return item


def driving_dimension(dim: DrawingT, name: str, value: float) -> DrawingT:
    constraint(dim, c.ksCFixedDim)
    constraint(dim, c.ksCDimWithVariable, name=name, value=value)
    return dim


def linear_dimension(
    symbols: ksapi.ISymbols2DContainer,
    points: Sequence[Point2],
    orientation: int,
    partners: Sequence[tuple[ksapi.IDrawingObject, int]],
    name: str,
    value: float,
) -> ksapi.ILineDimension:
    dim = require(symbols.GetLineDimensions().Add(), f"Linear dimension {name}")
    (x1, y1), (x2, y2), (x3, y3) = points
    dim.SetX1(x1); dim.SetY1(y1)
    dim.SetX2(x2); dim.SetY2(y2)
    dim.SetX3(x3); dim.SetY3(y3)
    dim.SetOrientation(orientation)
    require(dim.Update(), f"Linear dimension Update {name}")
    require(dim.Associate(), f"Associate {name}")
    for dimension_index, (partner, point_index) in enumerate(partners):
        require(any(item.IsValid() and item.GetConstraintType() == c.ksCMergePoints
                    and item.GetIndex() == dimension_index
                    and item.GetPartnerIndex() == point_index
                    and any(obj.GetId() == partner.GetId() for obj in item.GetPartners())
                    for item in dim.GetConstraints()),
                f"Missing witness-point association: {name}/{dimension_index}")
    return driving_dimension(dim, name, value)


def radial_dimension(
    symbols: ksapi.ISymbols2DContainer, circle: ksapi.ICircle,
    u: float, v: float, name: str, radius: float,
) -> ksapi.IDrawingObject:
    radial = require(symbols.GetRadialDimensions().Add(), "Radial dimension")
    radial.SetBaseObject(circle)
    radial.SetXc(u)
    radial.SetYc(v)
    radial.SetRadius(radius)
    radial.SetAngle(35.0)
    require(radial.Update(), "Radial dimension Update")
    assoc = [item for item in radial.GetConstraints() if item.GetConstraintType() == c.ksCAssociation]
    require(len(assoc) == 1 and assoc[0].IsValid(), "Radial dimension association")
    return driving_dimension(radial, name, radius)


def add_rectangle(
    drawing: ksapi.IDrawingContainer,
    p0: Point2, p1: Point2, p2: Point2, p3: Point2,
) -> list[ksapi.ILineSegment]:
    pts = [p0, p1, p2, p3]
    lines: list[ksapi.ILineSegment] = []
    for start, end in zip(pts, pts[1:] + pts[:1]):
        line = require(drawing.GetLineSegments().Add(), "Segment")
        line.SetX1(start[0]); line.SetY1(start[1])
        line.SetX2(end[0]); line.SetY2(end[1])
        require(line.Update(), "Segment Update")
        lines.append(line)
    return lines


def close_rect(lines: Sequence[ksapi.IDrawingObject]) -> None:
    n = len(lines)
    for i, line in enumerate(lines):
        constraint(line, c.ksCMergePoints, partners=[lines[(i + 1) % n]], index=1, partner_index=0)
        constraint(line, c.ksCHorizontal if i % 2 == 0 else c.ksCVertical)


def extrude(
    model: ksapi.IModelContainer, sketch: ksapi.ISketch, kind: int,
    depth: float, normal: Point3,
) -> ksapi.IExtrusion:
    operation = require(model.GetExtrusions().Add(kind), "Extrusion")
    operation.SetProfiles([sketch])
    operation.SetDirection(c3d.dtNormal if normal[1] > 0 else c3d.dtReverse)
    require(operation.SetSideParameters(True, c3d.etBlind, depth, 0.0, False, None), "Depth")
    require(operation.Update(), "Extrusion Update")
    return operation


def build(part: ksapi.IPart, model: ksapi.IModelContainer) -> None:
    # ---- front profile on XOZ: 60 x 30 base + D12 through hole (axis along Y)
    base = require(model.GetSketchs().Add(), "Base sketch")
    base.SetName("Base 60x28x30 + hole D12")
    base.SetPlane(require(part.GetDefaultObject(c3d.o3d_planeXOZ), "XOZ plane"))
    require(base.Update(), "Base sketch plane")
    p0, eu, ev = plane_map(base)
    normal = (eu[1] * ev[2] - eu[2] * ev[1],
              eu[2] * ev[0] - eu[0] * ev[2],
              eu[0] * ev[1] - eu[1] * ev[0])
    require(abs(normal[1]) > 0.99, f"Unexpected XOZ normal: {normal}")
    with edit(base) as (_, _, view):
        drawing = require(ksapi.IDrawingContainer(view), "Drawing container")
        symbols = require(ksapi.ISymbols2DContainer(view), "Symbols container")
        A = uv(p0, eu, ev, (0.0, 0.0, 0.0))
        B = uv(p0, eu, ev, (BASE_W, 0.0, 0.0))
        C = uv(p0, eu, ev, (BASE_W, 0.0, BASE_H))
        D = uv(p0, eu, ev, (0.0, 0.0, BASE_H))
        lines = add_rectangle(drawing, A, B, C, D)
        close_rect(lines)
        constraint(lines[0], c.ksCFixedPoint, index=0)   # anchor at the part origin
        hole_u, hole_v = uv(p0, eu, ev, (BASE_W - HOLE_FROM_RIGHT, 0.0, HOLE_FROM_BOTTOM))
        circle = require(drawing.GetCircles().Add(), "Hole circle")
        circle.SetXc(hole_u); circle.SetYc(hole_v); circle.SetRadius(HOLE_R)
        require(circle.Update(), "Hole circle Update")
        hmid = ((A[0] + B[0]) / 2, (A[1] + B[1]) / 2 - 12.0)
        vmid = ((B[0] + C[0]) / 2 + 12.0, (B[1] + C[1]) / 2)
        linear_dimension(symbols, [A, B, hmid], c.ksLinDHorizontal, [(lines[0], 0), (lines[0], 1)], "base_width", BASE_W)
        linear_dimension(symbols, [B, C, vmid], c.ksLinDVertical, [(lines[1], 0), (lines[1], 1)], "base_height", BASE_H)
        linear_dimension(symbols, [B, (hole_u, hole_v), (hmid[0], hmid[1] - 8.0)], c.ksLinDHorizontal, [(lines[1], 0), (circle, 0)], "hole_from_right", HOLE_FROM_RIGHT)
        linear_dimension(symbols, [A, (hole_u, hole_v), (vmid[0] + 8.0, vmid[1])], c.ksLinDVertical, [(lines[0], 0), (circle, 0)], "hole_from_bottom", HOLE_FROM_BOTTOM)
        radial_dimension(symbols, circle, hole_u, hole_v, "hole_radius", HOLE_R)
    base_op = extrude(model, base, c3d.o3d_bossExtrusion, BASE_D, normal)

    # ---- stepped upper structure: profile in XZ, Y 0..20
    stair = require(model.GetSketchs().Add(), "Stair sketch")
    stair.SetName("Tower and steps")
    stair.SetPlane(require(part.GetDefaultObject(c3d.o3d_planeXOZ), "XOZ plane"))
    q0, qu, qv = plane_map(stair)
    qn = (qu[1] * qv[2] - qu[2] * qv[1],
          qu[2] * qv[0] - qu[0] * qv[2],
          qu[0] * qv[1] - qu[1] * qv[0])
    with edit(stair) as (_, _, view):
        drawing = require(ksapi.IDrawingContainer(view), "Drawing container")
        symbols = require(ksapi.ISymbols2DContainer(view), "Symbols container")
        s1, s2 = STEP1_W, TOWER_W + STEP1_W
        s3 = TOWER_W + STEP1_W + STEP2_W
        pts3: list[Point3] = [
            (0.0, 0.0, BASE_H),
            (0.0, 0.0, BASE_H + TOWER_ABOVE),
            (TOWER_W, 0.0, BASE_H + TOWER_ABOVE),
            (TOWER_W, 0.0, BASE_H + STEP1_ABOVE),
            (s2, 0.0, BASE_H + STEP1_ABOVE),
            (s2, 0.0, BASE_H + STEP2_ABOVE),
            (s3, 0.0, BASE_H + STEP2_ABOVE),
            (s3, 0.0, BASE_H),
        ]
        pts = [uv(q0, qu, qv, p) for p in pts3]
        stair_lines: list[ksapi.ILineSegment] = []
        for start, end in zip(pts, pts[1:] + pts[:1]):
            line = require(drawing.GetLineSegments().Add(), "Segment")
            line.SetX1(start[0]); line.SetY1(start[1])
            line.SetX2(end[0]); line.SetY2(end[1])
            require(line.Update(), "Segment Update")
            stair_lines.append(line)
        n = len(stair_lines)
        for i, line in enumerate(stair_lines):
            constraint(line, c.ksCMergePoints, partners=[stair_lines[(i + 1) % n]], index=1, partner_index=0)
            constraint(line, c.ksCHorizontal if i % 2 == 1 else c.ksCVertical)
        constraint(stair_lines[0], c.ksCFixedPoint, index=0)  # anchor bottom-left at z=30
        L = stair_lines
        dims = [
            ([(pts[0], pts[1], (0.0, 0.0))], c.ksLinDVertical, [(L[0], 0), (L[0], 1)], "tower_height", TOWER_ABOVE),
            ([(pts[0], pts[3], (0.0, 0.0))], c.ksLinDVertical, [(L[0], 0), (L[3], 0)], "step1_height", STEP1_ABOVE),
            ([(pts[4], pts[5], (0.0, 0.0))], c.ksLinDVertical, [(L[4], 0), (L[4], 1)], "step2_height", STEP1_ABOVE - STEP2_ABOVE),
            ([(pts[1], pts[2], (0.0, 0.0))], c.ksLinDHorizontal, [(L[1], 0), (L[1], 1)], "tower_width", TOWER_W),
            ([(pts[3], pts[4], (0.0, 0.0))], c.ksLinDHorizontal, [(L[3], 0), (L[3], 1)], "step1_width", STEP1_W),
            ([(pts[7], pts[0], (0.0, 0.0))], c.ksLinDHorizontal, [(L[7], 0), (L[7], 1)], "upper_span", TOWER_W + STEP1_W + STEP2_W),
        ]
        for points, orientation, partners, name, value in dims:
            (p1, p2, _), = points
            if orientation == c.ksLinDHorizontal:
                loc = ((p1[0] + p2[0]) / 2, max(p[1] for p in pts) + 6.0)
            else:
                loc = (max(p[0] for p in pts) + 6.0, (p1[1] + p2[1]) / 2)
            linear_dimension(symbols, [p1, p2, loc], orientation, partners, name, value)
    extrude(model, stair, c3d.o3d_bossExtrusion, UPPER_D, qn)
    _ = base_op


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
            errors.append((list(path), error))
        for child in item.GetSubFeatures(c.ksOperTree, True, True):
            if child:
                visit(child, path)

    visit(require(ksapi.IFeature(part), "Part feature"), [])
    return errors


def validate(part: ksapi.IPart) -> Bounds:
    require(part.RebuildModel(True), "RebuildModel")
    root = require(ksapi.IFeature(part), "Part feature")
    bodies = root.GetResultBodies()
    require(len(bodies) == 1 and bodies[0].IsSolid(), f"Expected one solid: {len(bodies)}")
    raw = bodies[0].GetGabarit(0, 0, 0, 0, 0, 0)
    require(raw[0], "Body bounds")
    bounds = tuple(raw[1:])
    expected = (0.0, 0.0, 0.0, BASE_W, BASE_D, BASE_H + TOWER_ABOVE)
    for actual, want in zip(bounds, expected):
        require_close(actual, want, "Bounds")
    mass = require(ksapi.IMassInertiaParam(part), "Mass inertia")
    mass.SetLengthUnits(c.ksLUnMM)
    require(mass.Calculate(), "Mass calculation")
    volume = mass.GetVolume()
    expected_volume = (BASE_W * BASE_D * BASE_H
                       + TOWER_W * UPPER_D * TOWER_ABOVE
                       + STEP1_W * UPPER_D * STEP1_ABOVE
                       + STEP2_W * UPPER_D * STEP2_ABOVE
                       - math.pi * HOLE_R ** 2 * BASE_D)
    if not (math.isfinite(volume) and abs(volume - expected_volume) <= 0.05):
        raise RuntimeError(f"Volume {volume}; expected {expected_volume}")
    # One cylindrical wall, axis along Y, radius 6, spanning the full 28 mm depth.
    cylinder_faces = 0
    for obj in root.GetModelObjects([c3d.o3d_face]):
        face = require(ksapi.IFace(obj), "Face")
        if not face.IsCylinder():
            continue
        cylinder_faces += 1
        require_close(face.GetRadius(), HOLE_R, "Hole radius")
        rims = []
        for edge in face.GetLimitingEdges():
            if edge.IsCircle():
                g = require(edge.GetMathCurve(), "Rim curve").GetGabarit(0, 0, 0, 0, 0, 0)
                require(g[0], "Rim bounds")
                rims.append(g[1:])
        require(len(rims) == 2, f"Hole rims: {len(rims)}")
        for xmin, ymin, zmin, xmax, ymax, zmax in rims:
            require_close((xmax - xmin) / 2, HOLE_R, "Rim X radius")
            require_close((zmax - zmin) / 2, HOLE_R, "Rim Z radius")
        ys = sorted(min(r[1], r[4]) for r in rims)
        require_close(ys[0], 0.0, "Hole start Y")
        require_close(ys[1], BASE_D, "Hole end Y")
        centers = [((r[0] + r[3]) / 2, (r[2] + r[5]) / 2) for r in rims]
        require_close(centers[0][0], BASE_W - HOLE_FROM_RIGHT, "Hole centre X")
        require_close(centers[0][1], HOLE_FROM_BOTTOM, "Hole centre Z")
        require_close(centers[0][0], centers[1][0], "Hole axis X")
        require_close(centers[0][1], centers[1][1], "Hole axis Z")
    require(cylinder_faces == 1, f"Cylindrical faces: {cylinder_faces}")
    errors = feature_errors(part)
    require(not errors, f"Feature tree errors: {errors}")
    print(f"Validation: volume={volume:.3f} mm3 (target 72593), bounds={bounds}, "
          f"hole=R{HOLE_R} along Y, centres=({BASE_W - HOLE_FROM_RIGHT}, {HOLE_FROM_BOTTOM})")
    return bounds


def main() -> None:
    output = OUT.absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"Refusing to overwrite: {output}")
    app = require(ksapi.GetKompas(), "No running KOMPAS API session; will not launch one")
    previous = app.GetActiveDocument()
    owned: list[ksapi.IKompasDocument] = []
    try:
        doc = require(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart, True), "New part")
        owned.append(doc)
        doc3d = require(ksapi.IKompasDocument3D(doc), "3D document")
        part = require(doc3d.GetTopPart(), "Top part")
        part.SetName("PracticeProblem 1.1 - stepped block")
        model = require(part.GetModelContainer(), "Model container")
        build(part, model)
        validate(part)
        if output.exists() or output.is_symlink():
            raise FileExistsError(f"Refusing to overwrite: {output}")
        require(doc.SaveAs(str(output)), "SaveAs model.m3d")
        require(output.is_file() and output.stat().st_size > 0, "Saved file missing or empty")
        print(f"Saved: {output} ({output.stat().st_size} bytes)")
    finally:
        try:
            for item in reversed(owned):
                require(item.Close(c.kdDoNotSaveChanges), "Close own document")
        finally:
            if previous:
                previous.SetActive()


if __name__ == "__main__":
    main()
