# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""SOLIDWORKS 1.12: native, dimension-driven KOMPAS bracket, millimetres."""
from contextlib import contextmanager
import json
import math
from pathlib import Path
import tempfile
import traceback

import ksapi
from constants import constants as c
from constants3d import constants as c3d

ROOT = Path(__file__).resolve().parent
TREE = "Основание 125×75×10 с Ø20 → задняя стенка 125×10, высота 65 → боковая косынка 10, скос от (10,65) до (75,10)"


def require(value, message):
    if not value:
        raise RuntimeError(message)
    return value


def stage(message, **data):
    print(json.dumps({"stage": message, **data}, ensure_ascii=False), flush=True)


def constraint(obj, kind, *, partners=(), index=None, partner_index=None, name=None, value=None):
    item = require(obj.NewConstraint(), "NewConstraint")
    item.SetConstraintType(kind)
    if partners:
        item.SetPartners(list(partners))
    if index is not None:
        item.SetIndex(index)
    if partner_index is not None:
        item.SetPartnerIndex(partner_index)
    if name is not None:
        item.SetVariable(name)
    if value is not None:
        item.SetConstraintValue(value)
    require(item.Create() and item.IsValid(), f"Constraint {kind}, {name}")
    return item


def driving(dim, name, value):
    constraint(dim, c.ksCFixedDim)
    constraint(dim, c.ksCDimWithVariable, name=name, value=value)
    return dim


def dimension(symbols, start, end, text, horizontal, name, value):
    dim = require(symbols.GetLineDimensions().Add(), "Linear dimension")
    dim.SetX1(start[0]); dim.SetY1(start[1])
    dim.SetX2(end[0]); dim.SetY2(end[1])
    dim.SetX3(text[0]); dim.SetY3(text[1])
    dim.SetOrientation(c.ksLinDHorizontal if horizontal else c.ksLinDVertical)
    require(dim.Update(), f"Dimension Update {name}")
    require(dim.Associate(), f"Dimension Associate {name}")
    return driving(dim, name, value)


@contextmanager
def edit_sketch(part, model, plane, name, checks):
    sketch = require(model.GetSketchs().Add(), "Sketch")
    sketch.SetName(name)
    sketch.SetPlane(require(part.GetDefaultObject(plane), "Default plane"))
    require(sketch.Update(), "Sketch plane Update")
    axes = []
    for uv in ((0, 0), (1, 0), (0, 1)):
        point = sketch.GetPoint3D(*uv, 0, 0, 0)
        require(point[0], "GetPoint3D")
        axes.append(point[1:])
    stage("sketch axes", name=name, points=axes)
    fragment = require(sketch.BeginEdit(False), "BeginEdit")
    try:
        fragment.SetParametricMode(True)
        require(fragment.IsParametricMode(), "Parametric mode")
        view = require(fragment.GetViewsAndLayersManager().GetViews().GetActiveView(), "Sketch view")
        yield sketch, require(ksapi.IDrawingContainer(view), "Drawing"), require(ksapi.ISymbols2DContainer(view), "Symbols"), axes
    finally:
        require(sketch.EndEdit(), "EndEdit")
    state = sketch.GetConstraintsState()
    stage("sketch completed", name=name, constraints_state=state)
    require(state == c.ksStateWellConstrained, f"Sketch {name} not fully constrained: {state}")
    checks.append({"check": "fully_defined_sketch", "name": name, "state": state, "passed": True})


def polygon(drawing, vertices):
    lines = []
    for start, end in zip(vertices, vertices[1:] + vertices[:1]):
        obj = require(drawing.GetLineSegments().Add(), "Line")
        obj.SetX1(start[0]); obj.SetY1(start[1])
        obj.SetX2(end[0]); obj.SetY2(end[1])
        require(obj.Update(), "Line Update")
        lines.append(obj)
    for i, obj in enumerate(lines):
        constraint(obj, c.ksCMergePoints, partners=[lines[(i + 1) % len(lines)]], index=1, partner_index=0)
        start, end = vertices[i], vertices[(i + 1) % len(vertices)]
        if abs(start[0] - end[0]) < 1e-8:
            constraint(obj, c.ksCVertical)
        elif abs(start[1] - end[1]) < 1e-8:
            constraint(obj, c.ksCHorizontal)
    constraint(lines[0], c.ksCFixedPoint, index=0)
    return lines


