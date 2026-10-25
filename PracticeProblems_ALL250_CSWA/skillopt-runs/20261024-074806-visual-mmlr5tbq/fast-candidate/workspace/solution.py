# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Practice Problem 1.1: 60 x 28 base, stepped tower, through Ø12 hole."""
from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any

import ksapi
from constants import constants as c
from constants3d import constants as c3d


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


def profile(part: Any, model: Any, plane_obj: Any, vertices: list[list[float]],
            circles: list[list[float]], depth: float, index: int) -> Any:
    """One closed orthogonal profile with native driving dimensions."""
    require(len(vertices) >= 4, "Polygon needs four vertices")
    edges = list(zip(vertices, vertices[1:] + vertices[:1]))
    directions = []
    for p, q in edges:
        dx, dy = q[0] - p[0], q[1] - p[1]
        require((abs(dx) < 1e-9) != (abs(dy) < 1e-9), "Nonorthogonal or zero edge")
        directions.append(abs(dy) < 1e-9)
    require(all(directions[i] != directions[(i + 1) % len(edges)]
                for i in range(len(edges))), "Merge adjacent collinear edges first")
    sketch = require(model.GetSketchs().Add(), "Sketch")
    sketch.SetName(f"Profile {index}")
    sketch.SetPlane(plane_obj)
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
    skip = {max(i for i, h in enumerate(directions) if h),
            max(i for i, h in enumerate(directions) if not h)}
    for i, (p, q) in enumerate(edges):
        if i not in skip:
            length(symbols, p, q, directions[i], f"p{index}_e{i}")
    for j, (x, y, radius) in enumerate(circles):
        circle = require(drawing.GetCircles().Add(), "Circle")
        circle.SetXc(x); circle.SetYc(y); circle.SetRadius(radius)
        require(circle.Update(), "Circle Update")
        length(symbols, vertices[0], [x, y], True, f"p{index}_c{j}_x")
        length(symbols, vertices[0], [x, y], False, f"p{index}_c{j}_y")
        dim = require(symbols.GetRadialDimensions().Add(), "Radius")
        dim.SetBaseObject(circle); dim.SetXc(x); dim.SetYc(y)
        dim.SetRadius(radius); dim.SetAngle(35.)
        require(dim.Update(), "Radius Update")
        drive(dim, f"p{index}_c{j}_r", radius)
    require(sketch.EndEdit(), "EndEdit")
    require(sketch.GetConstraintsState() == c.ksStateWellConstrained, "Underdefined sketch")
    require(math.isfinite(depth) and depth != 0, "Invalid depth")
    operation = require(model.GetExtrusions().Add(c3d.o3d_bossExtrusion), "Extrusion")
    operation.SetProfiles([sketch])
    operation.SetDirection(c3d.dtNormal if depth > 0 else c3d.dtReverse)
    require(operation.SetSideParameters(depth > 0, c3d.etBlind, abs(depth), 0., False, None),
            "Depth")
    require(operation.Update(), "Extrusion Update")
    require(not ksapi.IFeature(operation).GetObjectError(), "Extrusion error")
    return sketch


def build(output: Path | None) -> dict[str, Any]:
    if output is not None:
        require(not output.exists() and not output.is_symlink(), "Output exists")
    app = require(ksapi.GetKompas(), "No existing CAD session")
    previous = app.GetActiveDocument()
    doc = require(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart, True), "New part")
    try:
        part = require(ksapi.IKompasDocument3D(doc).GetTopPart(), "Part")
        model = require(part.GetModelContainer(), "Model")

        # Base: front view 60 x 30, extruded 28 mm along +Y, with a through Ø12 hole.
        base_plane = require(part.GetDefaultObject(c3d.o3d_planeXOZ), "XOZ plane")
        base = profile(part, model, base_plane,
                       [[0., 0.], [60., 0.], [60., -30.], [0., -30.]],
                       [[44., -16., 6.]], 28., 0)

        # Upper steps start at Z=30 on an offset XOY plane and use the back 20 mm.
        auxiliary = require(ksapi.IAuxiliaryGeomContainer(part), "Auxiliary geometry")
        plane = require(auxiliary.GetPlanes3D().Add(c3d.o3d_planeOffset), "Offset plane")
        offset = require(ksapi.IPlane3DByOffset(plane), "Offset-plane interface")
        offset.SetBasePlane(require(part.GetDefaultObject(c3d.o3d_planeXOY), "XOY plane"))
        offset.SetOffset(30.)
        offset.SetDirection(True)
        require(offset.Update(), "Offset plane at Z=30")

        # Incremental rectangular columns on the base; X widths 20/12/12.
        profile(part, model, plane, [[0., 8.], [20., 8.], [20., 28.], [0., 28.]], [], 45., 1)
        profile(part, model, plane, [[20., 8.], [32., 8.], [32., 28.], [20., 28.]], [], 20., 2)
        profile(part, model, plane, [[32., 8.], [44., 8.], [44., 28.], [32., 28.]], [], 8., 3)

        require(part.RebuildModel(True), "Rebuild")
        bodies = ksapi.IFeature(part).GetResultBodies()
        require(len(bodies) == 1 and bodies[0].IsSolid(), "Expected one solid")
        raw = bodies[0].GetGabarit(0., 0., 0., 0., 0., 0.)
        require(raw[0], "Bounds status")
        bounds = list(raw[1:])
        expected_bounds = [0., 0., 0., 60., 28., 75.]
        require(all(abs(a - b) < 1e-5 for a, b in zip(bounds, expected_bounds)),
                f"Signed bounds {bounds} != {expected_bounds}")
        mass = require(ksapi.IMassInertiaParam(part), "Mass")
        mass.SetLengthUnits(c.ksLUnMM)
        require(mass.Calculate(), "Mass calculation")
        volume = mass.GetVolume()
        # Drawing-exact through-hole volume; the supplied 72593 differs by 640 mm3.
        expected_volume = 60 * 28 * 30 + 20 * (20 * 45 + 12 * 20 + 12 * 8) \
            - math.pi * 6 ** 2 * 28
        require(abs(volume - expected_volume) < .5, f"Volume {volume}")
        require(all(s.GetConstraintsState() == c.ksStateWellConstrained for s in (base,)),
                "Base sketch state")
        if output is not None:
            require(not output.exists() and not output.is_symlink(), "Output exists before save")
            require(doc.SaveAs(str(output)), "SaveAs")
            require(output.is_file() and output.stat().st_size > 0, "Missing output")
        result = {"bounds": bounds, "volume": volume, "target_volume": 72593.}
    except BaseException:
        raise
    require(doc.Close(c.kdDoNotSaveChanges), "Close own document")
    if previous:
        previous.SetActive()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(build(args.output.resolve()), flush=True)


if __name__ == "__main__":
    main()
