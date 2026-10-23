# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Practice 1.3: native tangent lever, millimetres, no dimension perturbations."""
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


def require(value, message):
    if not value:
        raise RuntimeError(message)
    return value


def log(message):
    print(message, flush=True)


def constraint(obj, kind, partner=None, index=None, partner_index=None,
               name=None, value=None):
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
    require(item.Create() and item.IsValid(), f"Constraint {kind}, {name}")
    return item


def driving(dim, name, value):
    constraint(dim, c.ksCFixedDim)
    constraint(dim, c.ksCDimWithVariable, name=name, value=value)


def radial(symbols, obj, name, value):
    dim = require(symbols.GetRadialDimensions().Add(), "Radial dimension")
    dim.SetBaseObject(obj)
    dim.SetXc(obj.GetXc())
    dim.SetYc(obj.GetYc())
    dim.SetRadius(value)
    dim.SetAngle(135.)
    require(dim.Update(), "Radial dimension Update")
    require(any(x.IsValid() and x.GetConstraintType() == c.ksCAssociation
                for x in dim.GetConstraints()), "Radial association")
    driving(dim, name, value)


def distance(symbols, first, second, name, value, position):
    dim = require(symbols.GetLineDimensions().Add(), "Distance")
    dim.SetX1(first.GetXc())
    dim.SetY1(first.GetYc())
    dim.SetX2(second.GetXc())
    dim.SetY2(second.GetYc())
    dim.SetX3(position[0])
    dim.SetY3(position[1])
    dim.SetOrientation(c.ksLinDHorizontal)
    require(dim.Update() and dim.Associate(), "Distance association")
    for index, obj in enumerate((first, second)):
        require(any(x.IsValid() and x.GetConstraintType() == c.ksCMergePoints
                    and x.GetIndex() == index and x.GetPartnerIndex() == 0
                    and any(p.GetId() == obj.GetId() for p in x.GetPartners())
                    for x in dim.GetConstraints()), "Distance witness link")
    driving(dim, name, value)


@contextmanager
def sketch_edit(part, model, name, states):
    sketch = require(model.GetSketchs().Add(), "Sketch")
    sketch.SetName(name)
    sketch.SetPlane(require(part.GetDefaultObject(c3d.o3d_planeXOY), "XOY"))
    require(sketch.Update(), "Sketch Update")
    fragment = require(sketch.BeginEdit(False), "BeginEdit")
    try:
        fragment.SetParametricMode(True)
        require(fragment.IsParametricMode(), "Parametric mode")
        view = require(fragment.GetViewsAndLayersManager().GetViews().GetActiveView(), "View")
        yield sketch, ksapi.IDrawingContainer(view), ksapi.ISymbols2DContainer(view)
    finally:
        require(sketch.EndEdit(), "EndEdit")
    state = sketch.GetConstraintsState()
    states.append((name, state))
    log(f"Sketch {name}: constraint state {state}")
    require(state == c.ksStateWellConstrained, f"Sketch not fully constrained: {name}: {state}")


def circle(drawing, x, y, r):
    obj = require(drawing.GetCircles().Add(), "Circle")
    obj.SetXc(x)
    obj.SetYc(y)
    obj.SetRadius(r)
    require(obj.Update(), "Circle Update")
    return obj


def arc(drawing, x, r, first, second):
    obj = require(drawing.GetArcs().Add(), "Arc")
    obj.SetXc(x)
    obj.SetYc(0.)
    obj.SetRadius(r)
    # IArc.SetAngle1/SetAngle2 require DEGREES, direction False = CCW.
    obj.SetAngle1(first)
    obj.SetAngle2(second)
    obj.SetDirection(False)
    require(obj.Update(), "Arc Update")
    return obj


def line(drawing, p, q):
    obj = require(drawing.GetLineSegments().Add(), "Line")
    obj.SetX1(p[0])
    obj.SetY1(p[1])
    obj.SetX2(q[0])
    obj.SetY2(q[1])
    require(obj.Update(), "Line Update")
    return obj


