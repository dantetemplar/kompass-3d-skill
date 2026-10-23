# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Practice Problem 2.11: native, dimension-driven KOMPAS-3D model.

Drawing: diameter 25, clipped width 20, concentric bore diameter 8,
base thickness 3, two edge rails of width 3 and extra height 2 mm.
Origin: bore centre on the bottom face. No preview or exports.
"""
from contextlib import contextmanager
import json
import math
from pathlib import Path
import tempfile

import ksapi
from constants import constants as c
from constants3d import constants as c3d

ROOT = Path(__file__).resolve().parent
REPORT = {"task": "2.11", "status": "failed", "title": "Practice Problem 2.11 — пластина с двумя бортиками", "script": "solution.py", "model": None, "volume_mm3": None, "reference_volume": 1387, "reference_units": "mm3", "volume_passed": False, "checks": [], "limitations": [], "tree": []}
LAST = "preflight"
CAD_UNCERTAIN = False


class CheckFailure(RuntimeError):
    """A completed call or readback reported failure, not an unknown CAD outcome."""


def stage(text):
    global LAST
    LAST = text
    print(text, flush=True)


def require(value, message):
    if not value:
        raise CheckFailure(message)
    return value


def check(text):
    REPORT["checks"].append(text)
    print(text, flush=True)


def relation(obj, kind, partner=None, index=None, partner_index=None, name=None, value=None, expression=None):
    item = require(obj.NewConstraint(), "NewConstraint")
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
    if expression is not None:
        item.SetExpression(expression)
    require(item.Create() and item.IsValid(), f"Constraint {kind}, {name}")
    return item


def drive(dim, name, value, expression):
    relation(dim, c.ksCFixedDim)
    relation(dim, c.ksCDimWithVariable, name=name, value=value, expression=expression)
    return dim


def linear(symbols, a, ai, pa, b, bi, pb, pos, orientation, name, value, expression):
    dim = require(symbols.GetLineDimensions().Add(), "Linear dimension")
    dim.SetX1(pa[0]); dim.SetY1(pa[1])
    dim.SetX2(pb[0]); dim.SetY2(pb[1])
    dim.SetX3(pos[0]); dim.SetY3(pos[1])
    dim.SetOrientation(orientation)
    require(dim.Update(), "Linear Update")
    require(dim.Associate(), "Dimension Associate")
    links = dim.GetConstraints()
    for i, partner, pi in ((0, a, ai), (1, b, bi)):
        require(any(x.IsValid() and x.GetConstraintType() == c.ksCMergePoints and x.GetIndex() == i and x.GetPartnerIndex() == pi and any(p.GetId() == partner.GetId() for p in x.GetPartners()) for x in links), f"Dimension association {name}/{i}")
    return drive(dim, name, value, expression)


def radial(symbols, obj, radius, name, expression):
    dim = require(symbols.GetRadialDimensions().Add(), "Radial dimension")
    dim.SetBaseObject(obj)
    dim.SetXc(0.); dim.SetYc(0.); dim.SetRadius(radius); dim.SetAngle(70.)
    require(dim.Update(), "Radial Update")
    require(any(x.IsValid() and x.GetConstraintType() == c.ksCAssociation for x in dim.GetConstraints()), "Radial association")
    return drive(dim, name, radius, expression)


def line(drawing, a, b, auxiliary=False):
    item = require(drawing.GetLineSegments().Add(), "Line")
    item.SetX1(a[0]); item.SetY1(a[1]); item.SetX2(b[0]); item.SetY2(b[1])
    if auxiliary:
        item.SetStyle(3)
    require(item.Update(), "Line Update")
    return item


def arc(drawing, a1, a2):
    item = require(drawing.GetArcs().Add(), "Arc")
    item.SetXc(0.); item.SetYc(0.); item.SetRadius(12.5)
    item.SetAngle1(a1); item.SetAngle2(a2); item.SetDirection(False)
    require(item.Update(), "Arc Update")
    return item


@contextmanager
def sketch(model, plane, name):
    stage("Sketch: " + name)
    item = require(model.GetSketchs().Add(), "Sketch Add")
    item.SetName(name); item.SetPlane(plane)
    require(item.Update(), "Sketch plane Update")
    fragment = require(item.BeginEdit(False), "BeginEdit")
    try:
        fragment.SetParametricMode(True)
        require(fragment.IsParametricMode(), "Parametric mode")
        view = require(fragment.GetViewsAndLayersManager().GetViews().GetActiveView(), "Sketch view")
        yield item, require(ksapi.IDrawingContainer(view), "Drawing"), require(ksapi.ISymbols2DContainer(view), "Symbols")
    except (ConnectionError, OSError) as exc:
        global CAD_UNCERTAIN
        CAD_UNCERTAIN = True
        raise exc
    finally:
        if not CAD_UNCERTAIN:
            stage("EndEdit: " + name)
            require(item.EndEdit(), "EndEdit")
    state = item.GetConstraintsState()
    check(f"Эскиз «{name}»: GetConstraintsState={state} (fully-defined=1).")
    require(state == c.ksStateWellConstrained, f"Under/over-defined sketch: {name}: {state}")


def link_feature(feature, value, expression):
    variables = require(ksapi.IFeature(feature), "Feature").GetVariables(False, True)
    candidates = [v for v in variables if not v.IsInformation() and not v.IsReadOnly() and abs(v.GetValue() - value) < 1e-7]
    require(len(candidates) == 1, f"Expected unique depth/offset {value}: {[(v.GetName(), v.GetValue(), v.GetParameterNote()) for v in variables]}")
    variable = candidates[0]
    variable.SetExpression(expression)
    require(variable.GetExpression() == expression, f"Feature expression {expression}")
    check(f"«{feature.GetName()}»: параметр {variable.GetName()}={expression} ({variable.GetValue():g} мм).")


def extrude(model, profile, name, depth, expression, cut=False):
    stage("Extrusion: " + name)
    item = require(model.GetExtrusions().Add(c3d.o3d_cutExtrusion if cut else c3d.o3d_bossExtrusion), "Extrusion Add")
    item.SetName(name); item.SetProfiles([profile])
    # A cut from the upper plane into the material uses dtNormal, normal side.
    item.SetDirection(c3d.dtNormal)
    require(item.SetSideParameters(True, c3d.etBlind, depth, 0., False, None), "SetSideParameters")
    require(item.Update(), "Extrusion Update")
    link_feature(item, depth, expression)
    require(item.Update(), "Extrusion expression Update")
    return item


def build(part, doc3d):
    model = require(part.GetModelContainer(), "Model container")
    xoy = require(part.GetDefaultObject(c3d.o3d_planeXOY), "XOY")
    for name, value, note in (("outer_R", 12.5, "Наружный радиус Ø25/2"), ("bore_R", 4., "Радиус отверстия Ø8/2"), ("part_W", 20., "Ширина между боковыми срезами"), ("rail_W", 3., "Ширина обоих бортиков 3 TYP"), ("base_T", 3., "Толщина основания"), ("rail_H", 2., "Высота бортиков над основанием")):
        require(part.AddVariable(name, value, note), "Global variable " + name)
    with sketch(model, xoy, "01 Контур Ø25, ширина 20, соосное Ø8") as (base, d, sy):
        angle = math.degrees(math.atan2(7.5, 10.))
        top = arc(d, angle, 180. - angle)
        bottom = arc(d, 180. + angle, 360. - angle)
        left = line(d, (-10., 7.5), (-10., -7.5))
        right = line(d, (10., -7.5), (10., 7.5))
        hole = require(d.GetCircles().Add(), "Bore circle")
        hole.SetXc(0.); hole.SetYc(0.); hole.SetRadius(4.)
        require(hole.Update(), "Bore Update")
        relation(top, c.ksCFixedPoint, index=0)
        relation(bottom, c.ksCConcentricity, top)
        relation(bottom, c.ksCEqualRadius, top)
        relation(hole, c.ksCConcentricity, top)
        for edge, a, ai, b, bi in ((left, top, 2, bottom, 1), (right, bottom, 2, top, 1)):
            relation(edge, c.ksCMergePoints, a, 0, ai)
            relation(edge, c.ksCMergePoints, b, 1, bi)
            relation(edge, c.ksCVertical)
        relation(left, c.ksCEqualLength, right)
        radial(sy, top, 12.5, "outline_radius", "outer_R")
        radial(sy, hole, 4., "bore_radius", "bore_R")
        linear(sy, left, 0, (-10., 7.5), right, 1, (10., 7.5), (0., 17.), c.ksLinDHorizontal, "outline_width", 20., "part_W")
    blank = extrude(model, base, "02 Заготовка на полную высоту 3+2", 5., "base_T+rail_H")
    stage("Offset plane at full height")
    plane = require(ksapi.IAuxiliaryGeomContainer(part).GetPlanes3D().Add(c3d.o3d_planeOffset), "Offset plane")
    plane.SetName("03 Плоскость верха: 3+2")
    offset = require(ksapi.IPlane3DByOffset(plane), "Offset interface")
    offset.SetBasePlane(xoy); offset.SetOffset(5.); offset.SetDirection(True)
    require(offset.Update(), "Offset Update")
    link_feature(plane, 5., "base_T+rail_H")
    require(offset.Update(), "Offset expression Update")
    with sketch(model, plane, "04 Симметричная выборка, бортики 3 TYP") as (pocket, d, sy):
        pts = [(-7., -13.5), (7., -13.5), (7., 13.5), (-7., 13.5)]
        edges = [line(d, a, b) for a, b in zip(pts, pts[1:] + pts[:1])]
        for i, edge in enumerate(edges):
            relation(edge, c.ksCMergePoints, edges[(i + 1) % 4], 1, 0)
            relation(edge, c.ksCHorizontal if i % 2 == 0 else c.ksCVertical)
        origin = require(d.GetPoints().Add(), "Origin datum")
        origin.SetX(0.); origin.SetY(0.)
        require(origin.Update(), "Origin point Update")
        relation(origin, c.ksCFixedPoint, index=0)
        linear(sy, edges[0], 0, pts[0], origin, 0, (0., 0.), (-4., -20.), c.ksLinDHorizontal, "pocket_half_width", 7., "part_W/2-rail_W")
        linear(sy, edges[0], 0, pts[0], origin, 0, (0., 0.), (-19., -6.), c.ksLinDVertical, "pocket_half_span", 13.5, "outer_R+1")
        linear(sy, edges[0], 0, pts[0], edges[0], 1, pts[1], (0., -17.), c.ksLinDHorizontal, "pocket_width", 14., "part_W-2*rail_W")
        linear(sy, edges[1], 0, pts[1], edges[1], 1, pts[2], (16., 0.), c.ksLinDVertical, "tool_clearance_span", 27., "2*outer_R+2")
        # The tool extends beyond both circular ends; its extra 1 mm is not a part dimension.
    cut = extrude(model, pocket, "05 Выборка 2 до основания 3", 2., "rail_H", cut=True)
    require(doc3d.CompleteRebuildDocument(), "CompleteRebuildDocument")
    require(part.RebuildModel(True), "Part RebuildModel")
    for item in (base, pocket):
        require(item.GetConstraintsState() == c.ksStateWellConstrained, "Final sketch state")
    check("Начало координат — центр Ø8 на нижней плоскости Z=0; зафиксированы только базовые точки центров, не вся геометрия.")
    return (base, blank, plane, pocket, cut)


def validate(part):
    stage("Rebuild and tree validation")
    feature = require(ksapi.IFeature(part), "Part feature")
    seen, errors = set(), []
    def visit(item):
        if item.reference in seen:
            return None
        seen.add(item.reference)
        error = item.GetObjectError()
        if error:
            errors.append((item.GetName(), error))
        row = {"name": item.GetName(), "type": item.GetFeatureType(), "error": error, "children": []}
        for child in item.GetSubFeatures(c.ksOperTree, True, True):
            if child:
                sub = visit(child)
                if sub is not None:
                    row["children"].append(sub)
        return row
    REPORT["tree"] = visit(feature)
    require(not errors, f"Feature errors: {errors}")
    check("Полное перестроение успешно; GetObjectError=0 во всём дереве операций.")
    bodies = feature.GetResultBodies()
    require(len(bodies) == 1 and bodies[0].IsSolid(), "One solid body")
    check("Итог содержит ровно одно твёрдое тело.")
    bounds = bodies[0].GetGabarit(0, 0, 0, 0, 0, 0)
    require(bounds[0], "Body bounds status")
    require(all(abs(a-b) < 1e-6 for a, b in zip(bounds[1:], (-10., -12.5, 0., 10., 12.5, 5.))), f"Bounds {bounds}")
    check("Габариты B-rep: X=−10…10, Y=−12.5…12.5, Z=0…5 мм.")
    stage("Mass properties Calculate")
    mass = require(ksapi.IMassInertiaParam(part), "Mass properties")
    mass.SetLengthUnits(c.ksLUnMM)
    require(mass.GetLengthUnits() == 1, "Millimetres before Calculate")
    require(mass.Calculate(), "Calculate")
    require(mass.GetLengthUnits() == 1, "Millimetres after Calculate")
    volume = mass.GetVolume()
    require(math.isfinite(volume) and volume > 0., "Finite positive volume")
    REPORT["volume_mm3"] = volume
    REPORT["volume_passed"] = 1386.5 <= volume < 1387.5
    check(f"МЦХ: SetLengthUnits(ksLUnMM), GetLengthUnits=1 до/после Calculate; объём {volume:.12f} мм³.")
    check(f"Независимый эталон [1386.5,1387.5) мм³: {REPORT['volume_passed']}.")


def main():
    attempt = Path(tempfile.mkdtemp(prefix="attempt-", dir=ROOT))
    output = attempt / "model.m3d"
    require(not output.exists() and not output.is_symlink(), "New absent model path")
    doc = None
    previous = None
    try:
        stage("GetKompas: connect only")
        app = require(ksapi.GetKompas(), "Нет существующей API-сессии; запуск КОМПАС запрещён")
        previous = app.GetActiveDocument()
        stage("Create owned part")
        doc = require(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart, True), "Own part document")
        d3 = require(ksapi.IKompasDocument3D(doc), "Document3D")
        part = require(d3.GetTopPart(), "Top part")
        part.SetName(REPORT["title"])
        build(part, d3)
        validate(part)
        stage("SaveAs new model path")
        require(not output.exists() and not output.is_symlink(), "SaveAs target must still be absent")
        require(doc.SaveAs(str(output)), "SaveAs")
        require(output.is_file() and output.stat().st_size > 0, "Nonempty model file")
        require(Path(doc.GetFullPath()).resolve() == output.resolve(), "Saved path readback")
        REPORT["model"] = str(output.relative_to(ROOT))
        check("SaveAs выполнен только в новый отсутствовавший путь; model.m3d непустой, путь документа подтверждён.")
        REPORT["status"] = "passed" if REPORT["volume_passed"] else "partial"
        if not REPORT["volume_passed"]:
            REPORT["limitations"].append("Объём не попал в эталонный интервал; размеры не подгонялись.")
        REPORT["limitations"].append("Изменение размеров, повторное открытие, исчерпывающий аудит топологии и preview не выполнялись по условию.")
    except Exception as exc:
        global CAD_UNCERTAIN
        if isinstance(exc, (ConnectionError, OSError)):
            CAD_UNCERTAIN = True
            REPORT["status"] = "blocked"
            REPORT["limitations"].append("Исход CAD-вызова неизвестен: дальнейшие CAD-записи, включая закрытие, остановлены.")
        REPORT["limitations"].append(f"Последняя операция: {LAST}. {type(exc).__name__}: {exc}")
        print(REPORT["limitations"][-1], flush=True)
        raise
    finally:
        try:
            if doc is not None and not CAD_UNCERTAIN:
                stage("Close owned document")
                require(doc.Close(c.kdDoNotSaveChanges), "Close owned document")
                check("Собственный документ закрыт в finally; чужие документы не изменялись и не закрывались.")
            if previous and not CAD_UNCERTAIN:
                previous.SetActive()
        finally:
            (ROOT / "result.json").write_text(json.dumps(REPORT, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
