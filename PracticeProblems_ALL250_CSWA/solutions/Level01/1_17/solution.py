# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Practice Problem 1.17: native dimension-driven sketch and 10 mm extrusion."""
from __future__ import annotations

from contextlib import contextmanager
import json
import math
from pathlib import Path
import tempfile

import ksapi
from constants import constants as c
from constants3d import constants as c3d

ROOT = Path(__file__).resolve().parent


def require(value, message):
    if not value:
        raise RuntimeError(message)
    return value


def log(stage, **data):
    print(json.dumps({"stage": stage, **data}, ensure_ascii=False), flush=True)


def relation(obj, kind, partner=None, index=None, partner_index=None, name=None, value=None):
    link = require(obj.NewConstraint(), "NewConstraint")
    link.SetConstraintType(kind)
    if partner is not None:
        link.SetPartners([partner])
    if index is not None:
        link.SetIndex(index)
    if partner_index is not None:
        link.SetPartnerIndex(partner_index)
    if name is not None:
        link.SetVariable(name)
    if value is not None:
        link.SetConstraintValue(value)
    require(link.Create() and link.IsValid(), f"Constraint {kind}: {name}")
    return link


def driving(dim, name, value):
    fixed = relation(dim, c.ksCFixedDim)
    log("dimension-fixed", name=name, native_value=fixed.GetConstraintValue(), nominal=ksapi.IDimensionText(dim).GetNominalValue(), constraints=[x.GetConstraintType() for x in dim.GetConstraints()])
    relation(dim, c.ksCDimWithVariable, name=name, value=value)
    return dim


def linear(symbols, p, q, placement, orientation, name, value):
    dim = require(symbols.GetLineDimensions().Add(), "Line dimension")
    dim.SetX1(p[0]); dim.SetY1(p[1])
    dim.SetX2(q[0]); dim.SetY2(q[1])
    dim.SetX3(placement[0]); dim.SetY3(placement[1])
    dim.SetOrientation(orientation)
    require(dim.Update(), f"Dimension Update {name}")
    require(dim.Associate(), f"Dimension Associate {name}")
    links = dim.GetConstraints()
    require(all(any(x.IsValid() and x.GetConstraintType() == c.ksCMergePoints
                    and x.GetIndex() == i for x in links) for i in (0, 1)),
            f"Witness associations {name}")
    return driving(dim, name, value)


def radial(symbols, obj, center, radius, name):
    dim = require(symbols.GetRadialDimensions().Add(), "Radial dimension")
    dim.SetBaseObject(obj)
    dim.SetXc(center[0]); dim.SetYc(center[1])
    dim.SetRadius(radius); dim.SetAngle(30.)
    require(dim.Update(), "Radial Update")
    require(any(x.IsValid() and x.GetConstraintType() == c.ksCAssociation
                for x in dim.GetConstraints()), "Radial association")
    return driving(dim, name, radius)


@contextmanager
def edit(sketch):
    fragment = require(sketch.BeginEdit(False), "BeginEdit")
    try:
        fragment.SetParametricMode(True)
        require(fragment.IsParametricMode(), "Parametric mode")
        view = require(fragment.GetViewsAndLayersManager().GetViews().GetActiveView(), "Sketch view")
        yield require(ksapi.IDrawingContainer(view), "Drawing"), require(ksapi.ISymbols2DContainer(view), "Symbols")
    finally:
        require(sketch.EndEdit(), "EndEdit")