def extrude(model, sketch, depth, name, reverse=False):
    op = require(model.GetExtrusions().Add(c3d.o3d_bossExtrusion), "Boss extrusion")
    op.SetName(name)
    op.SetProfiles([sketch])
    op.SetDirection(c3d.dtReverse if reverse else c3d.dtNormal)
    require(op.SetSideParameters(not reverse, c3d.etBlind, depth, 0, False, None), "Depth")
    require(op.Update(), f"Extrusion Update {name}")
    stage("operation created", name=name)
    return op


def build(part, model, checks):
    with edit_sketch(part, model, c3d.o3d_planeXOY, "Основание и отверстие Ø20", checks) as (sk, drawing, symbols, axes):
        require(axes == [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)], "Unexpected XOY axes")
        polygon(drawing, [(0, 0), (125, 0), (125, 75), (0, 75)])
        hole = require(drawing.GetCircles().Add(), "Hole circle")
        hole.SetXc(62.5); hole.SetYc(50); hole.SetRadius(10)
        require(hole.Update(), "Circle Update")
        dimension(symbols, (0, 0), (125, 0), (60, -15), True, "base_width", 125)
        dimension(symbols, (125, 0), (125, 75), (145, 40), False, "base_depth", 75)
        dimension(symbols, (0, 0), (62.5, 50), (35, -25), True, "hole_x", 62.5)
        # The drawing locates the hole 25 mm from the front edge (Y=75).
        dimension(symbols, (125, 75), (62.5, 50), (160, 60), False, "hole_front_offset", 25)
        radial = require(symbols.GetRadialDimensions().Add(), "Hole radial dimension")
        radial.SetBaseObject(hole)
        radial.SetXc(62.5); radial.SetYc(50); radial.SetRadius(10); radial.SetAngle(35)
        require(radial.Update(), "Radial Update")
        driving(radial, "hole_radius", 10)
    extrude(model, sk, 10, "Основание, толщина 10")

    with edit_sketch(part, model, c3d.o3d_planeXOY, "Сечение задней стенки 125×10", checks) as (sk, drawing, symbols, axes):
        polygon(drawing, [(0, 0), (125, 0), (125, 10), (0, 10)])
        dimension(symbols, (0, 0), (125, 0), (60, -15), True, "wall_width", 125)
        dimension(symbols, (125, 0), (125, 10), (140, 5), False, "wall_thickness", 10)
    extrude(model, sk, 10 + 55, "Задняя стенка, 55 над основанием")

    with edit_sketch(part, model, c3d.o3d_planeYOZ, "Боковая косынка, профиль 75×65", checks) as (sk, drawing, symbols, axes):
        origin, pu, pv = axes
        u = tuple(pu[i] - origin[i] for i in range(3))
        v = tuple(pv[i] - origin[i] for i in range(3))
        normal = (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])
        require(abs(abs(normal[0])-1) < 1e-8, "YOZ normal must be X")
        def local(y, z):
            point = (0, y, z)
            return tuple(sum((point[i]-origin[i])*axis[i] for i in range(3)) for axis in (u, v))
        pts = [local(0, 0), local(75, 0), local(75, 10), local(10, 65), local(0, 65)]
        polygon(drawing, pts)
        def edge_dimension(a, b, text, name, value):
            start, end = pts[a], pts[b]
            horizontal = abs(start[1]-end[1]) < 1e-8
            dimension(symbols, start, end, local(*text), horizontal, name, value)
        edge_dimension(0, 1, (35, -15), "gusset_depth", 75)
        edge_dimension(1, 2, (90, 5), "gusset_base_thickness", 10)
        edge_dimension(3, 4, (5, 80), "gusset_back_thickness", 10)
        edge_dimension(4, 0, (-15, 35), "gusset_total_height", 65)
    extrude(model, sk, 10, "Боковая косынка, толщина 10", reverse=normal[0] < 0)
    require(part.RebuildModel(True), "RebuildModel")


