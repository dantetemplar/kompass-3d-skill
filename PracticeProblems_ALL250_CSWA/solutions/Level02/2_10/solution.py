# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Practice Problem 2.10: native constrained arcs/lines, extruded 7 mm.

The inner spoke sides are radial at 60 and 195 degrees. The outer
sides are offset outward by 13 mm. All profile transitions are R6.
Only the marked origin (circle centre and baseline start) is anchored;
remaining geometry is governed by dimensions and geometric constraints.
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
TOL = 1e-7


def require(value, message):
    if not value:
        raise RuntimeError(message)
    return value


def out(stage, **data):
    print(json.dumps({"stage": stage, **data}, ensure_ascii=False), flush=True)


def add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def mul(a, k):
    return (a[0] * k, a[1] * k)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def unit(a):
    return mul(a, 1 / math.hypot(*a))


def left(a):
    return (-a[1], a[0])


def polar(r, angle):
    return (r * math.cos(math.radians(angle)), r * math.sin(math.radians(angle)))


def line(a, b, tag):
    return {"kind": "line", "a": a, "b": b, "tag": tag}


def arc(center, radius, a, b, ccw, tag):
    return {"kind": "arc", "center": center, "radius": radius,
            "a": a, "b": b, "ccw": ccw, "tag": tag}


def tangent(curve, p):
    if curve["kind"] == "line":
        return unit(sub(curve["b"], curve["a"]))
    return mul(left(unit(sub(p, curve["center"]))), 1 if curve["ccw"] else -1)


def offset(curve, side, radius):
    if curve["kind"] == "line":
        direction = unit(sub(curve["b"], curve["a"]))
        return ("line", add(curve["a"], mul(left(direction), side * radius)), direction)
    return ("circle", curve["center"], curve["radius"] - (1 if curve["ccw"] else -1) * side * radius)


def intersections(a, b):
    if a[0] == "circle" and b[0] == "line":
        return intersections(b, a)
    if a[0] == "line" and b[0] == "line":
        return [add(a[1], mul(a[2], cross(sub(b[1], a[1]), b[2]) / cross(a[2], b[2])))]
    if a[0] == "line":
        t = dot(sub(b[1], a[1]), a[2])
        foot = add(a[1], mul(a[2], t))
        length = math.sqrt(max(0., b[2] ** 2 - dot(sub(foot, b[1]), sub(foot, b[1]))))
        return [add(foot, mul(a[2], length)), add(foot, mul(a[2], -length))]
    distance = math.dist(a[1], b[1])
    direction = unit(sub(b[1], a[1]))
    x = (a[2] ** 2 - b[2] ** 2 + distance ** 2) / (2 * distance)
    h = math.sqrt(max(0., a[2] ** 2 - x ** 2))
    foot = add(a[1], mul(direction, x))
    return [add(foot, mul(left(direction), h)), add(foot, mul(left(direction), -h))]


def contact(curve, center):
    if curve["kind"] == "line":
        direction = unit(sub(curve["b"], curve["a"]))
        return add(curve["a"], mul(direction, dot(sub(center, curve["a"]), direction)))
    return add(curve["center"], mul(unit(sub(center, curve["center"])), curve["radius"]))


def round_chain(curves):
    """Analytic trim of circles/lines; no faceting and no volume fitting."""
    fillets = []
    trimmed = [dict(item) for item in curves]
    for i, first in enumerate(curves):
        second = curves[(i + 1) % len(curves)]
        corner = first["b"]
        require(math.dist(corner, second["a"]) < TOL, "Sharp contour closure")
        side = 1 if cross(tangent(first, corner), tangent(second, corner)) > 0 else -1
        center = min(intersections(offset(first, side, 6), offset(second, side, 6)),
                     key=lambda p: math.dist(p, corner))
        p, q = contact(first, center), contact(second, center)
        require(abs(math.dist(center, p) - 6) < TOL and abs(math.dist(center, q) - 6) < TOL,
                "Analytic fillet tangency")
        trimmed[i]["b"] = p
        trimmed[(i + 1) % len(curves)]["a"] = q
        fillets.append(arc(center, 6., p, q, side > 0, "R6_" + first["tag"]))
    return [item for pair in zip(trimmed, fillets) for item in pair]