def extrusion(model, sketch, depth, name, reverse=False):
    obj = require(model.GetExtrusions().Add(c3d.o3d_bossExtrusion), "Extrusion")
    obj.SetName(name)
    obj.SetProfiles([sketch])
    obj.SetDirection(c3d.dtReverse if reverse else c3d.dtNormal)
    require(obj.SetSideParameters(not reverse, c3d.etBlind, depth, 0., False, None), "Depth")
    require(obj.Update(), f"Extrusion Update: {name}")
    log(f"Built {name}")
    return obj


def build(part, model, states):
    # Outer tangencies are determined only by R16, R9 and centre distance 38.
    R, r, d = 16., 9., 38.
    co = (R-r)/d
    si = math.sqrt(1-co*co)
    angle = math.degrees(math.acos(co))
    with sketch_edit(part, model, "Касательный контур рычага", states) as (sketch, drawing, symbols):
        big = arc(drawing, 0., R, angle, 360.-angle)
        small = arc(drawing, d, r, 360.-angle, angle)
        upper = line(drawing, (R*co, R*si), (d+r*co, r*si))
        lower = line(drawing, (R*co, -R*si), (d+r*co, -r*si))
        constraint(big, c.ksCFixedPoint, index=0)
        constraint(big, c.ksCHAlignPoints, small, 0, 0)
        radial(symbols, big, "outer_hub_radius", R)
        radial(symbols, small, "outer_pin_radius", r)
        distance(symbols, big, small, "centres", d, (19., -24.))
        # Arc indices: centre 0, start 1, end 2. Segment indices: 0, 1.
        for segment, aindex, bindex in ((upper, 1, 2), (lower, 2, 1)):
            constraint(segment, c.ksCMergePoints, big, 0, aindex)
            constraint(segment, c.ksCMergePoints, small, 1, bindex)
            constraint(segment, c.ksCTangentTwoCurves, big)
            constraint(segment, c.ksCTangentTwoCurves, small)
        bore = circle(drawing, 0., 0., 10.)
        pinhole = circle(drawing, d, 0., 3.)
        constraint(bore, c.ksCConcentricity, big)
        constraint(pinhole, c.ksCConcentricity, small)
        radial(symbols, bore, "bore_radius", 10.)
        radial(symbols, pinhole, "pin_hole_radius", 3.)
    extrusion(model, sketch, 6., "Рычаг — толщина 6")
    with sketch_edit(part, model, "Большая кольцевая бобышка", states) as (sketch, drawing, symbols):
        outer = circle(drawing, 0., 0., 16.)
        inner = circle(drawing, 0., 0., 10.)
        constraint(outer, c.ksCFixedPoint, index=0)
        constraint(inner, c.ksCConcentricity, outer)
        radial(symbols, inner, "hub_bore_radius", 10.)
        radial(symbols, outer, "hub_outer_radius", 16.)
    extrusion(model, sketch, 14., "Большая бобышка — высота 14")
    with sketch_edit(part, model, "Малая кольцевая бобышка", states) as (sketch, drawing, symbols):
        # A construction centreline locates both circles by a driving 38 mm dimension.
        guide = line(drawing, (0., 0.), (38., 0.))
        guide.SetStyle(3)
        require(guide.Update(), "Construction line Update")
        constraint(guide, c.ksCFixedPoint, index=0)
        constraint(guide, c.ksCHorizontal)
        outer = circle(drawing, 38., 0., 9.)
        inner = circle(drawing, 38., 0., 3.)
        constraint(outer, c.ksCMergePoints, guide, 0, 1)
        constraint(inner, c.ksCConcentricity, outer)
        dim = require(symbols.GetLineDimensions().Add(), "Boss location")
        for setter, value in ((dim.SetX1, 0.), (dim.SetY1, 0.), (dim.SetX2, 38.),
                              (dim.SetY2, 0.), (dim.SetX3, 19.), (dim.SetY3, -15.)):
            setter(value)
        dim.SetOrientation(c.ksLinDHorizontal)
        require(dim.Update() and dim.Associate(), "Boss location association")
        driving(dim, "pin_centres", 38.)
        radial(symbols, outer, "pin_outer_radius", 9.)
        radial(symbols, inner, "pin_bore_radius", 3.)
    extrusion(model, sketch, 24., "Малая бобышка — вниз 24", reverse=True)


def tree_errors(part):
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
    visit(ksapi.IFeature(part))
    return errors


