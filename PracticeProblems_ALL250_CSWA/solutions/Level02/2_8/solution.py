# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Practice Problem 2.8: native dimension-driven offset frame, millimetres."""
from __future__ import annotations

import json
import math
from pathlib import Path
import tempfile
import traceback

import ksapi
from constants import constants as c
from constants3d import constants as c3d

ROOT = Path(__file__).resolve().parent


def require(value, message):
    if not value:
        raise RuntimeError(message)
    return value


def event(stage, **data):
    print(json.dumps({"stage": stage, **data}, ensure_ascii=False), flush=True)


def relation(obj, kind, partners=(), index=None, partner_index=None, name=None, value=None):
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
    ok = item.Create()
    require(ok and item.IsValid(), f"Constraint type={kind}, variable={name}")
    return item


def dimension(symbols, a, b, label, orient, name, value):
    obj = require(symbols.GetLineDimensions().Add(), "Linear dimension")
    obj.SetX1(a[0]); obj.SetY1(a[1])
    obj.SetX2(b[0]); obj.SetY2(b[1])
    obj.SetX3(label[0]); obj.SetY3(label[1])
    obj.SetOrientation(orient)
    require(obj.Update(), f"Dimension Update {name}")
    require(obj.Associate(), f"Dimension Associate {name}")
    relation(obj, c.ksCFixedDim)
    relation(obj, c.ksCDimWithVariable, name=name, value=value)
    return obj


def line(drawing, a, b, auxiliary=False):
    obj = require(drawing.GetLineSegments().Add(), "Line")
    obj.SetX1(a[0]); obj.SetY1(a[1])
    obj.SetX2(b[0]); obj.SetY2(b[1])
    if auxiliary:
        obj.SetStyle(c.ksCSConstruction)
    require(obj.Update(), "Line Update")
    return obj


def blend(previous, vertex, following, radius):
    la, lb = math.dist(previous, vertex), math.dist(vertex, following)
    u = tuple((vertex[i] - previous[i]) / la for i in range(2))
    v = tuple((following[i] - vertex[i]) / lb for i in range(2))
    turn = math.atan2(u[0]*v[1] - u[1]*v[0], sum(u[i]*v[i] for i in range(2)))
    trim = radius * math.tan(turn / 2)
    a = tuple(vertex[i] - trim*u[i] for i in range(2))
    b = tuple(vertex[i] + trim*v[i] for i in range(2))
    center = (a[0] - radius*u[1], a[1] + radius*u[0])
    return a, b, center


