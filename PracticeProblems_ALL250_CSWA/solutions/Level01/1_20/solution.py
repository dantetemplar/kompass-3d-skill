# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Practice Problem 1.20: native dimension-driven KOMPAS-3D model.

Origin: centre of the underside of the annular plate. Four identical rectangular
bars have inner sides tangent to R16 and outer corners on R55. No imported solids,
fixed contour geometry, previews, dimension perturbations, or reopen tests.
"""
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
TITLE = "Practice Problem 1.20 — кольцевая пластина с четырьмя стержнями"
TREE = "Кольцо Ø110/Ø32 × 10 → верхняя плоскость +10 → два касательных стержня 12×20 → два поперечных нижних стержня 12×20"


def require(value, message):
    if not value:
        raise RuntimeError(message)
    return value


def stage(message, **data):
    print(json.dumps({"stage": message, **data}, ensure_ascii=False), flush=True)


def relation(obj, kind, *, partners=(), index=None, partner_index=None,
             name=None, value=None, expression=None):
    con = require(obj.NewConstraint(), "NewConstraint")
    con.SetConstraintType(kind)
    if partners:
        con.SetPartners(list(partners))
    if index is not None:
        con.SetIndex(index)
    if partner_index is not None:
        con.SetPartnerIndex(partner_index)
    if name is not None:
        con.SetVariable(name)
    if value is not None:
        con.SetConstraintValue(value)
    if expression is not None:
        con.SetExpression(expression)
    require(con.Create(), f"Create constraint {kind}, {name}")
    require(con.IsValid(), f"Invalid constraint {kind}, {name}")
    return con


def driving(dim, name, value, expression):
    relation(dim, c.ksCFixedDim)
    relation(dim, c.ksCDimWithVariable, name=name, value=value, expression=expression)


def circle(drawing, radius, construction=False):
    obj = require(drawing.GetCircles().Add(), "Circle")
    obj.SetXc(0.0)
    obj.SetYc(0.0)
    obj.SetRadius(radius)
    if construction:
        obj.SetStyle(7)
    require(obj.Update(), "Circle update")
    return obj


def radial(symbols, obj, radius, name, expression):
    dim = require(symbols.GetRadialDimensions().Add(), "Radial dimension")
    dim.SetBaseObject(obj)
    dim.SetXc(0.0)
    dim.SetYc(0.0)
    dim.SetRadius(radius)
    dim.SetAngle(35.0)
    require(dim.Update(), "Radial dimension update")
    require(any(x.IsValid() and x.GetConstraintType() == c.ksCAssociation
                for x in dim.GetConstraints()), "Radial association")
    driving(dim, name, radius, expression)


def width_dimension(symbols, line, p, q, horizontal, name):
    dim = require(symbols.GetLineDimensions().Add(), "Bar width dimension")
    dim.SetX1(p[0])
    dim.SetY1(p[1])
    dim.SetX2(q[0])
    dim.SetY2(q[1])
    dim.SetX3((p[0] + q[0]) / 2 + (0 if horizontal else 7))
    dim.SetY3((p[1] + q[1]) / 2 - (7 if horizontal else 0))
    dim.SetOrientation(c.ksLinDHorizontal if horizontal else c.ksLinDVertical)
    require(dim.Update(), "Width dimension update")
    require(dim.Associate(), "Width dimension associate")
    for index in (0, 1):
        require(any(x.IsValid() and x.GetConstraintType() == c.ksCMergePoints
                    and x.GetIndex() == index and x.GetPartnerIndex() == index
                    and any(p.GetId() == line.GetId() for p in x.GetPartners())
                    for x in dim.GetConstraints()), "Width witness association")
    driving(dim, name, 12.0, "bar_width")


@contextmanager
def sketch_edit(part, model, plane, name, checks):
    sketch = require(model.GetSketchs().Add(), "Add sketch")
    sketch.SetName(name)
    sketch.SetPlane(plane)
    require(sketch.Update(), "Sketch support update")
    fragment = require(sketch.BeginEdit(False), "BeginEdit")
    try:
        fragment.SetParametricMode(True)
        require(fragment.IsParametricMode(), "Parametric mode")
        view = require(fragment.GetViewsAndLayersManager().GetViews().GetActiveView(), "Sketch view")
        yield sketch, ksapi.IDrawingContainer(view), ksapi.ISymbols2DContainer(view)
    finally:
        require(sketch.EndEdit(), "EndEdit")
    state = sketch.GetConstraintsState()
    stage("sketch-closed", name=name, constraints_state=state)
    require(state == c.ksStateWellConstrained, f"Sketch not fully defined: {name}, state={state}")
    checks.append(f"Эскиз «{name}»: GetConstraintsState={state}, полностью определён нативными связями и управляющими размерами; фиксирован только центр базовой окружности.")


def circle_network(drawing, symbols, prefix, construction):
    outer = circle(drawing, 55.0, construction)
    inner = circle(drawing, 16.0, construction)
    relation(outer, c.ksCFixedPoint, index=0)
    relation(inner, c.ksCConcentricity, partners=[outer])
    radial(symbols, outer, 55.0, prefix + "_outer", "outer_radius")
    radial(symbols, inner, 16.0, prefix + "_inner", "inner_radius")
    return outer, inner


def rectangle(drawing, points, rotated):
    lines = []
    for p, q in zip(points, points[1:] + points[:1]):
        obj = require(drawing.GetLineSegments().Add(), "Bar segment")
        obj.SetX1(p[0])
        obj.SetY1(p[1])
        obj.SetX2(q[0])
        obj.SetY2(q[1])
        require(obj.Update(), "Bar segment update")
        lines.append(obj)
    for i, line in enumerate(lines):
        relation(line, c.ksCMergePoints, partners=[lines[(i + 1) % 4]], index=1, partner_index=0)
        horizontal = (i % 2 == 0) != rotated
        relation(line, c.ksCHorizontal if horizontal else c.ksCVertical)
    return lines


def bars(part, model, plane, name, rotated, checks):
    half = math.sqrt(55.0**2 - (16.0 + 12.0)**2)
    with sketch_edit(part, model, plane, name, checks) as (sketch, drawing, symbols):
        outer, inner = circle_network(drawing, symbols, "lower" if rotated else "upper", True)
        first = None
        for sign in (1, -1):
            points = [(sign * 16.0, -half), (sign * 28.0, -half),
                      (sign * 28.0, half), (sign * 16.0, half)]
            if rotated:
                points = [(-y, x) for x, y in points]
            lines = rectangle(drawing, points, rotated)
            relation(lines[3], c.ksCTangentTwoCurves, partners=[inner])
            # Both corners of the outer long side terminate exactly on Ø110.
            relation(lines[1], c.ksCPointOnCurve, partners=[outer], index=0)
            relation(lines[1], c.ksCPointOnCurve, partners=[outer], index=1)
            if first is None:
                width_dimension(symbols, lines[0], points[0], points[1], not rotated,
                                "lower_width" if rotated else "upper_width")
                first = lines
            else:
                relation(lines[0], c.ksCEqualLength, partners=[first[0]])
    return sketch


def extrude(model, sketch, depth, name, reverse=False):
    operation = require(model.GetExtrusions().Add(c3d.o3d_bossExtrusion), "Add native boss")
    operation.SetName(name)
    operation.SetProfiles([sketch])
    operation.SetDirection(c3d.dtReverse if reverse else c3d.dtNormal)
    require(operation.SetSideParameters(not reverse, c3d.etBlind, depth, 0.0, False, None), "Boss depth")
    require(operation.Update(), f"Boss update: {name}")
    stage("extrusion-built", name=name)
    return operation


def feature_errors(part):
    errors, seen = [], set()
    def visit(feature):
        if feature.reference in seen:
            return
        seen.add(feature.reference)
        error = feature.GetObjectError()
        if error:
            errors.append(f"{feature.GetName()}: {error}")
        for child in feature.GetSubFeatures(c.ksOperTree, True, True):
            if child:
                visit(child)
    visit(ksapi.IFeature(part))
    return errors


def main():
    result = {"task": "1.20", "status": "failed", "title": TITLE,
              "script": "solution.py", "model": None, "volume_mm3": None,
              "reference_volume": 177882, "reference_units": "mm3",
              "volume_passed": False, "checks": [], "limitations": [], "tree": TREE}
    checks = result["checks"]
    attempt = Path(tempfile.mkdtemp(prefix="attempt-", dir=ROOT))
    output = attempt / "model.m3d"
    require(not output.exists() and not output.is_symlink(), "Output already exists")
    doc = None
    try:
        app = require(ksapi.GetKompas(), "Нет действующей API-сессии КОМПАС; приложение не запускалось")
        doc = require(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart, True), "Own new part")
        part = require(ksapi.IKompasDocument3D(doc).GetTopPart(), "Top part")
        part.SetName(TITLE)
        model = require(part.GetModelContainer(), "Native model container")
        for name, value, note in [("outer_radius", 55.0, "Наружный радиус Ø110/2"),
                                  ("inner_radius", 16.0, "Центральное отверстие Ø32/2"),
                                  ("bar_width", 12.0, "Общая ширина всех стержней")]:
            require(part.AddVariable(name, value, note), f"Shared variable: {name}")
        xoy = require(part.GetDefaultObject(c3d.o3d_planeXOY), "XOY at red origin")
        with sketch_edit(part, model, xoy, "Основание Ø110 и отверстие Ø32", checks) as (base, drawing, symbols):
            circle_network(drawing, symbols, "base", False)
        extrude(model, base, 10.0, "Кольцевая пластина, 10 мм")
        plane = require(ksapi.IAuxiliaryGeomContainer(part).GetPlanes3D().Add(c3d.o3d_planeOffset), "Top plane")
        plane.SetName("Верх основания, Z=10 мм")
        offset = ksapi.IPlane3DByOffset(plane)
        offset.SetBasePlane(xoy)
        offset.SetOffset(10.0)
        offset.SetDirection(True)
        require(offset.Update(), "Top plane offset")
        upper = bars(part, model, plane, "Верхние стержни: касание Ø32, углы на Ø110", False, checks)
        extrude(model, upper, 20.0, "Два верхних стержня, 20 мм")
        lower = bars(part, model, xoy, "Нижние поперечные стержни: касание Ø32, углы на Ø110", True, checks)
        extrude(model, lower, 20.0, "Два нижних стержня, 20 мм", reverse=True)
        require(part.RebuildModel(True), "Final rebuild")
        errors = feature_errors(part)
        require(not errors, f"Operation errors: {errors}")
        checks.append("Итоговое перестроение успешно; ошибок во всём нативном дереве операций нет.")
        bodies = ksapi.IFeature(part).GetResultBodies()
        require(len(bodies) == 1 and bodies[0].IsSolid(), "Expected one solid")
        checks.append("Получено одно твёрдое тело; все четыре стержня объединены с кольцевым основанием.")
        mass = require(ksapi.IMassInertiaParam(part), "Mass interface")
        mass.SetLengthUnits(c.ksLUnMM)
        require(mass.GetLengthUnits() == 1, "Mass length unit readback must be 1 (mm)")
        require(mass.Calculate(), "Mass calculation")
        require(mass.GetLengthUnits() == 1, "Mass units changed")
        volume = mass.GetVolume()
        require(math.isfinite(volume) and volume > 0, "Invalid native volume")
        result["volume_mm3"] = volume
        result["volume_passed"] = 177881.5 <= volume < 177882.5
        checks.append(f"IMassInertiaParam: SetLengthUnits(ksLUnMM), GetLengthUnits=1; объём {volume:.9f} мм³.")
        checks.append(f"Сравнение с интервалом [177881.5,177882.5): {result['volume_passed']}.")
        require(not output.exists() and not output.is_symlink(), "Refusing overwrite")
        require(doc.SaveAs(str(output)), "SaveAs new model path")
        require(output.is_file() and output.stat().st_size > 0, "Saved native model missing")
        require(Path(doc.GetFullPath()).resolve() == output.resolve(), "Saved document path mismatch")
        result["model"] = str(output.relative_to(ROOT))
        checks.append("SaveAs в новый отсутствовавший attempt-*/model.m3d успешен; файл непустой, GetFullPath совпадает.")
        result["status"] = "passed" if result["volume_passed"] else "partial"
        if not result["volume_passed"]:
            result["limitations"].append("Нативный объём вне интервала округления эталона; геометрия под объём не подгонялась.")
    except Exception as exc:
        result["limitations"].append(f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
    finally:
        if doc is not None:
            try:
                require(doc.Close(c.kdDoNotSaveChanges), "Close own document")
                checks.append("Собственный документ закрыт в finally; чужие документы не изменялись.")
            except Exception as exc:
                result["limitations"].append(f"Закрытие собственного документа: {exc}")
                result["status"] = "partial" if result["model"] else "failed"
        (ROOT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        stage("result", **result)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
