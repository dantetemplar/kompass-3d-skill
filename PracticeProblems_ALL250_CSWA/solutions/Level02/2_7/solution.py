# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""SOLIDWORKS Practice Problem 2.7, native KOMPAS-3D Linux.

Origin: right slot-end centre projected to the underside of the base.
X points toward the rounded nose; Z is vertical. All lengths are millimetres.
Tree: dimensioned base with slot -> 9 mm boss -> dimensioned pierced ear
on an offset XOZ plane -> 9 mm boss -> native two-instance linear pattern.
No import/export, rendering, reopen, or dimension-perturbation qualification.
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
REFERENCE = 56490
TREE = "Основание R20 и паз 14×23 → выдавливание 9; смещённая XOZ → проушина Ø35/Ø14, центр Z38 → выдавливание 9 → линейный массив 2, шаг 31 по Y"


def require(value, message):
    if not value:
        raise RuntimeError(message)
    return value


def stage(message, **values):
    print(json.dumps({"stage": message, **values}, ensure_ascii=False), flush=True)


def constraint(obj, kind, *, partner=None, index=None, partner_index=None,
               name=None, value=None):
    item = require(obj.NewConstraint(), "NewConstraint")
    item.SetConstraintType(kind)
    if index is not None:
        item.SetIndex(index)
    if partner_index is not None:
        item.SetPartnerIndex(partner_index)
    if partner is not None:
        item.SetPartners([partner])
    if name is not None:
        item.SetVariable(name)
    if value is not None:
        item.SetConstraintValue(value)
    require(item.Create() and item.IsValid(), f"Constraint failed {kind}, {name}")
    return item


def merge(first, fi, second, si):
    return constraint(first, c.ksCMergePoints, partner=second,
                      index=fi, partner_index=si)


def driving(dim, name, value):
    constraint(dim, c.ksCFixedDim)
    constraint(dim, c.ksCDimWithVariable, name=name, value=value)
    return dim


def linear(symbols, p1, p2, text, orientation, first, fi, second, si, name, value):
    dim = require(symbols.GetLineDimensions().Add(), "Line dimension")
    dim.SetX1(p1[0]); dim.SetY1(p1[1])
    dim.SetX2(p2[0]); dim.SetY2(p2[1])
    dim.SetX3(text[0]); dim.SetY3(text[1])
    dim.SetOrientation(orientation)
    require(dim.Update(), f"Dimension Update {name}")
    require(dim.Associate(), f"Dimension Associate {name}")
    for i, (obj, pi) in enumerate(((first, fi), (second, si))):
        require(any(link.IsValid() and link.GetConstraintType() == c.ksCMergePoints
                    and link.GetIndex() == i and link.GetPartnerIndex() == pi
                    and any(p.GetId() == obj.GetId() for p in link.GetPartners())
                    for link in dim.GetConstraints()), f"Witness association {name}/{i}")
    return driving(dim, name, value)


def radial(symbols, obj, centre, radius, name, angle=35):
    dim = require(symbols.GetRadialDimensions().Add(), "Radial dimension")
    dim.SetBaseObject(obj)
    dim.SetXc(centre[0]); dim.SetYc(centre[1])
    dim.SetRadius(radius)
    dim.SetAngle(angle)
    require(dim.Update(), f"Radial Update {name}")
    require(any(link.IsValid() and link.GetConstraintType() == c.ksCAssociation
                for link in dim.GetConstraints()), f"Radial association {name}")
    return driving(dim, name, radius)


def segment(drawing, start, end):
    obj = require(drawing.GetLineSegments().Add(), "Line segment")
    obj.SetX1(start[0]); obj.SetY1(start[1])
    obj.SetX2(end[0]); obj.SetY2(end[1])
    require(obj.Update(), "Line Update")
    return obj


def arc(drawing, centre, radius, first, last):
    obj = require(drawing.GetArcs().Add(), "Arc")
    obj.SetXc(centre[0]); obj.SetYc(centre[1])
    obj.SetRadius(radius)
    obj.SetAngle1(first); obj.SetAngle2(last)
    obj.SetDirection(False)
    require(obj.Update(), "Arc Update")
    return obj


def circle(drawing, centre, radius):
    obj = require(drawing.GetCircles().Add(), "Circle")
    obj.SetXc(centre[0]); obj.SetYc(centre[1])
    obj.SetRadius(radius)
    require(obj.Update(), "Circle Update")
    return obj