def build(part, model):
    angle = math.radians(50.)
    a = (-12. * math.sin(angle), 12. * math.cos(angle))
    b = ((65. - 12. / math.cos(angle)) / math.tan(angle), 65.)
    cc = (135., 65.)
    d = (135., 41.)
    e = ((41. + 12. / math.cos(angle)) / math.tan(angle), 41.)
    f = (-a[0], -a[1])
    vertices = [a, b, cc, d, e, f]
    sketch = require(model.GetSketchs().Add(), "Sketch")
    sketch.SetName("01 Контур R12, угол 50°, 2×Ø11")
    sketch.SetPlane(require(part.GetDefaultObject(c3d.o3d_planeXOY), "XOY plane"))
    require(sketch.Update(), "Sketch plane Update")
    with edit(sketch) as (drawing, symbols):
        edges = []
        for p, q in zip(vertices, vertices[1:]):
            line = require(drawing.GetLineSegments().Add(), "Line")
            line.SetX1(p[0]); line.SetY1(p[1]); line.SetX2(q[0]); line.SetY2(q[1])
            require(line.Update(), "Line Update")
            edges.append(line)
        cap = require(drawing.GetArcs().Add(), "Arc")
        cap.SetXc(0.); cap.SetYc(0.); cap.SetRadius(12.)
        cap.SetAngle1(-40.); cap.SetAngle2(140.); cap.SetDirection(True)
        require(cap.Update(), "Arc Update")
        holes = []
        for center in [(0., 0.), (100., 53.)]:
            hole = require(drawing.GetCircles().Add(), "Hole circle")
            hole.SetXc(center[0]); hole.SetYc(center[1]); hole.SetRadius(5.5)
            require(hole.Update(), "Circle Update")
            holes.append(hole)
        for i in range(4):
            relation(edges[i], c.ksCMergePoints, edges[i+1], 1, 0)
        relation(edges[-1], c.ksCMergePoints, cap, 1, 1)
        relation(cap, c.ksCMergePoints, edges[0], 2, 0)
        relation(edges[1], c.ksCHorizontal)
        relation(edges[2], c.ksCVertical)
        relation(edges[3], c.ksCHorizontal)
        relation(edges[0], c.ksCParallel, edges[4])
        relation(cap, c.ksCTangentTwoCurves, edges[0])
        relation(cap, c.ksCTangentTwoCurves, edges[4])
        # The only fixed point is the cap centre: the red origin on the drawing.
        relation(cap, c.ksCFixedPoint, index=0)
        radial(symbols, cap, (0., 0.), 12., "cap_radius")
        linear(symbols, (0., 0.), cc, (-25., 30.), c.ksLinDVertical, "top_height", 65.)
        linear(symbols, (0., 0.), d, (65., -30.), c.ksLinDHorizontal, "right_edge_x", 135.)
        linear(symbols, cc, d, (155., 53.), c.ksLinDVertical, "arm_width", 24.)
        angular = require(symbols.GetAngleDimensions().Add(c.ksDrADimension), "Angle dimension")
        angular.SetBaseObject1(edges[1]); angular.SetBaseObject2(edges[0])
        angular.SetXc(b[0]); angular.SetYc(b[1])
        angular.SetX1(cc[0]); angular.SetY1(cc[1])
        angular.SetX2(b[0] + 20.*math.cos(angle)); angular.SetY2(b[1] + 20.*math.sin(angle))
        angular.SetAngle1(0.); angular.SetAngle2(50.)
        angular.SetRadius(25.); angular.SetDirection(False)
        angular.SetDimensionType(c.ksADMinAngle)
        require(angular.Update(), "Angle dimension Update")
        log("angle-associations", types=[x.GetConstraintType() for x in angular.GetConstraints()])
        # FixedDim is the native driving angle; this binding rejected a named
        # angular variable although the nominal 50° and FixedDim are valid.
        relation(angular, c.ksCFixedDim)
        require(abs(ksapi.IDimensionText(angular).GetNominalValue() - 50.) < 1e-7,
                "Native driving angle must be 50 degrees")
        relation(holes[0], c.ksCConcentricity, cap)
        radial(symbols, holes[0], (0., 0.), 5.5, "bore_radius")
        relation(holes[1], c.ksCEqualRadius, holes[0])
        linear(symbols, (100., 53.), cc, (117., 80.), c.ksLinDHorizontal, "hole_edge_offset", 35.)
        linear(symbols, d, (100., 53.), (175., 46.), c.ksLinDVertical, "hole_center_height", 12.)
    state = sketch.GetConstraintsState()
    log("sketch", constraint_state=state)
    operation = require(model.GetExtrusions().Add(c3d.o3d_bossExtrusion), "Extrusion")
    operation.SetName("02 Пластина 10 мм со сквозными отверстиями")
    operation.SetProfiles([sketch]); operation.SetDirection(c3d.dtNormal)
    require(operation.SetSideParameters(True, c3d.etBlind, 10., 0., False, None), "Extrusion depth 10")
    require(operation.Update(), "Extrusion Update")
    return sketch, operation, state


