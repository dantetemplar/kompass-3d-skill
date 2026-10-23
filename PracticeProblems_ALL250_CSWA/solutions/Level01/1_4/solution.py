# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Practice Problem 1.4: standalone native Linux KOMPAS model, all lengths mm."""
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
U = 25.4
TREE = "Плоскость Z=11.43 → эллипс 40.64×12.7 с 2×Ø3.175 → фланец 3.81 → окружность Ø11.43 → ступица 11.43 → шестигранник S6.35 → гнездо 7.62"


def need(value, message):
    if not value:
        raise RuntimeError(message)
    return value


def event(stage, **values):
    print(json.dumps({"stage": stage, **values}, ensure_ascii=False), flush=True)


def link(obj, kind, partner=None, index=None, partner_index=None, name=None, value=None):
    item = need(obj.NewConstraint(), "NewConstraint")
    item.SetConstraintType(kind)
    if partner is not None:
        item.SetPartners([partner])
    if index is not None:
        item.SetIndex(index)
    if partner_index is not None:
        item.SetPartnerIndex(partner_index)
    if name is not None:
        item.SetVariable(name)
    if value is not None:
        item.SetConstraintValue(value)
    need(item.Create() and item.IsValid(), f"Constraint {kind}, {name}")
    return item


def drive(dim, name, value):
    link(dim, c.ksCFixedDim)
    link(dim, c.ksCDimWithVariable, name=name, value=value)
    return dim


def linear(symbols, p1, p2, location, orientation, obj1, idx1, obj2, idx2, name, value):
    dim = need(symbols.GetLineDimensions().Add(), "Linear dimension")
    dim.SetX1(p1[0]); dim.SetY1(p1[1])
    dim.SetX2(p2[0]); dim.SetY2(p2[1])
    dim.SetX3(location[0]); dim.SetY3(location[1])
    dim.SetOrientation(orientation)
    need(dim.Update(), "Dimension Update")
    need(dim.Associate(), f"Dimension association: {name}")
    return drive(dim, name, value)


def radius(symbols, circle, value, name):
    dim = need(symbols.GetRadialDimensions().Add(), "Radial dimension")
    dim.SetBaseObject(circle)
    dim.SetXc(circle.GetXc()); dim.SetYc(circle.GetYc())
    dim.SetRadius(value); dim.SetAngle(35.0)  # degrees
    need(dim.Update(), "Radial dimension Update")
    need(any(x.IsValid() and x.GetConstraintType() == c.ksCAssociation for x in dim.GetConstraints()), "Radial association")
    return drive(dim, name, value)


def circle(drawing, x, y, r, auxiliary=False):
    obj = need(drawing.GetCircles().Add(), "Circle")
    obj.SetXc(x); obj.SetYc(y); obj.SetRadius(r)
    if auxiliary:
        obj.SetStyle(7)  # KOMPAS auxiliary line, excluded from extrusion profile.
    need(obj.Update(), "Circle Update")
    return obj


def point(drawing):
    obj = need(drawing.GetPoints().Add(), "Origin point")
    obj.SetX(0.0); obj.SetY(0.0)
    need(obj.Update(), "Origin Update")
    link(obj, c.ksCFixedPoint, index=0)
    return obj


@contextmanager
def sketch(model, plane, name, states):
    obj = need(model.GetSketchs().Add(), "Sketch")
    obj.SetName(name); obj.SetPlane(plane)
    need(obj.Update(), "Sketch Update")
    fragment = need(obj.BeginEdit(False), "BeginEdit")
    try:
        fragment.SetParametricMode(True)
        need(fragment.IsParametricMode(), "Parametric mode")
        view = need(fragment.GetViewsAndLayersManager().GetViews().GetActiveView(), "Sketch view")
        yield obj, ksapi.IDrawingContainer(view), ksapi.ISymbols2DContainer(view)
    finally:
        need(obj.EndEdit(), "EndEdit")
    state = obj.GetConstraintsState()
    states.append((name, state))
    event("sketch", name=name, constraints_state=state)


def extrude(model, profile, depth, name, cut=False):
    operation = need(model.GetExtrusions().Add(c3d.o3d_cutExtrusion if cut else c3d.o3d_bossExtrusion), "Extrusion")
    operation.SetName(name); operation.SetProfiles([profile])
    operation.SetDirection(c3d.dtReverse if cut else c3d.dtNormal)
    need(operation.SetSideParameters(not cut, c3d.etBlind, depth, 0.0, False, None), "Extrusion depth")
    need(operation.Update(), f"Operation Update: {name}")
    event("operation", name=name)
    return operation


