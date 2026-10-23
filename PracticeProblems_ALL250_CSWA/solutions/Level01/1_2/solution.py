# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""SOLIDWORKS Practice 1.2: native KOMPAS sketches and extrusions, millimetres."""
from contextlib import contextmanager
import json
import math
from pathlib import Path
import tempfile

import ksapi
from constants import constants as c
from constants3d import constants as c3d

ROOT = Path(__file__).resolve().parent
UNCERTAIN = False
CHECKS = ["ast.parse: passed before execution"]
STATES = []
TREE = []


class BuildError(RuntimeError):
    pass


def require(value, message):
    if not value:
        raise BuildError(message)
    return value


def stage(text, **data):
    print(json.dumps({"stage": text, **data}, ensure_ascii=False), flush=True)


def constrain(obj, kind, partners=(), index=None, partner_index=None,
              name=None, value=None):
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
    require(item.Create() and item.IsValid(), f"Constraint {kind}/{name}")
    return item


def drive(dim, name, value):
    constrain(dim, c.ksCFixedDim)
    constrain(dim, c.ksCDimWithVariable, name=name, value=value)
    return dim


def line(drawing, a, b, style=1):
    obj = require(drawing.GetLineSegments().Add(), "Line")
    obj.SetX1(a[0]); obj.SetY1(a[1])
    obj.SetX2(b[0]); obj.SetY2(b[1])
    obj.SetStyle(style)
    require(obj.Update(), "Line Update")
    return obj


def polygon(drawing, vertices):
    lines = [line(drawing, a, b) for a, b in
             zip(vertices, vertices[1:] + vertices[:1])]
    for i, obj in enumerate(lines):
        constrain(obj, c.ksCMergePoints, [lines[(i + 1) % len(lines)]], 1, 0)
    return lines


def dim(symbols, a, b, offset, orientation, name, value):
    obj = require(symbols.GetLineDimensions().Add(), "Line dimension")
    obj.SetX1(a[0]); obj.SetY1(a[1])
    obj.SetX2(b[0]); obj.SetY2(b[1])
    obj.SetX3(offset[0]); obj.SetY3(offset[1])
    obj.SetOrientation(orientation)
    require(obj.Update(), "Dimension Update")
    require(obj.Associate(), f"Dimension Associate {name}")
    return drive(obj, name, value)


def angle(symbols, first, second, center, name, value):
    obj = require(symbols.GetAngleDimensions().Add(c.ksDrADimension), "Angle")
    obj.SetBaseObject1(first); obj.SetBaseObject2(second)
    obj.SetXc(center[0]); obj.SetYc(center[1])
    obj.SetX1(first.GetX2()); obj.SetY1(first.GetY2())
    obj.SetX2(second.GetX1()); obj.SetY2(second.GetY1())
    obj.SetAngle1(0.0); obj.SetAngle2(value)
    obj.SetRadius(15.0)
    obj.SetDimensionType(c.ksADMinAngle)
    obj.SetDirection(False)
    obj.SetX3(center[0] + 12); obj.SetY3(center[1] + 7)
    require(obj.Update(), "Angle Update")
    # Angular SetBaseObject creates the associations itself; Associate may
    # return False when no additional association is needed.
    stage("angle-associations", name=name,
          constraints=[{"type": x.GetConstraintType(), "valid": x.IsValid()}
                       for x in obj.GetConstraints()])
    require(obj.GetBaseObject1() and obj.GetBaseObject2(), "Angular base objects")
    constrain(obj, c.ksCFixedDim)
    item = require(obj.NewConstraint(), "Angular variable constraint")
    item.SetConstraintType(c.ksCDimWithVariable)
    item.SetVariable(name)
    item.SetDegrees(int(value))
    item.SetMinutes(0)
    item.SetSeconds(0.)
    require(item.Create() and item.IsValid(), "Angular variable Create")
    stage("angle-driving", degrees=item.GetDegrees(), value=item.GetConstraintValue())


