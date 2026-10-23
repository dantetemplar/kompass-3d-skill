# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Practice Problem 2.9: native dimension-driven KOMPAS model, no exports."""
from __future__ import annotations

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
TITLE = "SOLIDWORKS Practice Problem 2.9 — mounting plate"
TREE = "Plate sketch → Boss 2 mm → Six-circle cut sketch → Through cut (five holes + R12 side relief)"


def require(value, message):
    if not value:
        raise RuntimeError(message)
    return value


def report(stage, **data):
    print(json.dumps({"stage": stage, **data}, ensure_ascii=False), flush=True)


def constraint(obj, kind, partners=(), index=None, partner_index=None, name=None, value=None):
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
    require(item.Create() and item.IsValid(), f"Constraint {kind}: {name}")
    return item


def driver(dim, name, value):
    constraint(dim, c.ksCFixedDim)
    constraint(dim, c.ksCDimWithVariable, name=name, value=value)
    return dim


def dim_linear(symbols, p, q, text, orientation, partners, name, value):
    dim = require(symbols.GetLineDimensions().Add(), "Linear dimension")
    dim.SetX1(p[0]); dim.SetY1(p[1])
    dim.SetX2(q[0]); dim.SetY2(q[1])
    dim.SetX3(text[0]); dim.SetY3(text[1])
    dim.SetOrientation(orientation)
    require(dim.Update(), "Linear dimension update")
    require(dim.Associate(), f"Associate dimension {name}")
    associations = dim.GetConstraints()
    for i, (partner, pi) in enumerate(partners):
        require(any(a.IsValid() and a.GetConstraintType() == c.ksCMergePoints
                    and a.GetIndex() == i and a.GetPartnerIndex() == pi
                    and any(o.GetId() == partner.GetId() for o in a.GetPartners())
                    for a in associations), f"Dimension witness {name}/{i}")
    return driver(dim, name, value)


def dim_radius(symbols, obj, x, y, radius, name, angle=35.):
    dim = require(symbols.GetRadialDimensions().Add(), "Radial dimension")
    dim.SetBaseObject(obj)
    dim.SetXc(x); dim.SetYc(y)
    dim.SetRadius(radius)
    dim.SetAngle(angle)
    require(dim.Update(), "Radial dimension update")
    require(any(a.IsValid() and a.GetConstraintType() == c.ksCAssociation
                for a in dim.GetConstraints()), "Radial association")
    return driver(dim, name, radius)


@contextmanager
def edit(part, model, name):
    sketch = require(model.GetSketchs().Add(), "Sketch")
    sketch.SetName(name)
    sketch.SetPlane(require(part.GetDefaultObject(c3d.o3d_planeXOY), "XOY"))
    require(sketch.Update(), "Sketch plane")
    fragment = require(sketch.BeginEdit(False), "BeginEdit")
    try:
        fragment.SetParametricMode(True)
        require(fragment.IsParametricMode(), "Parametric sketch")
        view = require(fragment.GetViewsAndLayersManager().GetViews().GetActiveView(), "View")
        yield sketch, ksapi.IDrawingContainer(view), ksapi.ISymbols2DContainer(view)
    finally:
        require(sketch.EndEdit(), "EndEdit")
    state = sketch.GetConstraintsState()
    report("sketch", name=name, constraint_state=state)
    require(state == c.ksStateWellConstrained, f"Not fully defined: {name}: {state}")


def line(drawing, p, q):
    obj = require(drawing.GetLineSegments().Add(), "Line")
    obj.SetX1(p[0]); obj.SetY1(p[1])
    obj.SetX2(q[0]); obj.SetY2(q[1])
    require(obj.Update(), "Line update")
    return obj


def circle(drawing, x, y, radius):
    obj = require(drawing.GetCircles().Add(), "Circle")
    obj.SetXc(x); obj.SetYc(y); obj.SetRadius(radius)
    require(obj.Update(), "Circle update")
    return obj


def extrusion(model, sketch, name, cut=False):
    op = require(model.GetExtrusions().Add(c3d.o3d_cutExtrusion if cut else c3d.o3d_bossExtrusion), "Extrusion")
    op.SetName(name)
    op.SetProfiles([sketch])
    op.SetDirection(c3d.dtReverse if cut else c3d.dtNormal)
    require(op.SetSideParameters(not cut, c3d.etBlind, 2., 0., False, None), "Depth 2 mm")
    require(op.Update(), f"Build: {name}")
    return op


def align(a, b, vertical=False):
    constraint(a, c.ksCVAlignPoints if vertical else c.ksCHAlignPoints,
               partners=[b], index=0, partner_index=0)


