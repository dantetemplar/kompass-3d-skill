# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""SOLIDWORKS 1.11: native KOMPAS plate and central trapezoidal stiffener."""
from contextlib import contextmanager
import json
import math
from pathlib import Path
import tempfile

import ksapi
from constants import constants as c
from constants3d import constants as c3d

ROOT = Path(__file__).resolve().parent
CHECKS = []
LIMITATIONS = [
    "Центры отверстий приняты симметричными относительно начала координат и на средней линии пластины, как показано на видах; отдельных размеров смещения до кромок нет.",
    "Высота ребра у пластины совпадает с высотой пластины; вылет ребра 45 мм получен из общего размера 55 минус толщина пластины 10 мм.",
    "Пробные изменения размеров и повторное открытие сохранённой модели не выполнялись.",
]
TREE = "Пластина 125×55, 2×Ø15 → выдавливание 10 → трапециевидное ребро 45×(55/15) → симметричное выдавливание 20"


def need(value, message):
    if not value:
        raise RuntimeError(message)
    return value


def log(stage, **values):
    print(json.dumps({"stage": stage, **values}, ensure_ascii=False), flush=True)


def relation(obj, kind, partners=(), index=None, partner_index=None, name=None, value=None):
    item = need(obj.NewConstraint(), "NewConstraint")
    item.SetConstraintType(kind)
    if partners:
        item.SetPartners(list(partners))
    if index is not None:
        item.SetIndex(index)
    if partner_index is not None:
        item.SetPartnerIndex(partner_index)
    if name:
        item.SetVariable(name)
    if value is not None:
        item.SetConstraintValue(value)
    need(item.Create() and item.IsValid(), f"Constraint {kind}, {name}")
    return item


def dimension(symbols, a, b, orientation, name, value):
    dim = need(symbols.GetLineDimensions().Add(), "Line dimension")
    (obj1, index1, x1, y1), (obj2, index2, x2, y2) = a, b
    dim.SetX1(x1)
    dim.SetY1(y1)
    dim.SetX2(x2)
    dim.SetY2(y2)
    dim.SetX3((x1 + x2) / 2 + 8)
    dim.SetY3((y1 + y2) / 2 - 8)
    dim.SetOrientation(orientation)
    need(dim.Update(), f"Dimension {name}")
    need(dim.Associate(), f"Dimension association {name}")
    # The side sketch may associate its origin witness to the native sketch
    # origin instead of the coincident auxiliary origin point. The solver's
    # final fully-constrained state is checked after EndEdit.
    relations = dim.GetConstraints()
    need(any(r.IsValid() and r.GetConstraintType() == c.ksCMergePoints
             for r in relations), f"Dimension witness association {name}")
    relation(dim, c.ksCFixedDim)
    relation(dim, c.ksCDimWithVariable, name=name, value=value)
    return dim


def point(drawing, x, y):
    p = need(drawing.GetPoints().Add(), "Point")
    p.SetX(x)
    p.SetY(y)
    need(p.Update(), "Point Update")
    return p


def contour(drawing, vertices):
    lines = []
    for a, b in zip(vertices, vertices[1:] + vertices[:1]):
        line = need(drawing.GetLineSegments().Add(), "Segment")
        line.SetX1(a[0])
        line.SetY1(a[1])
        line.SetX2(b[0])
        line.SetY2(b[1])
        need(line.Update(), "Segment Update")
        lines.append(line)
    for i, line in enumerate(lines):
        relation(line, c.ksCMergePoints, [lines[(i + 1) % len(lines)]], 1, 0)
        a, b = vertices[i], vertices[(i + 1) % len(vertices)]
        if abs(a[1] - b[1]) < 1e-8:
            relation(line, c.ksCHorizontal)
        elif abs(a[0] - b[0]) < 1e-8:
            relation(line, c.ksCVertical)
    return lines


def witness(obj, index, xy):
    return obj, index, xy[0], xy[1]