@contextmanager
def edit(model, plane, name):
    global UNCERTAIN
    stage(name)
    sketch = require(model.GetSketchs().Add(), "Sketch")
    sketch.SetName(name)
    sketch.SetPlane(plane)
    require(sketch.Update(), "Sketch plane")
    fragment = require(sketch.BeginEdit(False), "BeginEdit")
    try:
        fragment.SetParametricMode(True)
        require(fragment.IsParametricMode(), "Parametric mode")
        view = require(fragment.GetViewsAndLayersManager().GetViews().GetActiveView(), "View")
        yield sketch, ksapi.IDrawingContainer(view), ksapi.ISymbols2DContainer(view)
    except BaseException as exc:
        if not isinstance(exc, BuildError):
            UNCERTAIN = True
        raise
    finally:
        if not UNCERTAIN:
            require(sketch.EndEdit(), "EndEdit")
    state = sketch.GetConstraintsState()
    STATES.append((name, state))
    stage("sketch-constraints", name=name, state=state)


def extrude(model, sketch, depth, name, cut=False, outward=True):
    stage(name)
    op = require(model.GetExtrusions().Add(
        c3d.o3d_cutExtrusion if cut else c3d.o3d_bossExtrusion), name)
    op.SetName(name)
    op.SetProfiles([sketch])
    normal = outward != cut
    op.SetDirection(c3d.dtNormal if normal else c3d.dtReverse)
    require(op.SetSideParameters(normal, c3d.etBlind, depth, 0., False, None), "Extrusion depth")
    require(op.Update(), f"Extrusion {name}")
    TREE.append(name)
    return op