def build(part, model, report):
    sketch = require(model.GetSketchs().Add(), "New sketch")
    sketch.SetName("Рамка: 150 × 250, верх 30, уступ 20; смещение 15; R6")
    sketch.SetPlane(require(part.GetDefaultObject(c3d.o3d_planeXOY), "XOY"))
    require(sketch.Update(), "Sketch plane")
    fragment = require(sketch.BeginEdit(False), "BeginEdit")
    try:
        fragment.SetParametricMode(True)
        require(fragment.IsParametricMode(), "Parametric mode")
        view = require(fragment.GetViewsAndLayersManager().GetViews().GetActiveView(), "View")
        drawing = require(ksapi.IDrawingContainer(view), "Drawing")
        symbols = require(ksapi.ISymbols2DContainer(view), "Dimensions")
        vertices = [(0.,0.), (150.,0.), (150.,20.), (30.,250.), (0.,250.)]
        outer = [line(drawing, a, b) for a, b in zip(vertices, vertices[1:]+vertices[:1])]
        for i, obj in enumerate(outer):
            relation(obj, c.ksCMergePoints, [outer[(i+1)%5]], 1, 0)
        for i, kind in [(0,c.ksCHorizontal), (1,c.ksCVertical), (3,c.ksCHorizontal), (4,c.ksCVertical)]:
            relation(outer[i], kind)
        # Only the origin is fixed; no complete entities or other vertices are frozen.
        relation(outer[0], c.ksCFixedPoint, index=0)
        dimension(symbols, vertices[0], vertices[1], (75,-15), c.ksLinDHorizontal, "width", 150.)
        dimension(symbols, vertices[0], vertices[4], (-20,125), c.ksLinDVertical, "height", 250.)
        dimension(symbols, vertices[4], vertices[3], (15,267), c.ksLinDHorizontal, "top_width", 30.)
        dimension(symbols, vertices[1], vertices[2], (170,10), c.ksLinDVertical, "heel_height", 20.)
        # 230*x + 120*y = 36900 is the outside diagonal. Offset inward by 15.
        norm = math.hypot(230.,120.)
        intercept = 36900. - 15.*norm
        hole = [(15.,15.), ((intercept-120.*15.)/230.,15.), (15.,(intercept-230.*15.)/120.)]
        corners = [blend(hole[i-1], hole[i], hole[(i+1)%3], 6.) for i in range(3)]
        arcs = []
        for a, b, center in corners:
            arc = require(drawing.GetArcs().Add(), "Fillet arc")
            arc.SetXc(center[0]); arc.SetYc(center[1]); arc.SetRadius(6.)
            arc.SetAngle1(math.degrees(math.atan2(a[1]-center[1],a[0]-center[0])) % 360)
            arc.SetAngle2(math.degrees(math.atan2(b[1]-center[1],b[0]-center[0])) % 360)
            arc.SetDirection(False)
            require(arc.Update(), "Arc Update")
            arcs.append(arc)
        inner = [line(drawing, corners[i][1], corners[(i+1)%3][0]) for i in range(3)]
        for i, obj in enumerate(inner):
            relation(obj, c.ksCMergePoints, [arcs[i]], 0, 2)
            relation(obj, c.ksCMergePoints, [arcs[(i+1)%3]], 1, 1)
            relation(obj, c.ksCTangentTwoCurves, [arcs[i]])
            relation(obj, c.ksCTangentTwoCurves, [arcs[(i+1)%3]])
        relation(inner[0], c.ksCHorizontal)
        relation(inner[2], c.ksCVertical)
        relation(inner[1], c.ksCParallel, [outer[2]])
        dimension(symbols, vertices[0], corners[2][1], (-10,60), c.ksLinDHorizontal, "left_offset", 15.)
        dimension(symbols, vertices[0], corners[0][1], (50,-7), c.ksLinDVertical, "bottom_offset", 15.)
        # A construction normal carries the actual perpendicular offset dimension.
        # Its first endpoint is tied to the outside-edge midpoint; its second lies
        # on the parallel inside edge. This is a native relation, not a Python-only offset.
        midpoint = (90.,135.)
        endpoint = (90.-15.*230./norm,135.-15.*120./norm)
        normal = line(drawing, midpoint, endpoint, auxiliary=True)
        relation(normal, c.ksCPointOnCurveMiddle, [outer[2]], index=0)
        relation(normal, c.ksCPointOnCurve, [inner[1]], index=1)
        relation(normal, c.ksCPerpendicular, [outer[2]])
        dimension(symbols, midpoint, endpoint, (100,120), c.ksLinDParallel, "diagonal_offset", 15.)
        radius = require(symbols.GetRadialDimensions().Add(), "Radius dimension")
        radius.SetBaseObject(arcs[0])
        radius.SetXc(corners[0][2][0]); radius.SetYc(corners[0][2][1])
        radius.SetRadius(6.); radius.SetAngle(225.)
        require(radius.Update(), "Radius dimension Update")
        relation(radius, c.ksCFixedDim)
        relation(radius, c.ksCDimWithVariable, name="inside_radius", value=6.)
        relation(arcs[1], c.ksCEqualRadius, [arcs[0]])
        relation(arcs[2], c.ksCEqualRadius, [arcs[0]])
    finally:
        require(sketch.EndEdit(), "EndEdit")
    state = sketch.GetConstraintsState()
    event("sketch", constraint_state=state)
    require(state == c.ksStateWellConstrained, f"Sketch constraints state={state}, expected 1")
    report["checks"].append("Эскиз полностью определён: GetConstraintsState=1; совпадения, H/V, касания, параллельность, равные R6 и управляющие размеры; фиксирована только точка начала.")
    extrusion = require(model.GetExtrusions().Add(c3d.o3d_bossExtrusion), "Extrusion")
    extrusion.SetName("Толщина 12 мм")
    extrusion.SetProfiles([sketch])
    extrusion.SetDirection(c3d.dtNormal)
    require(extrusion.SetSideParameters(True,c3d.etBlind,12.,0.,False,None), "Thickness")
    require(extrusion.Update(), "Extrusion Update")
    require(part.RebuildModel(True), "RebuildModel")
    report["checks"].append("Выдавливание 12 мм и RebuildModel выполнены успешно.")


