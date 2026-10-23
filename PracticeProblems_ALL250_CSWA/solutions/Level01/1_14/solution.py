# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Practice Problem 1.14: native, dimension-driven plate and centered blade."""
from __future__ import annotations

from contextlib import contextmanager
import json
import math
from pathlib import Path
import tempfile

import ksapi
from constants import constants as c
from constants3d import constants as c3d

ROOT = Path(__file__).resolve().parent
TITLE = "Practice Problem 1.14 — centered blade on mounting plate"
TREE = "Plate sketch (300×175, four Ø20) → extrusion 10 → four R20; blade sketch (120×65, Ø25 at Z55) → symmetric extrusion 10 → two upper R10"


def need(value, label):
    if not value:
        raise RuntimeError(label)
    return value


def report(stage, **data):
    print(json.dumps({"stage": stage, **data}, ensure_ascii=False), flush=True)


def link(obj, kind, partner=None, index=None, partner_index=None, variable=None, value=None):
    con = need(obj.NewConstraint(), "NewConstraint")
    con.SetConstraintType(kind)
    if partner is not None:
        con.SetPartners([partner])
    if index is not None:
        con.SetIndex(index)
    if partner_index is not None:
        con.SetPartnerIndex(partner_index)
    if variable is not None:
        con.SetVariable(variable)
    if value is not None:
        con.SetConstraintValue(value)
    need(con.Create() and con.IsValid(), f"Constraint {kind}, variable {variable}")
    return con


def dimension(symbols, p, q, orientation, name, value, expression=None):
    dim = need(symbols.GetLineDimensions().Add(), "Linear dimension")
    dim.SetX1(p[0]); dim.SetY1(p[1])
    dim.SetX2(q[0]); dim.SetY2(q[1])
    dim.SetX3((p[0]+q[0])/2 + (9 if orientation == c.ksLinDVertical else 0))
    dim.SetY3((p[1]+q[1])/2 - (9 if orientation == c.ksLinDHorizontal else 0))
    dim.SetOrientation(orientation)
    need(dim.Update(), f"Dimension Update {name}")
    need(dim.Associate(), f"Dimension Associate {name}")
    link(dim, c.ksCFixedDim)
    con = need(dim.NewConstraint(), "Dimension variable")
    con.SetConstraintType(c.ksCDimWithVariable)
    con.SetVariable(name)
    con.SetConstraintValue(value)
    if expression is not None:
        con.SetExpression(expression)
    need(con.Create() and con.IsValid(), f"Driving dimension {name}")
    return dim


def radial(symbols, circle, name, radius):
    dim = need(symbols.GetRadialDimensions().Add(), "Radial dimension")
    dim.SetBaseObject(circle)
    dim.SetXc(circle.GetXc()); dim.SetYc(circle.GetYc())
    dim.SetRadius(radius); dim.SetAngle(30.)
    need(dim.Update(), "Radial Update")
    link(dim, c.ksCFixedDim)
    link(dim, c.ksCDimWithVariable, variable=name, value=radius)


def segment(drawing, a, b, style=1):
    obj = need(drawing.GetLineSegments().Add(), "Segment")
    obj.SetX1(a[0]); obj.SetY1(a[1]); obj.SetX2(b[0]); obj.SetY2(b[1])
    obj.SetStyle(style)
    need(obj.Update(), "Segment Update")
    return obj


def circle(drawing, p, radius):
    obj = need(drawing.GetCircles().Add(), "Circle")
    obj.SetXc(p[0]); obj.SetYc(p[1]); obj.SetRadius(radius)
    need(obj.Update(), "Circle Update")
    return obj


def datum(drawing, symbols, prefix):
    obj = segment(drawing, (0., 0.), (1., 0.), 3)
    link(obj, c.ksCFixedPoint, index=0)
    link(obj, c.ksCHorizontal)
    dimension(symbols, (0., 0.), (1., 0.), c.ksLinDHorizontal, prefix+"_datum", 1.)
    return obj


