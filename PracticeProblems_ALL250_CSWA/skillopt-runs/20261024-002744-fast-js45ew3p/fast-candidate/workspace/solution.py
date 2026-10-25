# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Practice Problem 1.1: dimension-driven stepped block with a through hole.

World axes: X right, Y toward the front, Z up.  Origin is the red origin at
the back-left-bottom corner of the base.  XOZ sketches use (u, v) = (X, -Z)
and a positive signed depth extrudes toward +Y.
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

# Front-view outline of the upper staircase, extruded 20 mm from the back face.
UPPER = [
    [0, -30], [48, -30], [48, -38], [32, -38],
    [32, -50], [20, -50], [20, -75], [0, -75],
]
BASE = [[0, 0], [60, 0], [60, -30], [0, -30]]

SPEC: dict[str, Any] = {
    "profiles": [
        {"name": "Base 60x28x30 with through hole", "plane": "XOZ",
         "vertices": BASE, "circles": [[44, -16, 6]], "depth": 28},
        {"name": "Stepped upper block", "plane": "XOZ",
         "vertices": UPPER, "depth": 20},
    ],
    "bounds": [0, 0, 0, 60, 28, 75],
    # 60*28*30 + 20*(48*8 + 32*12 + 20*25) - pi*6^2*28
    "volume": 72593.0,
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
    sketch = require(model.GetSketchs().Add(), "Sketch")
    sketch.SetName(spec.get("name", f"Profile {index}"))
    sketch.SetPlane(require(part.GetDefaultObject(plane), "Plane"))
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
        raise
    require(doc.Close(c.kdDoNotSaveChanges), "Close own document")
    if previous:
        previous.SetActive()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    spec = json.loads(args.spec.read_text()) if args.spec else SPEC
    require(spec, "Set SPEC or pass --spec")
    require(args.output, "Pass --output")
    print(json.dumps(build(spec, args.output.resolve())), flush=True)


if __name__ == "__main__":
    main()
