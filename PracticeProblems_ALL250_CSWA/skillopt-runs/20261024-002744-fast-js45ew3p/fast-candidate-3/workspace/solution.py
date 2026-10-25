# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Practice Problem 1.1 - stepped block with through hole.

Origin at the left/front/bottom corner of the base block (red marker).
Front view: X right, Z up.  Top view: X right, Y away from viewer.
Positive Y points away from the viewer, so the exposed ledge of the base
top face (depth 8) lies at Y = 0..8 and the stacked steps occupy Y = 8..28.

Signed material intervals (mm):
  base   X 0..60  Y 0..28  Z  0..30   with O12 through hole along Y at (44, 16)
  step 1 X 0..48  Y 8..28  Z 30..38
  step 2 X 0..32  Y 8..28  Z 38..50
  column X 0..20  Y 8..28  Z 50..75

All four profiles are XOY rectangles extruded in +Z; the union is exact
because every upper footprint is contained in the base footprint.
Bounding box is asymmetric in X and Z (0..60, 0..28, 0..75).
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import ksapi
from constants import constants as c
from constants3d import constants as c3d

SPEC: dict[str, Any] = {
    "profiles": [
        {
            # Base as an XOZ profile so the O12 bore lives in the base's own
            # extrusion.  XOZ maps (u, v) = (X, -Z) and depth runs along +Y.
            "name": "Base 60x30x28 with O12 bore",
            "plane": "XOZ",
            "vertices": [[0, 0], [60, 0], [60, -30], [0, -30]],
            "circles": [[44, -16, 6]],
            "depth": 28,
        },
        {
            # Staircase above the base, set back to the rear 20 mm (Y 8..28).
            # Sketched on an XOZ-parallel plane 8 mm along +Y; the profile starts
            # at Z=30, so it never re-enters the bore (Z 10..22).
            "name": "Stepped upper block",
            "plane": "XOZ",
            "offset": 8.0,
            "vertices": [[0, -30], [48, -30], [48, -38], [32, -38],
                         [32, -50], [20, -50], [20, -75], [0, -75]],
            "depth": 20,
        },
    ],
    "bounds": [0.0, 0.0, 0.0, 60.0, 28.0, 75.0],
    "volume": 72593.27460518149,
}


def require(value: Any, label: str) -> Any:
    if not value:
        raise RuntimeError(label)
    return value


def constraint(obj: Any, kind: int, **values: Any) -> None:
    item = require(obj.NewConstraint(), "NewConstraint")
    item.SetConstraintType(kind)
    for key, value in values.items():
        getattr(item, "Set" + key)(value)
    require(item.Create() and item.IsValid(), f"Constraint {kind}")


def drive(dim: Any, name: str, value: float) -> None:
    constraint(dim, c.ksCFixedDim)
    constraint(dim, c.ksCDimWithVariable, Variable=name, ConstraintValue=value)


def length(symbols: Any, p: list[float], q: list[float], horizontal: bool,
           name: str) -> None:
    axis = 0 if horizontal else 1
    value = abs(q[axis] - p[axis])
    require(value > 1e-7, "Zero driving dimension")
    dim = require(symbols.GetLineDimensions().Add(), "Dimension")
    dim.SetX1(p[0]); dim.SetY1(p[1])
    dim.SetX2(q[0]); dim.SetY2(q[1])
    dim.SetX3((p[0] + q[0]) / 2 + (0 if horizontal else -7))
    dim.SetY3((p[1] + q[1]) / 2 + (-7 if horizontal else 0))
    dim.SetOrientation(c.ksLinDHorizontal if horizontal else c.ksLinDVertical)
    require(dim.Update() and dim.Associate(), f"Dimension association {name}")
    drive(dim, name, value)