@contextmanager
def edit(sketch):
    fragment = need(sketch.BeginEdit(False), "BeginEdit")
    try:
        fragment.SetParametricMode(True)
        need(fragment.IsParametricMode(), "Parametric mode")
        view = need(fragment.GetViewsAndLayersManager().GetViews().GetActiveView(), "View")
        yield ksapi.IDrawingContainer(view), ksapi.ISymbols2DContainer(view)
    finally:
        need(sketch.EndEdit(), "EndEdit")
    state = sketch.GetConstraintsState()
    log("sketch", name=sketch.GetName(), constraint_state=state)
    need(state == c.ksStateWellConstrained, f"Sketch not fully defined: {state}")
    CHECKS.append(f"Эскиз «{sketch.GetName()}»: полностью определён нативными связями и управляющими размерами (state={state}); фиксирована только точка начала координат.")


def sketch(part, model, plane, name):
    sk = need(model.GetSketchs().Add(), "Sketch")
    sk.SetName(name)
    sk.SetPlane(need(part.GetDefaultObject(plane), "Base plane"))
    need(sk.Update(), "Sketch Update")
    return sk


def expressions(sk, mapping):
    feature = ksapi.IFeature(sk)
    for name, expression in mapping.items():
        var = need(feature.GetVariableByName(False, True, name), f"Variable {name}")
        need(not var.IsInformation() and not var.IsReadOnly(), f"Driving variable {name}")
        var.SetExpression(expression)
        log("expression", name=name, expression=var.GetExpression())


def extrude(model, sk, name, depth, symmetric=False):
    op = need(model.GetExtrusions().Add(c3d.o3d_bossExtrusion), "Extrusion")
    op.SetName(name)
    op.SetProfiles([sk])
    op.SetDirection(c3d.dtBoth if symmetric else c3d.dtNormal)
    need(op.SetSideParameters(True, c3d.etBlind, depth / 2 if symmetric else depth, 0., False, None), "Forward depth")
    if symmetric:
        need(op.SetSideParameters(False, c3d.etBlind, depth / 2, 0., False, None), "Reverse depth")
    need(op.Update(), f"Extrusion Update: {name}")
    return op