def build(part, model):
    # Origin is at the centre of the large hole on the front sketch plane.
    # Drawing: W26 H28 t2; main hole x17 from left, midway vertically.
    with edit(part, model, "Plate 26 × 28 — origin at Ø7 centre") as (plate, drawing, symbols):
        p = require(drawing.GetPoints().Add(), "Origin point")
        p.SetX(0.); p.SetY(0.)
        require(p.Update(), "Origin point update")
        constraint(p, c.ksCFixedPoint, index=0)
        vertices = [(-17., -14.), (9., -14.), (9., 14.), (-17., 14.)]
        lines = [line(drawing, a, b) for a, b in zip(vertices, vertices[1:] + vertices[:1])]
        for i, edge in enumerate(lines):
            constraint(edge, c.ksCMergePoints, partners=[lines[(i + 1) % 4]], index=1, partner_index=0)
            constraint(edge, c.ksCHorizontal if i % 2 == 0 else c.ksCVertical)
        dim_linear(symbols, vertices[0], vertices[1], (-4, -20), c.ksLinDHorizontal,
                   [(lines[0], 0), (lines[0], 1)], "plate_width", 26.)
        dim_linear(symbols, vertices[1], vertices[2], (15, 0), c.ksLinDVertical,
                   [(lines[1], 0), (lines[1], 1)], "plate_height", 28.)
        dim_linear(symbols, vertices[0], (0, 0), (-8, -25), c.ksLinDHorizontal,
                   [(lines[0], 0), (p, 0)], "origin_from_left", 17.)
        dim_linear(symbols, vertices[0], (0, 0), (-24, -7), c.ksLinDVertical,
                   [(lines[0], 0), (p, 0)], "origin_from_bottom", 14.)
    extrusion(model, plate, "Plate thickness 2 mm")

    # The 3 mm dimension is between the rightmost Ø7 point and the
    # leftmost R12 relief point, NOT the relief depth or centre distance.
    with edit(part, model, "Ø7 + 4 × Ø3 and R12 relief — gap 3 mm") as (cuts, drawing, symbols):
        main = circle(drawing, 0., 0., 3.5)
        constraint(main, c.ksCFixedPoint, index=0)
        dim_radius(symbols, main, 0., 0., 3.5, "central_radius")
        ul = circle(drawing, -12., 9., 1.5)
        ur = circle(drawing, 0., 9., 1.5)
        ll = circle(drawing, -12., -9., 1.5)
        lr = circle(drawing, 0., -9., 1.5)
        dim_radius(symbols, ul, -12., 9., 1.5, "mount_radius")
        for obj in (ur, ll, lr):
            constraint(obj, c.ksCEqualRadius, partners=[ul])
        dim_linear(symbols, (-12, 9), (0, 0), (-6, 18), c.ksLinDHorizontal,
                   [(ul, 0), (main, 0)], "column_spacing", 12.)
        dim_linear(symbols, (0, 0), (-12, 9), (-21, 5), c.ksLinDVertical,
                   [(main, 0), (ul, 0)], "upper_row", 9.)
        dim_linear(symbols, (-12, -9), (0, 0), (-26, -5), c.ksLinDVertical,
                   [(ll, 0), (main, 0)], "lower_row", 9.)
        align(ur, main, vertical=True)
        align(ur, ul)
        align(ll, ul, vertical=True)
        align(lr, main, vertical=True)
        align(lr, ll)
        notch = circle(drawing, 18.5, 0., 12.)
        dim_radius(symbols, notch, 18.5, 0., 12., "relief_radius", 20.)
        align(notch, main)
        dim_linear(symbols, (0, 0), (18.5, 0), (9, 24), c.ksLinDHorizontal,
                   [(main, 0), (notch, 0)], "relief_centre", 18.5)
    # Store native, editable formulae; initial geometry already satisfies them.
    feature = require(ksapi.IFeature(cuts), "Cut sketch feature")
    expressions = {"relief_centre": "central_radius+relief_radius+3",
                   "lower_row": "upper_row", "column_spacing": "17-5", "upper_row": "14-5"}
    for name, expression in expressions.items():
        variable = require(feature.GetVariableByName(False, True, name), f"Variable {name}")
        require(not variable.IsInformation() and not variable.IsReadOnly(), f"Driving variable {name}")
        variable.SetExpression(expression)
        require(variable.GetExpression().replace(" ", "") == expression, f"Expression {name}")
    extrusion(model, cuts, "Through holes and circular side relief", cut=True)
    return [plate, cuts]