@contextmanager
def edit(sketch, checks):
    fragment = require(sketch.BeginEdit(False), "BeginEdit")
    try:
        fragment.SetParametricMode(True)
        require(fragment.IsParametricMode(), "Parametric mode")
        view = require(fragment.GetViewsAndLayersManager().GetViews().GetActiveView(), "View")
        yield require(ksapi.IDrawingContainer(view), "Drawing"), require(ksapi.ISymbols2DContainer(view), "Symbols")
    finally:
        require(sketch.EndEdit(), "EndEdit")
    state = sketch.GetConstraintsState()
    stage("sketch-state", name=sketch.GetName(), state=state)
    require(state == c.ksStateWellConstrained, f"Not fully constrained: {sketch.GetName()}={state}")
    checks.append(f"Эскиз «{sketch.GetName()}» полностью определён: state={state}; нативные связи и управляющие размеры, без фиксации всех объектов")


def new_sketch(model, plane, name):
    sk = require(model.GetSketchs().Add(), name)
    sk.SetName(name)
    sk.SetPlane(plane)
    require(sk.Update(), "Sketch support")
    return sk


def base_sketch(part, model, checks):
    sk = new_sketch(model, require(part.GetDefaultObject(c3d.o3d_planeXOY), "XOY"), "Основание R20, 86; паз 14×23")
    with edit(sk, checks) as (d, sy):
        bottom = segment(d, (-86, -20), (0, -20))
        nose = arc(d, (0, 0), 20, 270, 90)
        top = segment(d, (0, 20), (-86, 20))
        back = segment(d, (-86, 20), (-86, -20))
        merge(bottom, 1, nose, 1); merge(nose, 2, top, 0)
        merge(top, 1, back, 0); merge(back, 1, bottom, 0)
        constraint(bottom, c.ksCHorizontal)
        constraint(top, c.ksCHorizontal)
        constraint(back, c.ksCVertical)
        constraint(bottom, c.ksCTangentTwoCurves, partner=nose)
        constraint(top, c.ksCTangentTwoCurves, partner=nose)
        constraint(nose, c.ksCFixedPoint, index=0)
        radial(sy, nose, (0, 0), 20, "nose_R")
        linear(sy, (-86, -20), (0, -20), (-43, -29), c.ksLinDHorizontal,
               bottom, 0, bottom, 1, "base_straight", 86)
        # A capsule slot, driven by its radius and centre-to-centre length.
        sb = segment(d, (-23, -7), (0, -7))
        sr = arc(d, (0, 0), 7, 270, 90)
        st = segment(d, (0, 7), (-23, 7))
        sl = arc(d, (-23, 0), 7, 90, 270)
        merge(sb, 1, sr, 1); merge(sr, 2, st, 0)
        merge(st, 1, sl, 1); merge(sl, 2, sb, 0)
        constraint(sb, c.ksCHorizontal); constraint(st, c.ksCHorizontal)
        for line in (sb, st):
            for end in (sr, sl):
                constraint(line, c.ksCTangentTwoCurves, partner=end)
        constraint(sr, c.ksCFixedPoint, index=0)
        radial(sy, sr, (0, 0), 7, "slot_R")
        linear(sy, (-23, -7), (0, -7), (-12, -13), c.ksLinDHorizontal,
               sb, 0, sb, 1, "slot_centres", 23)
    return sk


def boss(model, sketch, depth, name, normal=True):
    stage("boss", name=name)
    op = require(model.GetExtrusions().Add(c3d.o3d_bossExtrusion), name)
    op.SetName(name)
    op.SetProfiles([sketch])
    op.SetDirection(c3d.dtNormal if normal else c3d.dtReverse)
    require(op.SetSideParameters(normal, c3d.etBlind, depth, 0, False, None), "Boss depth")
    require(op.Update(), name)
    return op