def feature_errors(part):
    errors, seen = [], set()
    def visit(obj):
        if obj.reference in seen:
            return
        seen.add(obj.reference)
        if obj.GetObjectError():
            errors.append([obj.GetName(), obj.GetObjectError()])
        for child in obj.GetSubFeatures(c.ksOperTree, True, True):
            if child:
                visit(child)
    visit(require(ksapi.IFeature(part), "Part feature"))
    return errors


def main():
    report = dict(task="2.8", status="failed", title="SOLIDWORKS Practice Problem 2.8 — треугольная рамка", script="solution.py", model=None, volume_mm3=None, reference_volume=118440, reference_units="mm3", volume_passed=False, checks=[], limitations=[], tree="Эскиз: наружный пятиугольник + смещённый внутренний контур с тремя R6 → выдавливание 12 мм")
    app, doc = None, None
    target = Path(tempfile.mkdtemp(prefix="attempt-", dir=ROOT)) / "model.m3d"
    try:
        require(not target.exists() and not target.is_symlink(), "Output already exists")
        app = require(ksapi.GetKompas(), "Нет существующей API-сессии; КОМПАС не запускался")
        doc = require(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart, True), "Own part")
        part = require(ksapi.IKompasDocument3D(doc).GetTopPart(), "Top part")
        part.SetName("Practice Problem 2.8 — рамка")
        build(part, require(part.GetModelContainer(), "Model container"), report)
        bodies = ksapi.IFeature(part).GetResultBodies()
        require(len(bodies)==1 and bodies[0].IsSolid(), "Expected one solid")
        report["checks"].append("Получено одно твёрдое тело.")
        errors = feature_errors(part)
        require(not errors, f"Operation errors: {errors}")
        report["checks"].append("GetObjectError=0 во всём нативном дереве.")
        mass = require(ksapi.IMassInertiaParam(part), "Mass properties")
        mass.SetLengthUnits(c.ksLUnMM)
        units = mass.GetLengthUnits()
        require(units == 1, f"Length units={units}, expected 1")
        require(mass.Calculate() and mass.IsActual(), "Mass calculation")
        volume = mass.GetVolume()
        require(math.isfinite(volume) and volume > 0, "Invalid volume")
        report["volume_mm3"] = volume
        report["volume_passed"] = 118439.5 <= volume < 118440.5
        report["checks"].append(f"IMassInertiaParam: SetLengthUnits(ksLUnMM), GetLengthUnits={units}; Calculate и IsActual успешны; V={volume:.9f} мм³.")
        report["checks"].append(f"Сравнение с [118439.5, 118440.5): {report['volume_passed']}.")
        require(not target.exists() and not target.is_symlink(), "SaveAs target already exists")
        require(doc.SaveAs(str(target)), "SaveAs")
        require(target.is_file() and target.stat().st_size > 0, "Saved file missing")
        require(Path(doc.GetFullPath()).resolve() == target.resolve(), "Saved path mismatch")
        report["model"] = str(target.relative_to(ROOT))
        report["checks"].append("SaveAs в новый отсутствовавший путь успешен; .m3d существует и непуст; GetFullPath совпадает.")
        report["status"] = "passed" if report["volume_passed"] else "partial"
    except Exception as exc:
        report["limitations"].append(f"{type(exc).__name__}: {exc}")
        if app is None:
            report["status"] = "blocked"
        traceback.print_exc()
    finally:
        if doc is not None:
            try:
                require(doc.Close(c.kdDoNotSaveChanges), "Close owned document")
                report["checks"].append("Собственный документ закрыт в finally; чужие документы не изменялись.")
            except Exception as exc:
                report["status"] = "partial" if report["model"] else "failed"
                report["limitations"].append(f"Ошибка закрытия: {exc}")
        report["limitations"].append("По заданию не выполнялись изменение размеров, повторное открытие, превью и экспорт.")
        (ROOT / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        event("result", **report)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