def rectangle(drawing, vertices):
    lines = [segment(drawing, p, q) for p, q in zip(vertices, vertices[1:] + vertices[:1])]
    for i, line in enumerate(lines):
        link(line, c.ksCMergePoints, lines[(i+1) % 4], 1, 0)
        link(line, c.ksCHorizontal if abs(line.GetY2()-line.GetY1()) < 1e-6 else c.ksCVertical)
    return lines


@contextmanager
def sketch(part, model, plane_kind, name, checks):
    obj = need(model.GetSketchs().Add(), "Sketch")
    obj.SetName(name)
    obj.SetPlane(need(part.GetDefaultObject(plane_kind), "Default plane"))
    need(obj.Update(), "Sketch Update")
    points = [obj.GetPoint3D(u, v, 0., 0., 0.) for u, v in [(0.,0.), (1.,0.), (0.,1.)]]
    need(all(p[0] for p in points), "Sketch coordinate system")
    origin = points[0][1:]
    axes = [tuple(p[i+1]-origin[i] for i in range(3)) for p in points[1:]]
    report("sketch-axes", name=name, origin=origin, u=axes[0], v=axes[1])
    def local(p):
        return tuple(sum((p[j]-origin[j])*axis[j] for j in range(3)) for axis in axes)
    fragment = need(obj.BeginEdit(False), "BeginEdit")
    try:
        fragment.SetParametricMode(True)
        need(fragment.IsParametricMode(), "Parametric mode")
        view = need(fragment.GetViewsAndLayersManager().GetViews().GetActiveView(), "Sketch view")
        yield obj, need(ksapi.IDrawingContainer(view), "Drawing"), need(ksapi.ISymbols2DContainer(view), "Symbols"), local
    finally:
        need(obj.EndEdit(), "EndEdit")
    state = obj.GetConstraintsState()
    report("sketch-state", name=name, state=state)
    need(state == c.ksStateWellConstrained, f"Sketch not fully defined: {name}: {state}")
    checks.append(f"{name}: fully defined (GetConstraintsState={state}); native coincidence, H/V and driving dimensions; only datum point anchored")


def extrusion(model, profile, name, symmetric=False):
    op = need(model.GetExtrusions().Add(c3d.o3d_bossExtrusion), "Extrusion")
    op.SetName(name)
    op.SetProfiles([profile])
    op.SetDirection(c3d.dtBoth if symmetric else c3d.dtNormal)
    need(op.SetSideParameters(True, c3d.etBlind, 5. if symmetric else 10., 0., False, None), "Forward extrusion")
    if symmetric:
        need(op.SetSideParameters(False, c3d.etBlind, 5., 0., False, None), "Reverse extrusion")
    need(op.Update(), f"Extrusion Update {name}")
    return op


def fillet(part, model, radius, name, selector, expected):
    need(part.RebuildModel(True), "Rebuild before fillet")
    edges = []
    for obj in ksapi.IFeature(part).GetModelObjects([c3d.o3d_edge]):
        edge = need(ksapi.IEdge(obj), "Edge")
        if not edge.IsStraight():
            continue
        p = edge.GetPoint(True, 0., 0., 0.)
        q = edge.GetPoint(False, 0., 0., 0.)
        need(p[0] and q[0], "Fillet edge endpoints")
        if selector(p[1:], q[1:]):
            edges.append(edge)
    need(len(edges) == expected, f"{name}: expected {expected} edges, found {len(edges)}")
    op = need(model.GetFillets().Add(), "Fillet")
    op.SetName(name); op.SetBaseObjects(edges)
    op.SetBuildingType(c3d.ksFilletCircleArc)
    op.SetRadius1(radius); op.SetTangent(False)
    need(op.Update(), f"Fillet Update {name}")
    return op