def build(part, model, states):
    xoy = need(part.GetDefaultObject(c3d.o3d_planeXOY), "XOY")
    plane = need(ksapi.IAuxiliaryGeomContainer(part).GetPlanes3D().Add(c3d.o3d_planeOffset), "Offset plane")
    plane.SetName("Низ фланца: 0.45 in")
    offset = ksapi.IPlane3DByOffset(plane)
    offset.SetBasePlane(xoy); offset.SetOffset(.45 * U); offset.SetDirection(True)
    need(offset.Update(), "Offset Update")
    with sketch(model, plane, "Фланец и крепёж: 1.6 × 0.5 in, 2 × Ø0.125 in", states) as (flange, drawing, symbols):
        origin = point(drawing)
        ellipse = need(drawing.GetEllipses().Add(), "Ellipse")
        ellipse.SetXc(0.0); ellipse.SetYc(0.0)
        ellipse.SetSemiAxisA(.8 * U); ellipse.SetSemiAxisB(.25 * U)
        ellipse.SetAngle(0.0)  # IEllipse.SetAngle uses degrees per SDK.
        need(ellipse.Update(), "Ellipse Update")
        link(ellipse, c.ksCConcentricity, origin)
        # Linux solver rejected horizontal/aligned/fixed-angle constraints on IEllipse.
        # Preserve the native exact ellipse, report this parameterization limit honestly.
        holes = []
        for sign, name in [(-1, "left"), (1, "right")]:
            x = sign * (.8-.175) * U
            hole = circle(drawing, x, 0, .125/2*U)
            link(hole, c.ksCHAlignPoints, origin, 0, 0)
            linear(symbols, (0, 0), (x, 0), (x/2, 10), c.ksLinDHorizontal, origin, 0, hole, 0, f"hole_{name}_offset", abs(x))
            holes.append(hole)
        radius(symbols, holes[0], .125/2*U, "mount_hole_radius")
        link(holes[1], c.ksCEqualRadius, holes[0])
    extrude(model, flange, .15*U, "Фланец: 0.15 in; два сквозных отверстия")
    with sketch(model, xoy, "Ступица: Ø0.45 in", states) as (hub, drawing, symbols):
        outer = circle(drawing, 0, 0, .45/2*U)
        link(outer, c.ksCFixedPoint, index=0)
        radius(symbols, outer, .45/2*U, "hub_radius")
    extrude(model, hub, .45*U, "Соосная ступица: 0.45 in")
    with sketch(model, xoy, "Правильный шестигранник S=0.25 in", states) as (hexagon, drawing, symbols):
        # Regularity is a native constraint network, not six fixed vertices.
        h = .25/2*U
        r = 2*h/math.sqrt(3)
        guide = circle(drawing, 0, 0, r, auxiliary=True)
        link(guide, c.ksCFixedPoint, index=0)
        vertices = [(r, 0), (r/2, h), (-r/2, h), (-r, 0), (-r/2, -h), (r/2, -h)]
        lines = []
        for a, b in zip(vertices, vertices[1:]+vertices[:1]):
            line = need(drawing.GetLineSegments().Add(), "Hexagon segment")
            line.SetX1(a[0]); line.SetY1(a[1]); line.SetX2(b[0]); line.SetY2(b[1])
            need(line.Update(), "Hexagon segment Update")
            lines.append(line)
        for i, line in enumerate(lines):
            link(line, c.ksCMergePoints, lines[(i+1)%6], 1, 0)
            link(line, c.ksCPointOnCurve, guide, 0)
            if i:
                link(line, c.ksCEqualLength, lines[0])
        link(lines[1], c.ksCHorizontal)
        linear(symbols, vertices[4], vertices[1], (9, 0), c.ksLinDVertical, lines[4], 0, lines[1], 0, "hex_across_flats", .25*U)
    extrude(model, hexagon, (.45-.15)*U, "Глухое шестигранное гнездо; дно 0.15 in", cut=True)