def contours():
    origin = (0., 0.)
    eye = (85., 0.)
    upper = polar(1, 60)
    lower = polar(1, 195)
    up_offset = mul(left(upper), -13.)
    lo_offset = mul(left(lower), 13.)
    upper_ring = add(up_offset, mul(upper, math.sqrt(64 ** 2 - 13 ** 2)))
    lower_ring = add(lo_offset, mul(lower, math.sqrt(64 ** 2 - 13 ** 2)))
    lower_hub = add(lo_offset, mul(lower, math.sqrt(18 ** 2 - 13 ** 2)))
    hub_bottom = (math.sqrt(18 ** 2 - 9 ** 2), -9.)
    eye_bottom = (85 - math.sqrt(16 ** 2 - 9 ** 2), -9.)
    eye_top = (eye_bottom[0], 9.)
    upper_elbow = add(up_offset, mul(upper, (9 - up_offset[1]) / upper[1]))
    outer = [arc(origin, 64., upper_ring, lower_ring, True, "rim_R64"),
             line(lower_ring, lower_hub, "lower_outer"),
             arc(origin, 18., lower_hub, hub_bottom, True, "hub_R18"),
             line(hub_bottom, eye_bottom, "strap_bottom"),
             arc(eye, 16., eye_bottom, eye_top, True, "eye_R16"),
             line(eye_top, upper_elbow, "strap_top"),
             line(upper_elbow, upper_ring, "upper_outer")]
    inner = [arc(origin, 51., polar(51, 60), polar(51, 195), True, "window_R51"),
             line(polar(51, 195), polar(18, 195), "lower_inner"),
             arc(origin, 18., polar(18, 195), polar(18, 60), False, "window_hub_R18"),
             line(polar(18, 60), polar(51, 60), "upper_inner")]
    return round_chain(outer), round_chain(inner)


def con(obj, kind, partner=None, index=None, other=None, name=None, value=None):
    item = require(obj.NewConstraint(), "NewConstraint")
    item.SetConstraintType(kind)
    if partner is not None:
        item.SetPartners([partner])
    if index is not None:
        item.SetIndex(index)
    if other is not None:
        item.SetPartnerIndex(other)
    if name is not None:
        item.SetVariable(name)
    if value is not None:
        item.SetConstraintValue(value)
    require(item.Create() and item.IsValid(), f"Constraint type={kind}, name={name}, object={obj.GetId()}")
    return item


def merge(a, ai, b, bi):
    return con(a, c.ksCMergePoints, b, ai, bi)


def drive(dim, name, value):
    con(dim, c.ksCFixedDim)
    con(dim, c.ksCDimWithVariable, name=name, value=value)
    return dim


def radial(symbols, obj, center, radius, name):
    dim = require(symbols.GetRadialDimensions().Add(), "Radial dimension")
    dim.SetBaseObject(obj)
    dim.SetXc(center[0]); dim.SetYc(center[1])
    dim.SetRadius(radius); dim.SetAngle(35.)
    require(dim.Update(), "Radial Update " + name)
    return drive(dim, name, radius)


def linear(symbols, a, ai, p, b, bi, q, orientation, value, name):
    dim = require(symbols.GetLineDimensions().Add(), "Linear dimension")
    dim.SetX1(p[0]); dim.SetY1(p[1]); dim.SetX2(q[0]); dim.SetY2(q[1])
    dim.SetX3((p[0] + q[0]) / 2 + 5); dim.SetY3((p[1] + q[1]) / 2 - 12)
    dim.SetOrientation(orientation)
    if orientation == c.ksLinDParallel:
        dim.SetAngle(math.degrees(math.atan2(q[1] - p[1], q[0] - p[0])))
    require(dim.Update(), "Linear Update " + name)
    require(dim.Associate(), "Linear Associate " + name)
    require(all(x.IsValid() for x in dim.GetConstraints()), "Dimension associations " + name)
    return drive(dim, name, value)