def build(part, model, checks):
    with sketch(part, model, c3d.o3d_planeXOY, "01 Plate 300×175; four Ø20", checks) as (plate, drawing, symbols, local):
        datum(drawing, symbols, "plate")
        vertices = [(-150.,-87.5), (150.,-87.5), (150.,87.5), (-150.,87.5)]
        lines = rectangle(drawing, vertices)
        dimension(symbols, vertices[0], vertices[1], c.ksLinDHorizontal, "plate_width", 300.)
        dimension(symbols, vertices[1], vertices[2], c.ksLinDVertical, "plate_depth", 175.)
        dimension(symbols, vertices[0], (0.,0.), c.ksLinDHorizontal, "plate_half_width", 150., "plate_width/2")
        dimension(symbols, vertices[0], (0.,0.), c.ksLinDVertical, "plate_half_depth", 87.5, "plate_depth/2")
        centers = [(-130.,-67.5), (130.,-67.5), (130.,67.5), (-130.,67.5)]
        holes = [circle(drawing, p, 10.) for p in centers]
        dimension(symbols, vertices[0], centers[0], c.ksLinDHorizontal, "hole_edge_x", 20.)
        dimension(symbols, vertices[0], centers[0], c.ksLinDVertical, "hole_edge_y", 20.)
        link(holes[1], c.ksCHAlignPoints, holes[0], 0, 0)
        dimension(symbols, centers[1], vertices[1], c.ksLinDHorizontal, "hole_right_x", 20., "hole_edge_x")
        link(holes[2], c.ksCVAlignPoints, holes[1], 0, 0)
        dimension(symbols, centers[2], vertices[2], c.ksLinDVertical, "hole_top_y", 20., "hole_edge_y")
        link(holes[3], c.ksCVAlignPoints, holes[0], 0, 0)
        link(holes[3], c.ksCHAlignPoints, holes[2], 0, 0)
        radial(symbols, holes[0], "mount_radius", 10.)
        for hole in holes[1:]:
            link(hole, c.ksCEqualRadius, holes[0])
    extrusion(model, plate, "02 Plate thickness 10")
    tol = 1e-5
    fillet(part, model, 20., "03 Four plate corners R20", lambda p,q: all(abs(abs(r[0])-150.)<tol and abs(abs(r[1])-87.5)<tol for r in (p,q)) and abs(p[0]-q[0])<tol and abs(p[1]-q[1])<tol, 4)
    with sketch(part, model, c3d.o3d_planeYOZ, "04 Centered blade 120×65; Ø25", checks) as (blade, drawing, symbols, local):
        origin_guide = datum(drawing, symbols, "blade")
        vertices = [local(p) for p in [(0.,-60.,10.), (0.,60.,10.), (0.,60.,75.), (0.,-60.,75.)]]
        width_horizontal = abs(vertices[0][1]-vertices[1][1]) < tol
        width_orientation = c.ksLinDHorizontal if width_horizontal else c.ksLinDVertical
        height_orientation = c.ksLinDVertical if width_horizontal else c.ksLinDHorizontal
        lines = rectangle(drawing, vertices)
        dimension(symbols, vertices[0], vertices[1], width_orientation, "blade_width", 120.)
        dimension(symbols, vertices[1], vertices[2], height_orientation, "blade_height", 65.)
        dimension(symbols, vertices[0], (0.,0.), width_orientation, "blade_half_width", 60., "blade_width/2")
        dimension(symbols, (0.,0.), vertices[0], height_orientation, "blade_base_z", 10.)
        center = local((0.,0.,55.))
        hole = circle(drawing, center, 12.5)
        # The centre remains on the datum's vertical through its origin.
        link(hole, c.ksCVAlignPoints if width_horizontal else c.ksCHAlignPoints, origin_guide, 0, 0)
        dimension(symbols, (0.,0.), center, height_orientation, "blade_hole_z", 55.)
        radial(symbols, hole, "blade_hole_radius", 12.5)
    extrusion(model, blade, "05 Centered blade thickness 10 (5+5)", symmetric=True)
    fillet(part, model, 10., "06 Two blade top corners R10", lambda p,q: all(abs(abs(r[1])-60.)<tol and abs(r[2]-75.)<tol for r in (p,q)) and abs(p[1]-q[1])<tol and abs(p[2]-q[2])<tol, 2)