def feature_errors(part):
    seen, errors = set(), []
    def visit(feature):
        if feature.reference in seen:
            return
        seen.add(feature.reference)
        if feature.GetObjectError():
            errors.append(f"{feature.GetName()}: {feature.GetObjectError()}")
        for child in feature.GetSubFeatures(c.ksOperTree, True, True):
            if child:
                visit(child)
    visit(require(ksapi.IFeature(part), "Part feature"))
    return errors


def main():
    result = dict(task="1.17", status="failed", title="Угловая пластина с двумя отверстиями",
                  script="solution.py", model=None, volume_mm3=None, reference_volume=38693,
                  reference_units="mm3", volume_passed=False, checks=[], limitations=[],
                  tree="Эскиз контура R12, 50°, 2×Ø11 → выдавливание 10 мм")
    attempt = Path(tempfile.mkdtemp(prefix="attempt-", dir=ROOT))
    output = attempt / "model.m3d"
    doc = None
    try:
        require(not output.exists() and not output.is_symlink(), "Output must not exist")
        app = require(ksapi.GetKompas(), "Нет запущенной API-сессии КОМПАС; запуск не выполнялся")
        doc = require(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart, True), "Own new part")
        part = require(ksapi.IKompasDocument3D(doc).GetTopPart(), "Top part")
        part.SetName("Practice Problem 1.17 — угловая пластина")
        sketch, operation, state = build(part, require(part.GetModelContainer(), "Model"))
        result["checks"].append(f"Состояние связей эскиза: {state} (полностью определён = {c.ksStateWellConstrained}).")
        result["checks"].append("Начало координат — центр R12/левого отверстия по красной метке; фиксирована только эта точка.")
        result["limitations"].append("Угловой размер 50° управляет геометрией через ksCFixedDim без именованной переменной: создание ksCDimWithVariable для него отклонено Linux API. Линейные и радиальные размеры имеют именованные переменные.")
        if state != c.ksStateWellConstrained:
            result["limitations"].append(f"Эскиз не полностью определён: состояние {state}.")
        require(part.RebuildModel(True), "RebuildModel")
        errors = feature_errors(part)
        require(not errors, f"Feature errors: {errors}")
        result["checks"].append("Дерево построения обойдено: GetObjectError=0 для всех элементов.")
        bodies = ksapi.IFeature(part).GetResultBodies()
        require(len(bodies) == 1 and bodies[0].IsSolid(), "One solid")
        result["checks"].append("Получено одно твёрдое тело; выдавливание 10 мм успешно.")
        mass = require(ksapi.IMassInertiaParam(part), "Mass properties")
        mass.SetLengthUnits(c.ksLUnMM)
        require(mass.GetLengthUnits() == 1, "Mass length units must read back 1")
        require(mass.Calculate(), "Mass Calculate")
        require(mass.GetLengthUnits() == 1, "Mass length units after Calculate")
        volume = mass.GetVolume()
        require(math.isfinite(volume) and volume > 0., "Valid volume")
        result["volume_mm3"] = volume
        result["volume_passed"] = 38692.5 <= volume < 38693.5
        result["checks"].append(f"IMassInertiaParam.SetLengthUnits(ksLUnMM); GetLengthUnits=1; Calculate успешно; объём {volume:.9f} мм³.")
        result["checks"].append(f"Сравнение с [38692.5,38693.5) мм³: {result['volume_passed']}.")
        require(not output.exists() and not output.is_symlink(), "SaveAs destination must not exist")
        require(doc.SaveAs(str(output)), "SaveAs")
        require(output.is_file() and output.stat().st_size > 0, "Native model file")
        result["model"] = str(output.relative_to(ROOT))
        result["checks"].append("SaveAs в новый attempt-каталог успешно; нативный model.m3d существует и непустой.")
        result["status"] = "passed" if result["volume_passed"] and state == c.ksStateWellConstrained else "partial"
        if not result["volume_passed"]:
            result["limitations"].append("Объём вне интервала округления эталона; геометрия под объём не подгонялась.")
    except Exception as exc:
        result["limitations"].append(f"{type(exc).__name__}: {exc}")
        log("error", error=str(exc))
    finally:
        if doc is not None:
            try:
                require(doc.Close(c.kdDoNotSaveChanges), "Close own document")
                result["checks"].append("Собственный документ закрыт в finally; чужие документы не изменялись и не закрывались.")
            except Exception as exc:
                result["limitations"].append(f"Закрытие собственного документа: {exc}")
                result["status"] = "partial" if result["model"] else "failed"
        (ROOT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        log("result", **result)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