def segment(drawing, a, b, construction=False):
    obj = require(drawing.GetLineSegments().Add(), "Line")
    obj.SetX1(a[0]); obj.SetY1(a[1]); obj.SetX2(b[0]); obj.SetY2(b[1])
    require(obj.Update(), "Line Update")
    return obj


def angle_dimension(symbols, baseline, obj, value, name, p, q):
    dim = require(symbols.GetAngleDimensions().Add(c.ksDrADimension), "Angle dimension")
    dim.SetBaseObject1(baseline); dim.SetBaseObject2(obj)
    dim.SetXc(0.); dim.SetYc(0.); dim.SetRadius(75.)
    dim.SetX1(20.); dim.SetY1(0.); dim.SetX2(p[0]); dim.SetY2(p[1])
    dim.SetAngle1(0.); dim.SetAngle2(value)
    dim.SetX3(q[0]); dim.SetY3(q[1])
    dim.SetDimensionType(c.ksADMinAngle)
    require(dim.Update(), "Angle dimension Update " + name)
    con(dim, c.ksCFixedDim)
    item = require(dim.NewConstraint(), "Angle variable")
    item.SetConstraintType(c.ksCDimWithVariable)
    item.SetVariable(name)
    item.SetDegrees(int(value))
    require(item.Create() and item.IsValid(), "Angle driving variable " + name)
    return dim


@contextmanager
def edit(sketch):
    fragment = require(sketch.BeginEdit(False), "BeginEdit")
    try:
        fragment.SetParametricMode(True)
        view = require(fragment.GetViewsAndLayersManager().GetViews().GetActiveView(), "Sketch view")
        yield fragment, ksapi.IDrawingContainer(view), ksapi.ISymbols2DContainer(view)
    finally:
        require(sketch.EndEdit(), "EndEdit")