def build(part, model):
    plate = sketch(part, model, c3d.o3d_planeXOY, "Пластина и симметричные отверстия")
    with edit(plate) as (drawing, symbols):
        origin = point(drawing, 0., 0.)
        relation(origin, c.ksCFixedPoint, index=0)
        vertices = [(-62.5, -27.5), (62.5, -27.5), (62.5, 27.5), (-62.5, 27.5)]
        lines = contour(drawing, vertices)
        dimension(symbols, witness(lines[0], 0, vertices[0]), witness(lines[0], 1, vertices[1]), c.ksLinDHorizontal, "p111_plate_width", 125.)
        dimension(symbols, witness(lines[1], 0, vertices[1]), witness(lines[1], 1, vertices[2]), c.ksLinDVertical, "p111_plate_height", 55.)
        dimension(symbols, witness(origin, 0, (0, 0)), witness(lines[0], 0, vertices[0]), c.ksLinDHorizontal, "p111_half_width", 62.5)
        dimension(symbols, witness(origin, 0, (0, 0)), witness(lines[0], 0, vertices[0]), c.ksLinDVertical, "p111_half_height", 27.5)
        holes = []
        for i, x in enumerate((-37.5, 37.5)):
            hole = need(drawing.GetCircles().Add(), "Circle")
            hole.SetXc(x)
            hole.SetYc(0.)
            hole.SetRadius(7.5)
            need(hole.Update(), "Circle Update")
            relation(hole, c.ksCHAlignPoints, [origin], 0, 0)
            dimension(symbols, witness(origin, 0, (0, 0)), witness(hole, 0, (x, 0)), c.ksLinDHorizontal, f"p111_hole_offset_{i}", 37.5)
            holes.append(hole)
        relation(holes[1], c.ksCEqualRadius, [holes[0]])
        radial = need(symbols.GetRadialDimensions().Add(), "Radius dimension")
        radial.SetBaseObject(holes[0])
        radial.SetXc(-37.5)
        radial.SetYc(0.)
        radial.SetRadius(7.5)
        radial.SetAngle(35.)
        need(radial.Update(), "Radius Update")
        relation(radial, c.ksCFixedDim)
        relation(radial, c.ksCDimWithVariable, name="p111_hole_radius", value=7.5)
    expressions(plate, {"p111_half_width": "p111_plate_width/2", "p111_half_height": "p111_plate_height/2", "p111_hole_offset_1": "p111_hole_offset_0"})
    extrude(model, plate, "Пластина толщиной 10 мм", 10.)

    rib = sketch(part, model, c3d.o3d_planeYOZ, "Боковой профиль центрального ребра")
    samples = [rib.GetPoint3D(u, v, 0., 0., 0.) for u, v in [(0., 0.), (1., 0.), (0., 1.)]]
    need(all(s[0] for s in samples), "Sketch coordinate conversion")
    o, pu, pv = [tuple(s[1:]) for s in samples]
    u = tuple(pu[i] - o[i] for i in range(3))
    v = tuple(pv[i] - o[i] for i in range(3))
    log("rib-plane", origin=o, u=u, v=v)
    def project(y, z):
        w = (-o[0], y - o[1], z - o[2])
        return sum(w[i] * u[i] for i in range(3)), sum(w[i] * v[i] for i in range(3))
    # Split the straight root edge at the document origin. This provides an
    # unambiguous contour endpoint anchor, rather than a loose point on an edge.
    vertices = [project(0., 0.), project(-27.5, 0.), project(-27.5, -45.), project(-12.5, -45.), project(27.5, 0.)]
    y_orientation = c.ksLinDHorizontal if abs(u[1]) > .9 else c.ksLinDVertical
    z_orientation = c.ksLinDHorizontal if abs(u[2]) > .9 else c.ksLinDVertical
    with edit(rib) as (drawing, symbols):
        lines = contour(drawing, vertices)
        relation(lines[0], c.ksCFixedPoint, index=0)
        dimension(symbols, witness(lines[0], 0, vertices[0]), witness(lines[0], 1, vertices[1]), y_orientation, "p111_rib_half_height", 27.5)
        dimension(symbols, witness(lines[1], 0, vertices[1]), witness(lines[1], 1, vertices[2]), z_orientation, "p111_rib_projection", 45.)
        dimension(symbols, witness(lines[2], 0, vertices[2]), witness(lines[2], 1, vertices[3]), y_orientation, "p111_rib_tip_height", 15.)
        dimension(symbols, witness(lines[0], 1, vertices[1]), witness(lines[4], 0, vertices[4]), y_orientation, "p111_rib_root_height", 55.)
    expressions(rib, {"p111_rib_half_height": "p111_plate_height/2", "p111_rib_root_height": "p111_plate_height"})
    extrude(model, rib, "Центральное ребро толщиной 20 мм", 20., symmetric=True)
    return plate, rib