def main():
    result = {"task": "1.3", "status": "failed", "title": "Рычаг с двумя бобышками",
              "script": "solution.py", "model": None, "volume_mm3": None,
              "reference_volume": 16268, "reference_units": "mm3", "volume_passed": None,
              "checks": [], "limitations": [
                  "Размер 6 у большой окружности прочитан как радиальная толщина стенки: R16 = Ø20/2 + 6.",
                  "Общие радиусы и межосевое расстояние повторены управляющими размерами в разных эскизах; межэскизных формул нет.",
                  "Пробные изменения размеров и повторное открытие не выполнялись."],
              "tree": "Касательный эскиз → рычаг 6; кольцевой эскиз → бобышка 14; кольцевой эскиз → бобышка вниз 24"}
    attempt = Path(tempfile.mkdtemp(prefix="attempt-", dir=ROOT))
    output = attempt / "model.m3d"
    require(not output.exists(), "Output must not exist")
    doc, previous = None, None
    transport_unknown = False
    states = []
    code = 1
    try:
        app = require(ksapi.GetKompas(), "Нет действующей API-сессии")
        previous = app.GetActiveDocument()
        doc = require(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart, True), "New own part")
        require(doc.GetDocumentType() == c.ksDocumentPart, "Document type")
        part = require(ksapi.IKompasDocument3D(doc).GetTopPart(), "Top part")
        part.SetName(result["title"])
        build(part, require(part.GetModelContainer(), "Model container"), states)
        result["checks"].append("Три эскиза полностью определены нативными связями и управляющими размерами; фиксированы только базовые точки.")
        require(part.RebuildModel(True), "RebuildModel")
        errors = tree_errors(part)
        require(not errors, f"Ошибки дерева: {errors}")
        result["checks"].append("Перестроение успешно, рекурсивная проверка GetObjectError: ошибок нет.")
        bodies = ksapi.IFeature(part).GetResultBodies()
        require(len(bodies) == 1 and bodies[0].IsSolid(), "Exactly one solid")
        result["checks"].append("Конечный результат — одно твёрдое тело.")
        mass = require(ksapi.IMassInertiaParam(part), "Mass properties")
        mass.SetLengthUnits(c.ksLUnMM)
        require(mass.GetLengthUnits() == c.ksLUnMM, "Mass units readback")
        require(mass.Calculate() and mass.IsActual(), "Actual mass properties")
        volume = mass.GetVolume()
        require(math.isfinite(volume) and volume > 0., "Positive CAD volume")
        result["volume_mm3"] = volume
        passed = 16267.5 <= volume < 16268.5
        result["volume_passed"] = passed
        result["checks"].append(f"МЦХ: SetLengthUnits/GetLengthUnits = ksLUnMM; актуальный объём {volume:.9f} мм³; интервал эталона [16267.5, 16268.5): {'пройден' if passed else 'не пройден'}.")
        require(not output.exists(), "Refuse overwrite")
        require(doc.SaveAs(str(output)), "SaveAs")
        require(output.is_file() and output.stat().st_size > 0, "Saved nonempty file")
        require(Path(doc.GetFullPath()).resolve() == output.resolve(), "Saved full path")
        result["model"] = str(output.relative_to(ROOT))
        result["checks"].append("SaveAs выполнен в новый attempt-*; непустой model.m3d существует, GetFullPath совпадает.")
        result["status"] = "passed" if passed else "partial"
        code = 0
    except (ConnectionError, BrokenPipeError, EOFError, OSError) as exc:
        transport_unknown = True
        result["status"] = "blocked"
        result["limitations"].append(f"API/ввод-вывод: исход последнего вызова неизвестен; новых записей и закрытия документа нет: {exc}")
        traceback.print_exc()
    except Exception as exc:
        result["limitations"].append(f"Ошибка выполнения: {type(exc).__name__}: {exc}")
        traceback.print_exc()
    finally:
        if doc is not None and not transport_unknown:
            try:
                require(doc.Close(c.kdDoNotSaveChanges), "Close own document")
                result["checks"].append("Собственный документ закрыт; чужие документы не изменялись и не закрывались.")
                if previous:
                    previous.SetActive()
            except Exception as exc:
                result["limitations"].append(f"Закрытие собственного документа не подтверждено: {exc}")
                result["status"] = "blocked"
                code = 1
        (ROOT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        log(json.dumps(result, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