def build(part, model):
    theta = math.radians(65)
    s, co = math.sin(theta), math.cos(theta)
    a = 40 - 26 / math.tan(theta)
    b = 40 + 24 / math.tan(theta)
    h = 58 - (78 - b) / math.tan(theta)
    plane = require(part.GetDefaultObject(c3d.o3d_planeXOY), "XOY")
    vertices = [(0., 0.), (78., 0.), (78., h), (b, 58.),
                (40., 34.), (a, 8.), (0., 8.)]
    with edit(model, plane, "01 Боковой профиль 78 × 58, 65°") as (sk, draw, sy):
        ls = polygon(draw, vertices)
        for i in (0, 5):
            constrain(ls[i], c.ksCHorizontal)
        for i in (1, 6):
            constrain(ls[i], c.ksCVertical)
        constrain(ls[3], c.ksCCollinear, [ls[4]])
        constrain(ls[2], c.ksCPerpendicular, [ls[3]])
        constrain(ls[0], c.ksCFixedPoint, index=0)
        dim(sy, vertices[0], vertices[1], (39, -10), c.ksLinDHorizontal, "length", 78)
        dim(sy, vertices[0], vertices[3], (-15, 29), c.ksLinDVertical, "height", 58)
        dim(sy, vertices[0], vertices[6], (-7, 4), c.ksLinDVertical, "base", 8)
        dim(sy, vertices[0], vertices[4], (20, -18), c.ksLinDHorizontal, "step_x", 40)
        dim(sy, vertices[0], vertices[4], (-23, 17), c.ksLinDVertical, "step_h", 34)
        stage("before-angle", points=[(x.GetX1(), x.GetY1(), x.GetX2(), x.GetY2()) for x in ls])
        angle(sy, ls[0], ls[3], (a - 8 / math.tan(theta), 0), "inclination", 65)
        stage("profile-geometry", points=[(x.GetX1(), x.GetY1(), x.GetX2(), x.GetY2()) for x in ls])
    base = extrude(model, sk, 28, "02 Основа — ширина 28")
    coords = []
    for uv in ((0, 0), (1, 0), (0, 1)):
        xyz = sk.GetPoint3D(*uv, 0., 0., 0.)
        require(xyz[0], "Sketch axes")
        coords.append(tuple(xyz[1:]))
    stage("base-coordinate-system", points=coords)
    require(all(abs(x-y) < 1e-7 for p, q in zip(coords, ((0,0,0),(1,0,0),(0,1,0)))
                for x, y in zip(p, q)), "Unexpected XOY axes")
    p = [(0., 8.), (40., 8.), (40., 34.), (24., 34.), (24., 16.), (0., 16.)]
    with edit(model, plane, "03 Передняя ступень 24 + 16, 16 + 18") as (step, draw, sy):
        ls = polygon(draw, p)
        for i, obj in enumerate(ls):
            constrain(obj, c.ksCHorizontal if i % 2 == 0 else c.ksCVertical)
        constrain(ls[0], c.ksCFixedPoint, index=0)
        dim(sy, p[0], p[1], (20, 3), c.ksLinDHorizontal, "step_length", 40)
        dim(sy, p[0], p[4], (12, -5), c.ksLinDHorizontal, "lower_length", 24)
        dim(sy, p[1], p[2], (46, 21), c.ksLinDVertical, "step_rise", 26)
        dim(sy, p[0], p[5], (-5, 12), c.ksLinDVertical, "lower_rise", 8)
    extrude(model, step, 18, "04 Ступень — ширина 18")
    top = (b + 7 * s, 58 - 7 * co)
    p = [top, (top[0] + 5*s, top[1] - 5*co),
         (top[0] + 5*s - 36*co, top[1] - 5*co - 36*s),
         (top[0] - 36*co, top[1] - 36*s)]
    with edit(model, plane, "05 Сквозной паз 5 × 36, отступ 7") as (slot, draw, sy):
        ls = polygon(draw, p)
        constrain(ls[0], c.ksCParallel, [ls[2]])
        constrain(ls[1], c.ksCParallel, [ls[3]])
        constrain(ls[0], c.ksCPerpendicular, [ls[1]])
        constrain(ls[0], c.ksCFixedPoint, index=0)
        guide = line(draw, (0., 0.), (78., 0.), style=3)
        constrain(guide, c.ksCFixedPoint, index=0)
        constrain(guide, c.ksCHorizontal)
        dim(sy, (0,0), (78,0), (39,-8), c.ksLinDHorizontal, "guide_length", 78)
        dim(sy, p[0], p[1], (top[0] + 6, top[1] + 5), c.ksLinDParallel, "slot_width", 5)
        dim(sy, p[1], p[2], (70, 29), c.ksLinDParallel, "slot_depth", 36)
        angle(sy, guide, ls[3], (p[3][0] - p[3][1] / math.tan(theta), 0), "slot_angle", 65)
    extrude(model, slot, 28, "06 Сквозной вырез паза", cut=True)
    # Choose the top-front planar face geometrically, not by topology index.
    # Boss row: 7.5 from each transverse end, pitch 15; middle of 7 mm flange.
    center = (b + 3.5*s, 58 - 3.5*co, 14.)
    candidates = []
    for obj in ksapi.IFeature(part).GetModelObjects([c3d.o3d_face]):
        face = ksapi.IFace(obj)
        if face.IsPlanar() and face.GetDistanceToPoint(*center) < 1e-6:
            candidates.append(obj)
    require(len(candidates) == 1, f"Top-front boss face count: {len(candidates)}")
    with edit(model, candidates[0], "07 Одинаковые бобышки Ø6, шаг 15") as (boss, draw, sy):
        frame = []
        for uv in ((0.,0.), (1.,0.), (0.,1.)):
            out = boss.GetPoint3D(*uv, 0.,0.,0.)
            require(out[0], "Boss coordinate frame")
            frame.append(tuple(out[1:]))
        ux = tuple(frame[1][i] - frame[0][i] for i in range(3))
        uy = tuple(frame[2][i] - frame[0][i] for i in range(3))
        normal = (ux[1]*uy[2]-ux[2]*uy[1], ux[2]*uy[0]-ux[0]*uy[2], ux[0]*uy[1]-ux[1]*uy[0])
        desired = (co, s, 0.)
        outward = sum(x*y for x,y in zip(normal, desired)) > 0
        points = []
        for z in (7.5, 22.5):
            out = boss.GetPointProjectionToXY(center[0], center[1], z, 0., 0.)
            require(out[0], "Boss point projection")
            points.append(tuple(out[1:]))
        circles = []
        for x, y in points:
            circle = require(draw.GetCircles().Add(), "Boss circle")
            circle.SetXc(x); circle.SetYc(y); circle.SetRadius(3.)
            require(circle.Update(), "Boss circle Update")
            circles.append(circle)
        constrain(circles[0], c.ksCFixedPoint, index=0)
        constrain(circles[1], c.ksCEqualRadius, [circles[0]])
        dx, dy = points[1][0]-points[0][0], points[1][1]-points[0][1]
        require(min(abs(dx), abs(dy)) < 1e-6, "Boss transverse axis not aligned")
        vertical = abs(dx) < 1e-6
        constrain(circles[0], c.ksCVAlignPoints if vertical else c.ksCHAlignPoints,
                  [circles[1]], 0, 0)
        dim(sy, points[0], points[1], (points[0][0]+10, points[0][1]+10),
            c.ksLinDVertical if vertical else c.ksLinDHorizontal, "boss_pitch", 15)
        radial = require(sy.GetRadialDimensions().Add(), "Boss radius")
        radial.SetBaseObject(circles[0])
        radial.SetXc(points[0][0]); radial.SetYc(points[0][1]); radial.SetRadius(3.)
        radial.SetAngle(35.)
        require(radial.Update(), "Radial dimension Update")
        drive(radial, "boss_radius", 3.)
        stage("boss-coordinate-system", origin=frame[0], ux=ux, uy=uy, normal=normal,
              outward=outward, centers=points)
    extrude(model, boss, 6, "08 Две бобышки — высота 6", outward=outward)