def inspect_tree(part):
    errors, seen = [], set()
    def visit(feature):
        if feature.reference in seen:
            return
        seen.add(feature.reference)
        error = feature.GetObjectError()
        if error:
            errors.append([feature.GetName(), error])
        for child in feature.GetSubFeatures(c.ksOperTree, True, True):
            if child:
                visit(child)
    visit(ksapi.IFeature(part))
    need(not errors, f"Feature errors: {errors}")
    CHECKS.append("Обход дерева операций: ошибок построения нет.")


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    attempt = Path(tempfile.mkdtemp(prefix="attempt-", dir=ROOT))
    output = attempt / "model.m3d"
    result = {"task": "1.11", "status": "failed", "title": "Кронштейн с центральным ребром", "script": "solution.py", "model": None, "volume_mm3": None, "reference_volume": 96716, "reference_units": "mm3", "volume_passed": None, "checks": CHECKS, "limitations": LIMITATIONS, "tree": TREE}
    doc = None
    unknown = False
    exit_code = 1
    try:
        need(not output.exists(), "Model path already exists")
        app = need(ksapi.GetKompas(), "No existing API session; not launching CAD")
        doc = need(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart, True), "Own new document")
        doc3d = need(ksapi.IKompasDocument3D(doc), "3D document")
        part = need(doc3d.GetTopPart(), "Top part")
        part.SetName("1.11 — Кронштейн с центральным ребром")
        sketches = build(part, need(part.GetModelContainer(), "Model container"))
        need(doc3d.CompleteRebuildDocument(), "Complete rebuild")
        need(part.RebuildModel(True), "Rebuild model")
        for sk in sketches:
            need(sk.GetConstraintsState() == c.ksStateWellConstrained, "Sketch state after rebuild")
        inspect_tree(part)
        bodies = ksapi.IFeature(part).GetResultBodies()
        need(len(bodies) == 1 and bodies[0].IsSolid(), "One native solid")
        CHECKS.append("Итоговый B-rep содержит ровно одно твёрдое тело.")
        mass = need(ksapi.IMassInertiaParam(part), "Mass inertia interface")
        mass.SetLengthUnits(c.ksLUnMM)
        units = mass.GetLengthUnits()
        need(units == c.ksLUnMM, f"Length units readback {units}")
        need(mass.Calculate(), "Native mass properties calculation")
        volume = mass.GetVolume()
        need(math.isfinite(volume) and volume > 0, "Native volume")
        result["volume_mm3"] = volume
        result["volume_passed"] = 96715.5 <= volume < 96716.5
        CHECKS.append(f"IMassInertiaParam: GetLengthUnits={units} (ksLUnMM), Calculate успешно, объём={volume:.9f} мм³.")
        CHECKS.append(f"Сравнение с интервалом [96715.5,96716.5) мм³: {result['volume_passed']}.")
        need(not output.exists(), "Refuse model overwrite")
        need(doc.SaveAs(str(output)), "SaveAs")
        need(output.is_file() and output.stat().st_size > 0, "Nonempty native file")
        result["model"] = str(output.relative_to(ROOT))
        CHECKS.append("SaveAs нового model.m3d успешно; файл существует и непустой.")
        result["status"] = "passed" if result["volume_passed"] else "partial"
        exit_code = 0
    except (ConnectionError, BrokenPipeError, EOFError) as exc:
        unknown = True
        result["status"] = "blocked"
        LIMITATIONS.append(f"Потеря API, исход последнего вызова неизвестен; дальнейшая запись прекращена: {exc}")
    except Exception as exc:
        LIMITATIONS.append(f"Ошибка выполнения: {type(exc).__name__}: {exc}")
        log("error", error=repr(exc))
        if doc is not None:
            try:
                if not output.exists() and doc.SaveAs(str(output)) and output.is_file():
                    result["model"] = str(output.relative_to(ROOT))
                    result["status"] = "partial"
                    CHECKS.append("Промежуточная собственная модель сохранена после ошибки.")
            except (ConnectionError, BrokenPipeError, EOFError):
                unknown = True
                result["status"] = "blocked"
    finally:
        if doc is not None and not unknown:
            try:
                need(doc.Close(c.kdDoNotSaveChanges), "Close own document")
                CHECKS.append("Собственный документ закрыт в finally; чужие документы не изменялись и не закрывались.")
            except Exception as exc:
                LIMITATIONS.append(f"Не удалось подтвердить закрытие собственного документа: {exc}")
                result["status"] = "blocked"
                exit_code = 1
        (attempt / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        (ROOT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        log("result", **result)
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