def profile(part: Any, model: Any, spec: dict[str, Any], index: int) -> Any:
    points = spec["vertices"]
    require(len(points) >= 4, "Polygon needs four vertices")
    edges = list(zip(points, points[1:] + points[:1]))
    directions = []
    for p, q in edges:
        dx, dy = q[0] - p[0], q[1] - p[1]
        require((abs(dx) < 1e-9) != (abs(dy) < 1e-9), "Nonorthogonal or zero edge")
        directions.append(abs(dy) < 1e-9)
    require(all(directions[i] != directions[(i + 1) % len(edges)]
                for i in range(len(edges))), "Merge adjacent collinear edges first")
    plane = {"XOY": c3d.o3d_planeXOY, "XOZ": c3d.o3d_planeXOZ}[spec["plane"]]
    base_plane = require(part.GetDefaultObject(plane), "Plane")
    offset = spec.get("offset", 0.0)
    if offset:
        # Shift the sketch plane along its own normal.  XOY normal is +Z; XOZ
        # normal is -Y in this recipe, so a Y placement needs the negated sign.
        auxiliary = require(ksapi.IAuxiliaryGeomContainer(part), "Auxiliary geometry")
        shifted = require(auxiliary.GetPlanes3D().Add(c3d.o3d_planeOffset), "Offset plane")
        offsetter = require(ksapi.IPlane3DByOffset(shifted), "Offset-plane interface")
        offsetter.SetBasePlane(base_plane)
        offsetter.SetOffset(abs(offset))
        offsetter.SetDirection(offset > 0)
        require(offsetter.Update(), "Offset plane update")
        base_plane = shifted
    sketch = require(model.GetSketchs().Add(), "Sketch")
    sketch.SetName(spec.get("name", f"Profile {index}"))
    sketch.SetPlane(base_plane)
    require(sketch.Update(), "Sketch Update")
    fragment = require(sketch.BeginEdit(False), "BeginEdit")
    fragment.SetParametricMode(True)
    view = require(fragment.GetViewsAndLayersManager().GetViews().GetActiveView(), "View")
    drawing, symbols = ksapi.IDrawingContainer(view), ksapi.ISymbols2DContainer(view)
    lines = []
    for p, q in edges:
        line = require(drawing.GetLineSegments().Add(), "Line")
        line.SetX1(p[0]); line.SetY1(p[1]); line.SetX2(q[0]); line.SetY2(q[1])
        require(line.Update(), "Line Update")
        lines.append(line)
    for i, line in enumerate(lines):
        constraint(line, c.ksCMergePoints, Partners=[lines[(i + 1) % len(lines)]],
                   Index=1, PartnerIndex=0)
        constraint(line, c.ksCHorizontal if directions[i] else c.ksCVertical)
    constraint(lines[0], c.ksCFixedPoint, Index=0)
    # Closure supplies the last horizontal and vertical lengths: do not overconstrain.
    skip = {max(i for i, h in enumerate(directions) if h),
            max(i for i, h in enumerate(directions) if not h)}
    for i, (p, q) in enumerate(edges):
        if i not in skip:
            length(symbols, p, q, directions[i], f"p{index}_e{i}")
    for j, (x, y, radius) in enumerate(spec.get("circles", [])):
        circle = require(drawing.GetCircles().Add(), "Circle")
        circle.SetXc(x); circle.SetYc(y); circle.SetRadius(radius)
        require(circle.Update(), "Circle Update")
        length(symbols, points[0], [x, y], True, f"p{index}_c{j}_x")
        length(symbols, points[0], [x, y], False, f"p{index}_c{j}_y")
        dim = require(symbols.GetRadialDimensions().Add(), "Radius")
        dim.SetBaseObject(circle); dim.SetXc(x); dim.SetYc(y)
        dim.SetRadius(radius); dim.SetAngle(35.)
        require(dim.Update(), "Radius Update")
        drive(dim, f"p{index}_c{j}_r", radius)
    require(sketch.EndEdit(), "EndEdit")
    require(sketch.GetConstraintsState() == c.ksStateWellConstrained, "Underdefined sketch")
    depth = spec["depth"]
    require(math.isfinite(depth) and depth != 0, "Invalid signed depth")
    normal = depth > 0
    operation = require(model.GetExtrusions().Add(c3d.o3d_bossExtrusion), "Extrusion")
    operation.SetProfiles([sketch])
    operation.SetDirection(c3d.dtNormal if normal else c3d.dtReverse)
    require(operation.SetSideParameters(normal, c3d.etBlind, abs(depth), 0., False, None), "Depth")
    require(operation.Update(), "Extrusion Update")
    require(not ksapi.IFeature(operation).GetObjectError(), "Extrusion error")
    return sketch


def build(spec: dict[str, Any], output: Path | None) -> dict[str, Any]:
    if output is not None:
        require(not output.exists() and not output.is_symlink(), "Output exists")
    app = require(ksapi.GetKompas(), "No existing CAD session")
    previous = app.GetActiveDocument()
    doc = require(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart, True), "New part")
    # No cleanup after an interrupted/failed native call: session outcome is unknown.
    try:
        part = require(ksapi.IKompasDocument3D(doc).GetTopPart(), "Part")
        model = require(part.GetModelContainer(), "Model")
        sketches = [profile(part, model, item, i) for i, item in enumerate(spec["profiles"])]
        require(part.RebuildModel(True), "Rebuild")
        bodies = ksapi.IFeature(part).GetResultBodies()
        require(len(bodies) == 1 and bodies[0].IsSolid(), "Expected one solid")
        raw = bodies[0].GetGabarit(0., 0., 0., 0., 0., 0.)
        require(raw[0], "Bounds status")
        bounds = list(raw[1:])
        require(all(abs(a - b) < 1e-5 for a, b in zip(bounds, spec["bounds"])),
                f"Signed bounds {bounds} != {spec['bounds']}")
        mass = require(ksapi.IMassInertiaParam(part), "Mass")
        mass.SetLengthUnits(c.ksLUnMM)
        require(mass.Calculate(), "Mass calculation")
        volume = mass.GetVolume()
        require(abs(volume - spec["volume"]) < .5, f"Volume {volume}")
        require(all(s.GetConstraintsState() == c.ksStateWellConstrained for s in sketches), "Sketch state")
        if output is not None:
            require(not output.exists() and not output.is_symlink(), "Output exists before save")
            require(doc.SaveAs(str(output)), "SaveAs")
            require(output.is_file() and output.stat().st_size > 0, "Missing output")
        result = {"bounds": bounds, "volume": volume, "sketches": len(sketches)}
    except BaseException:
        # Preserve stage/traceback and suspect document rather than further API calls.
        raise
    require(doc.Close(c.kdDoNotSaveChanges), "Close own document")
    if previous:
        previous.SetActive()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--qualify", action="store_true")
    args = parser.parse_args()
    if args.qualify:
        raise SystemExit("qualification not used for this task")
    spec = json.loads(args.spec.read_text()) if args.spec else SPEC
    require(spec, "Set SPEC or pass --spec")
    require(args.output, "Pass --output")
    print(json.dumps(build(spec, args.output.resolve())), flush=True)


if __name__ == "__main__":
    main()