def build(part, model, checks):
    sketch = require(model.GetSketchs().Add(), "Sketch")
    sketch.SetName("01 Профиль: R64/R51, спицы 13, R18, проушина Ø32, отверстия")
    sketch.SetPlane(require(part.GetDefaultObject(c3d.o3d_planeXOY), "XOY"))
    require(sketch.Update(), "Sketch plane")
    geometry = {}
    objects = {}
    with edit(sketch) as (fragment, drawing, symbols):
        for chain in contours():
            chain_objects = []
            for shape in chain:
                if shape["kind"] == "line":
                    obj = segment(drawing, shape["a"], shape["b"])
                else:
                    obj = require(drawing.GetArcs().Add(), "Arc")
                    obj.SetXc(shape["center"][0]); obj.SetYc(shape["center"][1])
                    obj.SetRadius(shape["radius"])
                    obj.SetAngle1(math.degrees(math.atan2(shape["a"][1] - shape["center"][1], shape["a"][0] - shape["center"][0])) % 360)
                    obj.SetAngle2(math.degrees(math.atan2(shape["b"][1] - shape["center"][1], shape["b"][0] - shape["center"][0])) % 360)
                    obj.SetDirection(not shape["ccw"])
                    require(obj.Update(), "Arc Update " + shape["tag"])
                objects[shape["tag"]] = obj
                geometry[shape["tag"]] = shape
                chain_objects.append(obj)
            for i, shape in enumerate(chain):
                following = chain[(i + 1) % len(chain)]
                obj, nxt = chain_objects[i], chain_objects[(i + 1) % len(chain)]
                merge(obj, 2 if shape["kind"] == "arc" else 1, nxt, 1 if following["kind"] == "arc" else 0)
                con(obj, c.ksCTangentTwoCurves, nxt)
        out("closed-tangent-contours", curves=len(objects))
        origin = objects["rim_R64"]
        con(origin, c.ksCFixedPoint, index=0)
        radial(symbols, origin, (0, 0), 64., "rim_radius")
        for tag, radius in (("hub_R18", 18.), ("window_R51", 51.), ("window_hub_R18", 18.)):
            con(objects[tag], c.ksCConcentricity, origin)
            if tag == "window_hub_R18":
                con(objects[tag], c.ksCEqualRadius, objects["hub_R18"])
            else:
                radial(symbols, objects[tag], (0, 0), radius, tag)
        eye = objects["eye_R16"]
        radial(symbols, eye, (85, 0), 16., "eye_radius")
        con(eye, c.ksCHAlignPoints, origin, 0, 0)
        linear(symbols, origin, 0, (0, 0), eye, 0, (85, 0), c.ksLinDHorizontal, 85., "eye_pitch")
        fillets = [tag for tag in objects if tag.startswith("R6_")]
        first = objects[fillets[0]]
        radial(symbols, first, geometry[fillets[0]]["center"], 6., "blend_radius")
        for tag in fillets[1:]:
            con(objects[tag], c.ksCEqualRadius, first)
        for tag in ("strap_bottom", "strap_top"):
            obj = objects[tag]
            con(obj, c.ksCHorizontal)
            linear(symbols, origin, 0, (0, 0), obj, 0, geometry[tag]["a"], c.ksLinDVertical, 9., tag + "_half_width")
        baseline = segment(drawing, (0, 0), (20, 0), True)
        con(baseline, c.ksCFixedPoint, index=0)
        con(baseline, c.ksCHorizontal)
        linear(symbols, baseline, 0, (0, 0), baseline, 1, (20, 0), c.ksLinDHorizontal, 20., "datum_length")
        for tag, value in (("lower_inner", 15.), ("upper_inner", 60.)):
            obj = objects[tag]
            con(origin, c.ksCPointOnCurve, obj, index=0)
            angle_dimension(symbols, baseline, obj, value, tag + "_angle", geometry[tag]["a"], polar(75, value / 2))
        auxiliaries = [baseline]
        for side, phi in (("lower", 195.), ("upper", 60.)):
            outer, inner = objects[side + "_outer"], objects[side + "_inner"]
            con(outer, c.ksCParallel, inner)
            if side == "lower":
                pitch = require(drawing.GetCircles().Add(), "Spoke offset construction circle")
                pitch.SetXc(0.); pitch.SetYc(0.); pitch.SetRadius(13.)
                require(pitch.Update(), "Construction circle Update")
                con(pitch, c.ksCConcentricity, origin)
                radial(symbols, pitch, (0, 0), 13., "spoke_width")
                auxiliaries.append(pitch)
            con(pitch, c.ksCTangentTwoCurves, outer)
        for center, radius, target, name in (((0, 0), 10.5, origin, "central_bore_R"), ((85, 0), 8., eye, "eye_bore_R")):
            hole = require(drawing.GetCircles().Add(), "Bore circle")
            hole.SetXc(center[0]); hole.SetYc(center[1]); hole.SetRadius(radius)
            require(hole.Update(), "Bore Update")
            con(hole, c.ksCConcentricity, target)
            radial(symbols, hole, center, radius, name)
        for auxiliary in auxiliaries:
            auxiliary.SetStyle(2)
            require(auxiliary.Update(), "Auxiliary style Update")
        out("native-constraints-created")
    state = sketch.GetConstraintsState()
    checks.append(f"Состояние размерного эскиза после EndEdit: {state} (WellConstrained={c.ksStateWellConstrained})")
    out("sketch-state", state=state, expected=c.ksStateWellConstrained)
    operation = require(model.GetExtrusions().Add(c3d.o3d_bossExtrusion), "Extrusion")
    operation.SetName("02 Пластина, толщина 7 мм")
    operation.SetProfiles([sketch]); operation.SetDirection(c3d.dtNormal)
    require(operation.SetSideParameters(True, c3d.etBlind, 7., 0., False, None), "Extrusion 7 mm")
    require(operation.Update(), "Extrusion Update")
    checks.append("Нативное выдавливание замкнутых дуговых контуров на 7 мм: Update=True")
    return sketch, operation, state