def feature_errors(part):
    errors, seen = [], set()
    def visit(item):
        if item.reference in seen:
            return
        seen.add(item.reference)
        if item.GetObjectError():
            errors.append(f"{item.GetName()}: {item.GetObjectError()}")
        for child in item.GetSubFeatures(c.ksOperTree, True, True):
            if child:
                visit(child)
    visit(require(ksapi.IFeature(part), "Part feature"))
    return errors


def main():
    result = {"task": "2.9", "status": "failed", "title": TITLE, "script": "solution.py",
              "model": None, "volume_mm3": None, "reference_volume": 1273,
              "reference_units": "mm3", "volume_passed": False, "checks": [],
              "limitations": [], "tree": TREE}
    doc = None
    try:
        attempt = Path(tempfile.mkdtemp(prefix="attempt-", dir=ROOT))
        target = attempt / "model.m3d"
        require(not target.exists() and not target.is_symlink(), "New model path")
        app = ksapi.GetKompas()
        if not app:
            result["status"] = "blocked"
            raise RuntimeError("No existing KOMPAS API session; application was not launched")
        doc = require(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart, True), "Own new document")
        doc3d = require(ksapi.IKompasDocument3D(doc), "3D document")
        part = require(doc3d.GetTopPart(), "Top part")
        part.SetName(TITLE)
        sketches = build(part, require(part.GetModelContainer(), "Model container"))
        require(doc3d.CompleteRebuildDocument(), "Complete rebuild")
        require(part.RebuildModel(True), "Rebuild model")
        for sketch in sketches:
            state = sketch.GetConstraintsState()
            require(state == c.ksStateWellConstrained, f"Final sketch state: {state}")
        result["checks"].append("Both native sketches fully defined (ksStateWellConstrained=1), using coincidences, horizontal/vertical alignment, equal radii and driving dimensions; only origin point/centre anchored.")
        errors = feature_errors(part)
        require(not errors, f"Feature errors: {errors}")
        result["checks"].append("Native feature tree rebuilt with no operation errors.")
        bodies = ksapi.IFeature(part).GetResultBodies()
        require(len(bodies) == 1 and bodies[0].IsSolid(), "Single solid body")
        result["checks"].append("Exactly one solid body.")
        mass = require(ksapi.IMassInertiaParam(part), "Mass inertia")
        mass.SetLengthUnits(c.ksLUnMM)
        units = mass.GetLengthUnits()
        require(units == 1, f"Mass length unit readback: {units}")
        require(mass.Calculate(), "Mass calculation")
        require(mass.GetLengthUnits() == 1, "Mass units remain mm")
        volume = mass.GetVolume()
        require(math.isfinite(volume) and volume > 0, "Positive finite native volume")
        result["volume_mm3"] = volume
        result["volume_passed"] = 1272.5 <= volume < 1273.5
        result["checks"].append("IMassInertiaParam.SetLengthUnits(ksLUnMM); GetLengthUnits=1 before and after Calculate.")
        result["checks"].append(f"Native volume {volume:.12f} mm3; rounded-reference interval [1272.5,1273.5): {result['volume_passed']}.")
        require(not target.exists() and not target.is_symlink(), "SaveAs path must not exist")
        require(doc.SaveAs(str(target)), "SaveAs")
        require(target.is_file() and target.stat().st_size > 0, "Saved nonempty model")
        result["model"] = str(target.relative_to(ROOT))
        result["checks"].append("SaveAs succeeded into a new attempt directory; nonempty native .m3d exists.")
        result["status"] = "passed" if result["volume_passed"] else "partial"
        if not result["volume_passed"]:
            result["limitations"].append("Drawing dimensions yield about 1272.48758 mm3, 0.01242 mm3 below the required lower rounding bound 1272.5; geometry was not adjusted to fit the reference.")
        result["limitations"].append("Vertical centring of the Ø7 hole/relief and symmetric lower mounting row follow the drawing symmetry; no separate dimensions are provided for them.")
        result["limitations"].append("Dimension-change tests and save/reopen were not performed, as requested. No preview, raster or export was generated.")
    except Exception as exc:
        result["limitations"].append(f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
    finally:
        if doc is not None:
            try:
                require(doc.Close(c.kdDoNotSaveChanges), "Close own document")
                result["checks"].append("Own document closed in finally; no foreign document was modified or closed.")
            except Exception as exc:
                result["status"] = "partial" if result["model"] else "failed"
                result["limitations"].append(f"Closing own document: {exc}")
        (ROOT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report("result", **result)
    return 0 if result["status"] in ("passed", "partial") else 1


if __name__ == "__main__":
    raise SystemExit(main())