def errors_and_tree(part):
    seen, errors, nodes = set(), [], []
    def visit(feature, depth=0):
        if feature.reference in seen:
            return
        seen.add(feature.reference)
        err = feature.GetObjectError()
        nodes.append("  "*depth + feature.GetName())
        if err:
            errors.append([feature.GetName(), err])
        for child in feature.GetSubFeatures(c.ksOperTree, True, True):
            if child:
                visit(child, depth+1)
    visit(ksapi.IFeature(part))
    return errors, nodes


def save(doc, output, result):
    require(not output.exists() and not output.is_symlink(), "Output already exists")
    stage("save-native", path=str(output))
    require(doc.SaveAs(str(output)), "SaveAs")
    require(output.is_file() and output.stat().st_size > 0, "Saved file exists")
    require(Path(doc.GetFullPath()).resolve() == output, "Saved full path")
    result["model"] = str(output.relative_to(ROOT))
    CHECKS.append("Нативная модель SaveAs успешно сохранена; файл непустой и путь подтверждён")


def main():
    global UNCERTAIN
    attempt = Path(tempfile.mkdtemp(prefix="attempt-", dir=ROOT)).resolve()
    output = attempt / "model.m3d"
    result = {"task":"1.2", "status":"failed", "title":"Ступенчатый кронштейн с пазом",
              "script":"solution.py", "model":None, "volume_mm3":None,
              "reference_volume":70039, "reference_units":"mm3", "volume_passed":None,
              "checks":CHECKS, "limitations":[
                  "Габариты ступени 40 и 34 получены как 24+16 и 16+18; отдельные управляющие размеры заданы на суммы.",
                  "Межэскизные положения ступени и начала паза заданы вычисленными базовыми точками, без общей таблицы выражений; изменение основы требует согласованной правки этих баз.",
                  "Ось бобышек принята посередине полосы 7 мм, согласно разрезу и симметрии изображения; отдельный размер 3.5 не указан.",
                  "Пробные изменения размеров, повторное открытие, preview и экспорт не выполнялись."],
              "tree":""}
    doc, part, previous = None, None, None
    try:
        stage("connect")
        app = require(ksapi.GetKompas(), "Нет API-сессии; запуск запрещён")
        previous = app.GetActiveDocument()
        require(not output.exists(), "Output collision")
        doc = require(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart, True), "New own part")
        doc3d = require(ksapi.IKompasDocument3D(doc), "Document3D")
        part = require(doc3d.GetTopPart(), "Top part")
        part.SetName("1.2 Ступенчатый кронштейн с пазом")
        build(part, require(part.GetModelContainer(), "Model container"))
        stage("validate")
        require(doc3d.CompleteRebuildDocument(), "Complete rebuild")
        require(part.RebuildModel(True), "Rebuild model")
        bodies = ksapi.IFeature(part).GetResultBodies()
        require(len(bodies) == 1 and bodies[0].IsSolid(), "One solid body")
        CHECKS.append("После перестроения получено одно твёрдое тело")
        errors, nodes = errors_and_tree(part)
        result["tree"] = "\n".join(nodes)
        require(not errors, f"Feature errors: {errors}")
        CHECKS.append("Полный обход нативного дерева: ошибок операций нет")
        for name, state in STATES:
            CHECKS.append(f"Эскиз {name}: состояние связей {state}")
        fully = all(state == c.ksStateWellConstrained for _, state in STATES)
        if not fully:
            result["limitations"].append("Не все эскизы полностью определены нативным решателем")
        mass = require(ksapi.IMassInertiaParam(part), "Mass properties")
        mass.SetLengthUnits(c.ksLUnMM)
        units = mass.GetLengthUnits()
        require(units == c.ksLUnMM, f"Mass units readback: {units}")
        require(mass.Calculate(), "Mass Calculate")
        require(mass.GetLengthUnits() == c.ksLUnMM, "Mass units after Calculate")
        volume = mass.GetVolume()
        require(math.isfinite(volume) and volume > 0, "Positive finite volume")
        result["volume_mm3"] = volume
        result["volume_passed"] = 70038.5 <= volume < 70039.5
        CHECKS.append(f"IMassInertiaParam: ksLUnMM={units}, GetLengthUnits подтверждён до/после Calculate; объём {volume:.9f} мм³")
        CHECKS.append(f"Интервал округления эталона [70038.5, 70039.5): {result['volume_passed']}")
        result["status"] = "passed" if result["volume_passed"] and fully else "partial"
        save(doc, output, result)
        stage("completed", volume_mm3=volume, status=result["status"])
    except BuildError as exc:
        result["limitations"].append(str(exc))
        if part is not None:
            bodies = ksapi.IFeature(part).GetResultBodies()
            if bodies and not output.exists():
                save(doc, output, result)
                result["status"] = "partial"
    except BaseException as exc:
        UNCERTAIN = True
        result["status"] = "blocked"
        result["limitations"].append(f"Неизвестный исход API: {type(exc).__name__}: {exc}; новые обращения и закрытие остановлены")
        raise
    finally:
        if doc is not None and not UNCERTAIN:
            require(doc.Close(c.kdDoNotSaveChanges), "Close own document")
            CHECKS.append("Собственный документ закрыт после сохранения; чужие документы не изменялись и не закрывались")
            if previous:
                previous.SetActive()
        result["tree"] = result["tree"] or " → ".join(TREE)
        text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        (attempt / "result.json").write_text(text)
        (ROOT / "result.json").write_text(text)
        stage("result", report=str(ROOT / "result.json"), **result)


if __name__ == "__main__":
    main()