def check_tree(part):
    seen, errors = set(), []
    def visit(item):
        if item.reference in seen:
            return
        seen.add(item.reference)
        error = item.GetObjectError()
        if error:
            errors.append({"name": item.GetName(), "error": error})
        for child in item.GetSubFeatures(c.ksOperTree, True, True):
            if child:
                visit(child)
    feature = require(ksapi.IFeature(part), "Part feature")
    visit(feature)
    require(not errors, f"Feature errors: {errors}")
    bodies = feature.GetResultBodies()
    require(len(bodies) == 1 and bodies[0].IsSolid(), "One solid body")
    return {"check": "native_tree_and_solid", "feature_errors": errors, "solid_count": 1, "passed": True}


def main():
    result = {"task": "1.12", "status": "failed", "title": "Practice Problem 1.12 — угловой кронштейн с косынкой", "script": "solution.py", "model": None, "volume_mm3": None, "reference_volume": 177233, "reference_units": "mm3", "volume_passed": False, "checks": [], "limitations": [], "tree": TREE}
    doc = None
    output = Path(tempfile.mkdtemp(prefix="attempt-", dir=ROOT)) / "model.m3d"
    try:
        require(not output.exists(), "Output exists before document creation")
        app = require(ksapi.GetKompas(), "No running KOMPAS API session; launch is forbidden")
        doc = require(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart, True), "Own new document")
        part = require(ksapi.IKompasDocument3D(doc).GetTopPart(), "Top part")
        part.SetName("1.12 — угловой кронштейн")
        build(part, require(part.GetModelContainer(), "Model container"), result["checks"])
        result["checks"].append(check_tree(part))
        mass = require(ksapi.IMassInertiaParam(part), "Mass properties")
        mass.SetLengthUnits(c.ksLUnMM)
        units = mass.GetLengthUnits()
        require(units == 1, f"Mass units readback: {units}")
        require(mass.Calculate(), "Mass Calculate")
        require(mass.IsActual(), "Mass IsActual")
        volume = mass.GetVolume()
        require(math.isfinite(volume) and volume > 0, "Invalid volume")
        result["volume_mm3"] = volume
        result["volume_passed"] = 177232.5 <= volume < 177233.5
        result["checks"].append({"check": "volume_rounding_interval_mm3", "length_units_readback": units, "interval": [177232.5, 177233.5], "actual": volume, "passed": result["volume_passed"]})
        require(not output.exists() and not output.is_symlink(), "SaveAs path already exists")
        require(doc.SaveAs(str(output)), "SaveAs")
        require(output.is_file() and output.stat().st_size > 0, "Saved file missing or empty")
        result["model"] = str(output.relative_to(ROOT))
        result["checks"].append({"check": "native_save_new_path", "passed": True})
        result["status"] = "passed" if result["volume_passed"] else "partial"
        if not result["volume_passed"]:
            result["limitations"].append("Объём вне интервала округления эталона; геометрия не подгонялась.")
    except Exception as error:
        result["limitations"].append(f"{type(error).__name__}: {error}")
        traceback.print_exc()
    finally:
        if doc is not None:
            try:
                require(doc.Close(c.kdDoNotSaveChanges), "Close own document")
                result["checks"].append({"check": "own_document_closed", "passed": True})
            except Exception as error:
                result["limitations"].append(f"Closing own document: {error}")
                result["status"] = "partial" if result["model"] else "failed"
        (ROOT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        stage("result", **result)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