def ear_sketch(part, model, checks):
    aux = require(ksapi.IAuxiliaryGeomContainer(part), "Auxiliary geometry")
    plane = require(aux.GetPlanes3D().Add(c3d.o3d_planeOffset), "Ear support")
    plane.SetName("Проушина: внешняя плоскость Y=-20")
    offset = require(ksapi.IPlane3DByOffset(plane), "Offset plane")
    offset.SetBasePlane(require(part.GetDefaultObject(c3d.o3d_planeXOZ), "XOZ"))
    offset.SetOffset(20)
    offset.SetDirection(False)
    require(offset.Update(), "Offset Update")
    sk = new_sketch(model, plane, "Проушина Ø35 и соосное Ø14, высота центра 38")
    mapped = []
    for u, v in ((0, 0), (1, 0), (0, 1)):
        result = sk.GetPoint3D(u, v, 0, 0, 0)
        require(result[0], "Sketch coordinate mapping")
        mapped.append(tuple(result[1:]))
    stage("ear-plane-map", points=mapped)
    expected = ((0, -20, 0), (1, -20, 0), (0, -20, -1))
    require(all(math.dist(a, b) < 1e-7 for a, b in zip(mapped, expected)),
            f"Unqualified XOZ orientation: {mapped}")
    checks.append("GetPoint3D: плоскость Y=-20, локальные оси +X/−Z, нормаль +Y; профиль задан с учётом отображения")
    with edit(sk, checks) as (d, sy):
        datum = require(d.GetPoints().Add(), "Origin datum")
        datum.SetX(0); datum.SetY(0)
        require(datum.Update(), "Datum Update")
        constraint(datum, c.ksCFixedPoint, index=0)
        foot = segment(d, (-86, -9), (-51, -9))
        right = segment(d, (-51, -9), (-51, -38))
        crown = arc(d, (-68.5, -38), 17.5, 180, 360)
        left = segment(d, (-86, -38), (-86, -9))
        merge(foot, 1, right, 0); merge(right, 1, crown, 2)
        merge(crown, 1, left, 0); merge(left, 1, foot, 0)
        constraint(foot, c.ksCHorizontal)
        constraint(right, c.ksCVertical); constraint(left, c.ksCVertical)
        constraint(right, c.ksCTangentTwoCurves, partner=crown)
        constraint(left, c.ksCTangentTwoCurves, partner=crown)
        radial(sy, crown, (-68.5, -38), 17.5, "ear_R", 245)
        linear(sy, (-86, -9), (0, 0), (-43, 10), c.ksLinDHorizontal,
               foot, 0, datum, 0, "ear_back_offset", 86)
        linear(sy, (-86, -9), (0, 0), (8, -4), c.ksLinDVertical,
               foot, 0, datum, 0, "ear_base_height", 9)
        linear(sy, (-68.5, -38), (0, 0), (17, -19), c.ksLinDVertical,
               crown, 0, datum, 0, "ear_centre_height", 38)
        hole = circle(d, (-68.5, -38), 7)
        constraint(hole, c.ksCConcentricity, partner=crown)
        radial(sy, hole, (-68.5, -38), 7, "ear_hole_R", 310)
    return sk


def pattern_ear(part, model, seed):
    stage("pattern-ear")
    feature = require(model.GetFeaturePatterns().Add(c3d.o3d_meshCopy), "Ear pattern")
    feature.SetName("Две одинаковые проушины: шаг 31, толщина 9")
    pattern = require(ksapi.ILinearPattern(feature), "Linear pattern")
    pattern.SetInitialObjects([seed])
    pattern.SetAxis1(require(part.GetDefaultObject(c3d.o3d_axisOY), "OY"))
    pattern.SetAxis2(require(part.GetDefaultObject(c3d.o3d_axisOX), "OX"))
    pattern.SetStep1(31)
    pattern.SetCount1(2)
    pattern.SetDirection1(True)
    pattern.SetBoundaryInstancesStepFactor1(False)
    pattern.SetStep2(1)
    pattern.SetCount2(1)
    pattern.SetDirection2(True)
    pattern.SetBoundaryInstancesStepFactor2(False)
    pattern.SetBuildingType(c.ksLPSaveAll)
    pattern.SetGeometryPattern(False)
    require(pattern.Update(), "Pattern Update")


