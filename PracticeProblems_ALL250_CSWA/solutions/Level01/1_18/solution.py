# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Practice Problem 1.18: native, dimension-driven KOMPAS-3D part.

Origin: hole centre at the rail-top/plate-bottom plane.
XY: plate [-50,50]^2; rails X=-58..97, Y=-58..-26 and 26..58.
Z: rails -20..0; perforated plate and end stops 0..10.
No imports from the skill, no export, reopen, or dimensional perturbation.
"""
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
TREE = "Эскиз квадратной плиты с Ø45 → выдавливание 10; эскиз двух направляющих → выдавливание вниз 20; эскиз концевых выступов → выдавливание 10"


def require(value, message):
    if not value:
        raise RuntimeError(message)
    return value


def evidence(message, **data):
    print(json.dumps({"stage": message, **data}, ensure_ascii=False), flush=True)


def relation(obj, kind, partner=None, index=None, partner_index=None,
             name=None, value=None, expression=None):
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


def driving(dim, name, value, expression=None):
    relation(dim, c.ksCFixedDim)
    relation(dim, c.ksCDimWithVariable, name=name, value=value, expression=expression)


def linear(symbols, a, b, orientation, name, value, expression=None):
    """Witness = (native object, point index, XY), verified after Associate."""
    dim = require(symbols.GetLineDimensions().Add(), "Line dimension")
    p, q = a[2], b[2]
    dim.SetX1(p[0])
    dim.SetY1(p[1])
    dim.SetX2(q[0])
    dim.SetY2(q[1])
    dim.SetX3((p[0] + q[0]) / 2 + (12 if orientation == c.ksLinDVertical else 0))
    dim.SetY3((p[1] + q[1]) / 2 - (12 if orientation == c.ksLinDHorizontal else 0))
    dim.SetOrientation(orientation)
    require(dim.Update(), f"Dimension {name}")
    require(dim.Associate(), f"Associate {name}")
    links = dim.GetConstraints()
    for i, (obj, idx, _) in enumerate((a, b)):
        require(any(x.IsValid() and x.GetConstraintType() == c.ksCMergePoints
                    and x.GetIndex() == i and x.GetPartnerIndex() == idx
                    and any(p.GetId() == obj.GetId() for p in x.GetPartners())
                    for x in links), f"Dimension witness {name}/{i}")
    driving(dim, name, value, expression)
    return dim


def segment(drawing, a, b):
    obj = require(drawing.GetLineSegments().Add(), "Line")
    obj.SetX1(a[0])
    obj.SetY1(a[1])
    obj.SetX2(b[0])
    obj.SetY2(b[1])
    require(obj.Update(), "Line Update")
    return obj


def rectangle(drawing, x, y, width, height):
    points = [(x, y), (x + width, y), (x + width, y + height), (x, y + height)]
    edges = [segment(drawing, a, b) for a, b in zip(points, points[1:] + points[:1])]
    for i, edge in enumerate(edges):
        relation(edge, c.ksCMergePoints, edges[(i + 1) % 4], 1, 0)
        relation(edge, c.ksCHorizontal if i % 2 == 0 else c.ksCVertical)
    return edges, points


def vertex(rect, i):
    return rect[0][i], 0, rect[1][i]


def origin(drawing):
    point = require(drawing.GetPoints().Add(), "Origin point")
    point.SetX(0.)
    point.SetY(0.)
    require(point.Update(), "Origin Update")
    relation(point, c.ksCFixedPoint, index=0)
    return point, 0, (0., 0.)


@contextmanager
def sketch(part, model, name, checks):
    obj = require(model.GetSketchs().Add(), "Sketch")
    obj.SetName(name)
    obj.SetPlane(require(part.GetDefaultObject(c3d.o3d_planeXOY), "XOY"))
    require(obj.Update(), "Sketch Update")
    fragment = require(obj.BeginEdit(False), "BeginEdit")
    try:
        fragment.SetParametricMode(True)
        require(fragment.IsParametricMode(), "Parametric sketch mode")
        view = require(fragment.GetViewsAndLayersManager().GetViews().GetActiveView(), "View")
        yield obj, require(ksapi.IDrawingContainer(view), "Drawing"), require(ksapi.ISymbols2DContainer(view), "Symbols")
    finally:
        require(obj.EndEdit(), "EndEdit")
    state = obj.GetConstraintsState()
    evidence("sketch", name=name, constraint_state=state)
    require(state == c.ksStateWellConstrained, f"Under/overconstrained {name}: {state}")
    checks.append(f"{name}: полностью определён, GetConstraintsState={state}; связи совпадения и H/V, управляющие размеры; зафиксирована только базовая точка.")


def extrude(model, profile, name, depth, reverse=False):
    op = require(model.GetExtrusions().Add(c3d.o3d_bossExtrusion), "Boss extrusion")
    op.SetName(name)
    op.SetProfiles([profile])
    op.SetDirection(c3d.dtReverse if reverse else c3d.dtNormal)
    require(op.SetSideParameters(not reverse, c3d.etBlind, depth, 0., False, None), "Extrusion depth")
    evidence("extruding", name=name)
    require(op.Update(), f"Extrusion Update: {name}")
    return op


def build(part, model, checks):
    with sketch(part, model, "01 Квадратная плита 100 и отверстие Ø45", checks) as (plate, drawing, symbols):
        hole = require(drawing.GetCircles().Add(), "Circle")
        hole.SetXc(0.)
        hole.SetYc(0.)
        hole.SetRadius(22.5)
        require(hole.Update(), "Circle Update")
        relation(hole, c.ksCFixedPoint, index=0)
        datum = (hole, 0, (0., 0.))
        rect = rectangle(drawing, -50., -50., 100., 100.)
        linear(symbols, vertex(rect, 0), vertex(rect, 1), c.ksLinDHorizontal, "plate_size", 100.)
        relation(rect[0][1], c.ksCEqualLength, rect[0][0])
        linear(symbols, vertex(rect, 0), datum, c.ksLinDHorizontal, "plate_half_x", 50., "plate_size/2")
        linear(symbols, vertex(rect, 0), datum, c.ksLinDVertical, "plate_half_y", 50., "plate_size/2")
        dim = require(symbols.GetRadialDimensions().Add(), "Radial dimension")
        dim.SetBaseObject(hole)
        dim.SetXc(0.)
        dim.SetYc(0.)
        dim.SetRadius(22.5)
        dim.SetAngle(35.)
        require(dim.Update(), "Radius Update")
        require(any(x.IsValid() and x.GetConstraintType() == c.ksCAssociation for x in dim.GetConstraints()), "Radius association")
        driving(dim, "hole_radius", 22.5)
    extrude(model, plate, "02 Плита толщиной 10", 10.)

    with sketch(part, model, "03 Две направляющие 155×32, отступ 8", checks) as (rails, drawing, symbols):
        datum = origin(drawing)
        lower = rectangle(drawing, -58., -58., 155., 32.)
        upper = rectangle(drawing, -58., 26., 155., 32.)
        linear(symbols, vertex(lower, 0), vertex(lower, 1), c.ksLinDHorizontal, "rail_length", 155.)
        linear(symbols, vertex(lower, 1), vertex(lower, 2), c.ksLinDVertical, "rail_width", 32.)
        linear(symbols, vertex(lower, 0), datum, c.ksLinDHorizontal, "rail_left", 58., "50+8")
        linear(symbols, vertex(lower, 0), datum, c.ksLinDVertical, "rail_outer", 58., "50+8")
        relation(upper[0][0], c.ksCEqualLength, lower[0][0])
        relation(upper[0][1], c.ksCEqualLength, lower[0][1])
        relation(upper[0][0], c.ksCVAlignPoints, lower[0][0], 0, 0)
        linear(symbols, datum, vertex(upper, 0), c.ksLinDVertical, "rail_inner", 26., "rail_outer-rail_width")
    extrude(model, rails, "04 Направляющие вниз на 20", 20., reverse=True)

    with sketch(part, model, "05 Два концевых выступа 20×32", checks) as (stops, drawing, symbols):
        datum = origin(drawing)
        lower = rectangle(drawing, 77., -58., 20., 32.)
        upper = rectangle(drawing, 77., 26., 20., 32.)
        linear(symbols, vertex(lower, 0), vertex(lower, 1), c.ksLinDHorizontal, "stop_length", 20.)
        linear(symbols, vertex(lower, 1), vertex(lower, 2), c.ksLinDVertical, "stop_width", 32.)
        linear(symbols, datum, vertex(lower, 1), c.ksLinDHorizontal, "rail_end", 97., "155-50-8")
        linear(symbols, vertex(lower, 0), datum, c.ksLinDVertical, "stop_outer", 58., "50+8")
        relation(upper[0][0], c.ksCEqualLength, lower[0][0])
        relation(upper[0][1], c.ksCEqualLength, lower[0][1])
        relation(upper[0][0], c.ksCVAlignPoints, lower[0][0], 0, 0)
        linear(symbols, datum, vertex(upper, 0), c.ksLinDVertical, "stop_inner", 26., "stop_outer-stop_width")
    extrude(model, stops, "06 Концевые выступы высотой 10", 10.)


def validate(part, checks):
    require(part.RebuildModel(True), "Part rebuild")
    root = require(ksapi.IFeature(part), "Root feature")
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

    visit(root)
    require(not errors, f"Feature errors: {errors}")
    checks.append("Перестроение успешно; во всех ветвях нативного дерева GetObjectError=0.")
    bodies = root.GetResultBodies()
    require(len(bodies) == 1 and bodies[0].IsSolid(), "One connected solid")
    checks.append("Результат — одно твёрдое тело.")
    mass = require(ksapi.IMassInertiaParam(part), "Mass properties")
    mass.SetLengthUnits(c.ksLUnMM)
    units = mass.GetLengthUnits()
    require(units == 1, f"Mass length units {units}, expected 1")
    require(mass.Calculate() and mass.IsActual(), "Actual mass calculation")
    volume = mass.GetVolume()
    require(math.isfinite(volume) and volume > 0, f"Invalid volume {volume}")
    checks.append("МЦХ: SetLengthUnits(c.ksLUnMM), GetLengthUnits=1; Calculate=True, IsActual=True.")
    passed = 295295.5 <= volume < 295296.5
    checks.append(f"Объём {volume:.12f} мм³; интервал эталона [295295.5, 295296.5): {passed}.")
    return volume, passed


def main():
    attempt = Path(tempfile.mkdtemp(prefix="attempt-", dir=ROOT))
    output = attempt / "model.m3d"
    require(not output.exists() and not output.is_symlink(), "New model path")
    result = {
        "task": "1.18", "status": "failed", "title": "SOLIDWORKS Practice Problem 1.18",
        "script": "solution.py", "model": None, "volume_mm3": None,
        "reference_volume": 295296, "reference_units": "mm3", "volume_passed": False,
        "checks": [], "limitations": [
            "Размеры разных эскизов заданы локально; сквозная межэскизная зависимость размеров не создавалась.",
            "Изменение размеров и повторное открытие не выполнялись по условию; превью и экспорт не создавались."
        ], "tree": TREE,
    }
    doc = None
    try:
        app = ksapi.GetKompas()
        if not app:
            result["status"] = "blocked"
            raise RuntimeError("Нет запущенной API-сессии КОМПАС; запуск и перезапуск запрещены.")
        doc = require(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart, True), "Own new document")
        require(doc.GetDocumentType() == c.ksDocumentPart, "Part document type")
        part = require(ksapi.IKompasDocument3D(doc).GetTopPart(), "Top part")
        part.SetName("Practice Problem 1.18 — плита на двух направляющих")
        model = require(part.GetModelContainer(), "Model container")
        build(part, model, result["checks"])
        volume, passed = validate(part, result["checks"])
        result["volume_mm3"] = volume
        result["volume_passed"] = passed
        require(not output.exists() and not output.is_symlink(), "SaveAs path must not exist")
        evidence("saving", model=str(output), volume_mm3=volume, volume_passed=passed)
        require(doc.SaveAs(str(output)), "SaveAs")
        require(output.is_file() and output.stat().st_size > 0, "Nonempty native file")
        require(Path(doc.GetFullPath()).resolve() == output.resolve(), "Saved document path")
        result["model"] = str(output.relative_to(ROOT))
        result["checks"].append("SaveAs в ранее не существовавший attempt-*/model.m3d успешен; непустой файл и GetFullPath подтверждены.")
        result["status"] = "passed" if passed else "partial"
    except Exception as exc:
        result["limitations"].append(f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
    finally:
        if doc is not None:
            try:
                require(doc.Close(c.kdDoNotSaveChanges), "Close own document")
                result["checks"].append("Собственный документ закрыт в finally; чужие документы не редактировались и не закрывались.")
            except Exception as exc:
                result["status"] = "partial" if result["model"] else "failed"
                result["limitations"].append(f"Закрытие собственного документа: {exc}")
        (ROOT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    evidence("result", **result)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