def errors(part):
    found, seen = [], set()
    def visit(feature):
        if feature.reference in seen:
            return
        seen.add(feature.reference)
        if feature.GetObjectError():
            found.append([feature.GetName(), feature.GetObjectError()])
        for child in feature.GetSubFeatures(c.ksOperTree, True, True):
            if child:
                visit(child)
    visit(ksapi.IFeature(part))
    return found


def main():
    result = {"task": "2.10", "status": "failed", "title": "Плоский секторный рычаг с двумя отверстиями",
              "script": "solution.py", "model": None, "volume_mm3": None, "reference_volume": 36748,
              "reference_units": "mm3", "volume_passed": False, "checks": [], "limitations": [],
              "tree": "Эскиз дуг и отрезков с R6 и отверстиями → выдавливание 7 мм"}
    doc = None
    try:
        output = Path(tempfile.mkdtemp(prefix="attempt-", dir=ROOT)) / "model.m3d"
        require(not output.exists(), "Output already exists")
        app = require(ksapi.GetKompas(), "Нет существующей API-сессии КОМПАС; запуск запрещён")
        out("connected")
        doc = require(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart, True), "Own document")
        doc3d = require(ksapi.IKompasDocument3D(doc), "3D document")
        part = require(doc3d.GetTopPart(), "Top part")
        part.SetName("Practice Problem 2.10 — Секторный рычаг")
        sketch, operation, state = build(part, require(part.GetModelContainer(), "Model container"), result["checks"])
        require(part.RebuildModel(True), "RebuildModel")
        feature_errors = errors(part)
        require(not feature_errors, f"Ошибки операций: {feature_errors}")
        result["checks"].append("Перестроение успешно; ошибки эскиза и операций отсутствуют")
        bodies = ksapi.IFeature(part).GetResultBodies()
        require(len(bodies) == 1 and bodies[0].IsSolid(), "One solid required")
        result["checks"].append("Получено одно твёрдое тело")
        mass = require(ksapi.IMassInertiaParam(part), "Mass properties")
        mass.SetLengthUnits(c.ksLUnMM)
        units = mass.GetLengthUnits()
        require(units == 1, f"Mass length units: {units}")
        require(mass.Calculate(), "Mass Calculate")
        volume = mass.GetVolume()
        require(math.isfinite(volume) and volume > 0, "Finite positive volume")
        result["volume_mm3"] = volume
        result["volume_passed"] = 36747.5 <= volume < 36748.5
        result["checks"].append(f"МЦХ: SetLengthUnits(ksLUnMM), GetLengthUnits={units}; Calculate=True; объём={volume:.9f} мм³")
        result["checks"].append(f"Сравнение [36747.5,36748.5): {result['volume_passed']}")
        require(not output.exists() and not output.is_symlink(), "Refusing existing SaveAs path")
        require(doc.SaveAs(str(output)), "SaveAs")
        require(output.is_file() and output.stat().st_size > 0, "Saved native file")
        result["model"] = str(output.relative_to(ROOT))
        result["checks"].append("SaveAs в ранее отсутствовавший attempt-*/model.m3d успешен; файл непустой")
        if state != c.ksStateWellConstrained:
            result["limitations"].append(f"Эскиз не полностью определён: состояние {state}")
        if not result["volume_passed"]:
            result["limitations"].append("Объём не попал в интервал округления эталона; геометрия под объём не подгонялась")
        result["status"] = "passed" if result["volume_passed"] and state == c.ksStateWellConstrained else "partial"
    except Exception as exc:
        result["limitations"].append(f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
    finally:
        if doc is not None:
            try:
                require(doc.Close(c.kdDoNotSaveChanges), "Close own document")
                result["checks"].append("Собственный документ закрыт в finally; чужие документы не изменялись")
            except Exception as exc:
                result["status"] = "partial" if result["model"] else "failed"
                result["limitations"].append(f"Закрытие собственного документа: {exc}")
        (ROOT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        out("result", **result)


if __name__ == "__main__":
    main()
