# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Native dimension-driven orthogonal profiles on XOY/XOZ, with signed extrusion.

Copy this standalone recipe and set SPEC, or pass --spec part.json --output part.m3d.
Coordinates are sketch-local: native XOZ maps (u,v) to (X,0,-Z).
Each profile has vertices, optional circles [u,v,r], plane, and signed depth.
One vertex anchors each polygon; lengths, coincidences and H/V drive its shape.
Circle positions are dimensioned from the anchor; circles on its axes are not
supported by this recipe. Nonorthogonal polygons require another recipe.
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
            "plane": "XOZ",
            "vertices": [[0, 0], [60, 0], [60, -30], [0, -30]],
            "circles": [[44, -16, 6]],
            "depth": -28,
        },
        {
            "plane": "XOZ",
            "vertices": [[0, -30], [0, -75], [20, -75], [20, -50],
                         [32, -50], [32, -38], [48, -38], [48, -30]],
            "depth": -20,
        },
    ],
    "bounds": [0, -28, 0, 60, 0, 75],
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
        for plane, sign in (("XOY", 1), ("XOY", -1), ("XOZ", 1), ("XOZ", -1)):
            low, high = sorted([0., sign * 6.])
            bounds = ([0., 0., low, 43., 27., high] if plane == "XOY" else
                      [0., low, -27., 43., high, 0.])
            spec = {"profiles": [{"plane": plane, "vertices": [[0, 0], [43, 0], [43, 27], [0, 27]],
                                  "circles": [[11, 9, 3.5]], "depth": sign * 6}],
                    "bounds": bounds, "volume": (43 * 27 - math.pi * 3.5 ** 2) * 6}
            print(json.dumps({"plane": plane, "sign": sign, **build(spec, None)}), flush=True)
        spec = {"profiles": [
            {"plane": "XOZ", "vertices": [[0, 0], [47, 0], [47, -19], [0, -19]],
             "circles": [[13, -8, 2.5]], "depth": -17},
            {"plane": "XOZ", "vertices": [[0, -19], [35, -19], [35, -26], [22, -26],
                                             [22, -39], [9, -39], [9, -53], [0, -53]], "depth": -11}],
                "bounds": [0, -17, 0, 47, 0, 53],
                "volume": (47 * 19 - math.pi * 2.5 ** 2) * 17 + (35 * 7 + 22 * 13 + 9 * 14) * 11}
        print(json.dumps({"qualification": "two signed profiles and negative local coordinates",
                          **build(spec, None)}), flush=True)
    else:
        spec = json.loads(args.spec.read_text()) if args.spec else SPEC
        require(spec, "Set SPEC or pass --spec")
        require(args.output, "Pass --output")
        print(json.dumps(build(spec, args.output.resolve())), flush=True)


if __name__ == "__main__":
    main()