def validate(part, checks):
    require(part.RebuildModel(True), "RebuildModel")
    feature = require(ksapi.IFeature(part), "Part feature")
    errors, seen = [], set()

    def visit(item):
        if item.reference in seen:
            return
        seen.add(item.reference)
        error = item.GetObjectError()
        if error:
            errors.append((item.GetName(), error))
        for child in item.GetSubFeatures(c.ksOperTree, True, True):
            if child:
                visit(child)

    visit(feature)
    require(not errors, f"Feature errors: {errors}")
    checks.append("Перестроение успешно; ошибок во всём нативном дереве операций нет")
    bodies = feature.GetResultBodies()
    require(len(bodies) == 1 and bodies[0].IsSolid(), "Expected one solid body")
    checks.append("Итог: одно твёрдое тело")
    inertia = require(ksapi.IMassInertiaParam(part), "Mass properties")
    inertia.SetLengthUnits(c.ksLUnMM)
    units = inertia.GetLengthUnits()
    require(units == 1, f"Mass length units: {units}")
    require(inertia.Calculate(), "Mass calculation")
    volume = inertia.GetVolume()
    require(math.isfinite(volume) and volume > 0, f"Invalid volume: {volume}")
    checks.append(f"МЦХ: SetLengthUnits(ksLUnMM), GetLengthUnits={units}; Calculate успешно, V={volume:.9f} мм³")
    expected = 9 * (86 * 40 + math.pi * 20**2 / 2 - 23 * 14 - math.pi * 7**2) + 18 * (35 * (38 - 9) + math.pi * 17.5**2 / 2 - math.pi * 7**2)
    require(abs(volume - expected) < 1e-5, f"Drawing formula {expected}, CAD {volume}")
    checks.append(f"Независимая формула по размерам чертежа: {expected:.9f} мм³; совпадение с CAD < 1e-5 мм³")
    passed = 56489.5 <= volume < 56490.5
    checks.append(f"Сравнение с интервалом округления [56489.5,56490.5): {passed}")
    return volume, passed


def main():
    checks = ["Исходные размеры и форма прочитаны по текущему чертежу и превью 2.7; начало соответствует красной метке"]
    report = {"task": "2.7", "status": "failed", "title": "Practice Problem 2.7 — кронштейн с двумя проушинами", "script": "solution.py", "model": None, "volume_mm3": None, "reference_volume": REFERENCE, "reference_units": "mm3", "volume_passed": False, "checks": checks, "limitations": [], "tree": TREE}
    attempt = Path(tempfile.mkdtemp(prefix="attempt-", dir=ROOT))
    output = attempt / "model.m3d"
    require(not output.exists() and not output.is_symlink(), "Output already exists")
    doc = None
    try:
        stage("connect-existing-session")
        app = ksapi.GetKompas()
        if not app:
            report["status"] = "blocked"
            raise RuntimeError("Нет действующей API-сессии; КОМПАС не запускался")
        doc = require(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart, True), "Own new part")
        part = require(ksapi.IKompasDocument3D(doc).GetTopPart(), "Top part")
        part.SetName("Practice Problem 2.7 — кронштейн")
        model = require(part.GetModelContainer(), "Model container")
        stage("base-sketch")
        sk = base_sketch(part, model, checks)
        boss(model, sk, 9, "Основание толщиной 9")
        stage("ear-sketch")
        ear = ear_sketch(part, model, checks)
        seed = boss(model, ear, 9, "Проушина толщиной 9")
        pattern_ear(part, model, seed)
        stage("validation")
        volume, passed = validate(part, checks)
        report["volume_mm3"] = volume
        report["volume_passed"] = passed
        stage("save-new-model", path=str(output))
        require(not output.exists() and not output.is_symlink(), "Refuse existing SaveAs path")
        require(doc.SaveAs(str(output)), "SaveAs")
        require(output.is_file() and output.stat().st_size > 0, "Saved file missing/empty")
        checks.append("SaveAs выполнен в новый отсутствовавший путь attempt-*/model.m3d; файл существует и непуст")
        report["model"] = str(output.relative_to(ROOT))
        report["status"] = "passed" if passed else "partial"
        if not passed:
            report["limitations"].append("Объём не попал в интервал округления эталона; геометрия не подгонялась")
    except Exception as exc:
        report["limitations"].append(f"{type(exc).__name__}: {exc}")
        stage("failure", error=report["limitations"][-1])
        traceback.print_exc()
    finally:
        if doc is not None:
            try:
                require(doc.Close(c.kdDoNotSaveChanges), "Close own document")
                checks.append("Собственный документ закрыт finally; чужие документы не изменялись и не закрывались")
            except Exception as exc:
                report["status"] = "partial" if report["model"] else "failed"
                report["limitations"].append(f"Close: {exc}")
        (ROOT / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        stage("result", **report)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