def inspect_tree(part):
    errors, seen = [], set()
    def visit(item):
        if item.reference in seen:
            return
        seen.add(item.reference)
        error = item.GetObjectError()
        if error:
            errors.append([item.GetName(), error])
        for child in item.GetSubFeatures(c.ksOperTree, True, True):
            if child:
                visit(child)
    feature = ksapi.IFeature(part)
    visit(feature)
    bodies = feature.GetResultBodies()
    need(len(bodies) == 1 and bodies[0].IsSolid(), "One native solid")
    return errors


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    attempt = Path(tempfile.mkdtemp(prefix="attempt-", dir=ROOT))
    output = attempt / "model.m3d"
    need(not output.exists(), "Output must be new")
    result = {"task": "1.4", "status": "failed", "title": "Фланцевая втулка с шестигранным гнездом", "script": "solution.py", "model": None, "volume_mm3": None, "reference_volume": .146, "reference_units": "in3", "volume_passed": None, "checks": [], "limitations": ["Наружный контур трактуется как эллипс 1.6 × 0.5 in: тип кривой отдельно не подписан на чертеже.", "Размер 0.25 in прочитан как расстояние между параллельными гранями правильного шестигранника; глубина гнезда 0.45−0.15=0.30 in.", "Межэскизные размеры и смещение отверстий от торцов не связаны выражениями: при изменении длины фланца отступ 0.175 in автоматически не сохраняется.", "Пробные изменения размеров и повторное открытие не выполнялись.", "У эллипса нативная соосность с началом, но полуоси и ориентация заданы его геометрическими свойствами: Linux API отклонил связи горизонтальности/выравнивания/фиксации угла. Полная размерная параметризация эллипса не достигнута."], "tree": TREE}
    doc = None
    api_unknown = False
    exit_code = 1
    states = []
    try:
        app = need(ksapi.GetKompas(), "Нет API-сессии; запуск запрещён")
        doc = need(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart, True), "Own new part")
        doc3d = ksapi.IKompasDocument3D(doc)
        part = need(doc3d.GetTopPart(), "Top part")
        part.SetName(result["title"])
        build(part, need(part.GetModelContainer(), "Model container"), states)
        need(doc3d.CompleteRebuildDocument(), "CompleteRebuildDocument")
        need(part.RebuildModel(True), "RebuildModel")
        errors = inspect_tree(part)
        result["checks"].append(f"Одно твёрдое тело; ошибки дерева: {errors}")
        result["checks"].append(f"Состояния ограничений эскизов после EndEdit: {states}; WellConstrained={c.ksStateWellConstrained}")
        if not all(state == c.ksStateWellConstrained for _, state in states):
            result["limitations"].append("Не все эскизы полностью определены; реальные состояния приведены в checks.")
        mass = need(ksapi.IMassInertiaParam(part), "Mass inertia interface")
        mass.SetLengthUnits(c.ksLUnMM)
        units = mass.GetLengthUnits()
        need(units == c.ksLUnMM, f"Length units readback: {units}")
        need(mass.Calculate(), "Mass inertia Calculate")
        volume = mass.GetVolume()
        need(math.isfinite(volume) and volume > 0, "CAD volume")
        result["volume_mm3"] = volume
        inch_volume = volume / U**3
        passed = .1455 <= inch_volume < .1465
        result["volume_passed"] = passed
        result["checks"].append(f"IMassInertiaParam.Calculate; GetLengthUnits={units}=ksLUnMM; V={volume:.12g} mm3 = {inch_volume:.12g} in3; интервал эталона [0.1455,0.1465): {passed}")
        need(not output.exists(), "SaveAs destination exists")
        need(doc.SaveAs(str(output)), "SaveAs")
        need(output.is_file() and output.stat().st_size > 0, "Nonempty native model")
        result["model"] = str(output.relative_to(ROOT))
        result["checks"].append("SaveAs успешно; сохранён непустой новый model.m3d, без экспорта.")
        result["status"] = "passed" if passed and not errors and all(s == c.ksStateWellConstrained for _, s in states) else "partial"
        exit_code = 0
    except Exception as exc:
        traceback.print_exc()
        text = f"{type(exc).__name__}: {exc}"
        api_unknown = any(s in text.lower() for s in ("connection", "broken pipe", "socket", "eof", "transport", "timeout", "timed out"))
        result["status"] = "blocked" if api_unknown else "failed"
        result["limitations"].append(text)
        if api_unknown:
            result["limitations"].append("Исход API неизвестен; новые обращения и закрытие документа остановлены.")
    finally:
        if doc is not None and not api_unknown:
            try:
                need(doc.Close(c.kdDoNotSaveChanges), "Close own document")
                result["checks"].append("Собственный документ закрыт в finally; чужие документы не изменялись и не закрывались.")
            except Exception as exc:
                result["limitations"].append(f"Закрытие собственного документа: {type(exc).__name__}: {exc}")
                result["status"] = "blocked"
                exit_code = 1
        text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        (attempt / "result.json").write_text(text)
        (ROOT / "result.json").write_text(text)
        event("result", **result)
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