def check_tree(part):
    errors, seen = [], set()
    def visit(feature):
        if feature.reference in seen:
            return
        seen.add(feature.reference)
        error = feature.GetObjectError()
        if error:
            errors.append((feature.GetName(), error))
        for child in feature.GetSubFeatures(c.ksOperTree, True, True):
            if child:
                visit(child)
    visit(need(ksapi.IFeature(part), "Part feature"))
    need(not errors, f"Feature errors: {errors}")
    return errors


def absent(path):
    if path.exists() or path.is_symlink():
        raise FileExistsError(str(path))


def main():
    result = {"task":"1.14", "status":"failed", "title":TITLE, "script":"solution.py", "model":None, "volume_mm3":None, "reference_volume":581662, "reference_units":"mm3", "volume_passed":False, "checks":[], "limitations":[], "tree":TREE}
    checks = result["checks"]
    output = Path(tempfile.mkdtemp(prefix="attempt-", dir=ROOT)) / "model.m3d"
    absent(output)
    doc = None
    try:
        app = need(ksapi.GetKompas(), "Existing KOMPAS API session unavailable; no launch attempted")
        doc = need(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart, True), "Own new part document")
        doc3d = need(ksapi.IKompasDocument3D(doc), "3D document")
        part = need(doc3d.GetTopPart(), "Top part")
        part.SetName(TITLE)
        build(part, need(part.GetModelContainer(), "Model container"), checks)
        need(part.RebuildModel(True), "Final rebuild")
        check_tree(part)
        checks.append("Final native operation tree has no feature errors")
        bodies = ksapi.IFeature(part).GetResultBodies()
        need(len(bodies) == 1 and bodies[0].IsSolid(), "One solid body")
        checks.append("Final part contains one solid body")
        mass = need(ksapi.IMassInertiaParam(part), "Mass properties")
        mass.SetLengthUnits(c.ksLUnMM)
        need(mass.GetLengthUnits() == 1, "Mass length units readback must be 1 (mm)")
        need(mass.Calculate() and mass.IsActual(), "Actual mass properties")
        need(mass.GetLengthUnits() == 1, "Mass units after Calculate")
        volume = mass.GetVolume()
        need(math.isfinite(volume) and volume > 0, "Positive finite volume")
        result["volume_mm3"] = volume
        result["volume_passed"] = 581661.5 <= volume < 581662.5
        checks.append(f"IMassInertiaParam.SetLengthUnits(ksLUnMM); GetLengthUnits=1; actual volume={volume:.9f} mm3")
        checks.append(f"Rounding interval [581661.5,581662.5): {result['volume_passed']}")
        absent(output)
        need(doc.SaveAs(str(output)), "SaveAs fresh owned model")
        need(output.is_file() and output.stat().st_size > 0, "Saved nonempty .m3d")
        result["model"] = str(output.relative_to(ROOT))
        checks.append("SaveAs succeeded to previously absent attempt-*/model.m3d; nonempty file exists")
        result["status"] = "passed" if result["volume_passed"] else "partial"
        if not result["volume_passed"]:
            result["limitations"].append("Measured volume is outside reference rounding interval; geometry was not adjusted to volume")
    except Exception as exc:
        result["limitations"].append(f"{type(exc).__name__}: {exc}")
        report("failure", error=str(exc))
    finally:
        if doc is not None:
            try:
                need(doc.Close(c.kdDoNotSaveChanges), "Close own document")
                checks.append("Own document closed in finally; no foreign document changed or closed")
            except Exception as exc:
                result["status"] = "partial" if result["model"] else "failed"
                result["limitations"].append(f"Own document cleanup failed: {exc}")
        (ROOT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        report("result", **result)


if __name__ == "__main__":
    main()
