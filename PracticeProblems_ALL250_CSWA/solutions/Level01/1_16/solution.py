# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Practice Problem 1.16: native, dimension-driven KOMPAS-3D part."""
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
TREE = "Основание: эскиз 125×15 → выдавливание 60; проушина: касательный полукруг R20, центр (50,35), основание y=15, соосное отверстие R10 → выдавливание 40"


def require(value, message):
    if not value:
        raise RuntimeError(message)
    return value


def absent(path):
    require(not path.exists() and not path.is_symlink(), f"Output already exists: {path}")


def constraint(obj, kind, *, partner=None, index=None, partner_index=None, name=None, value=None):
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
    require(item.Create() and item.IsValid(), f"Constraint type={kind}, variable={name}")
    return item


def drive(dim, name, value):
    constraint(dim, c.ksCFixedDim)
    constraint(dim, c.ksCDimWithVariable, name=name, value=value)
    return dim


def linear(symbols, a, b, offset, orientation, partners, name, value):
    dim = require(symbols.GetLineDimensions().Add(), "Linear dimension")
    dim.SetX1(a[0]); dim.SetY1(a[1])
    dim.SetX2(b[0]); dim.SetY2(b[1])
    dim.SetX3(offset[0]); dim.SetY3(offset[1])
    dim.SetOrientation(orientation)
    require(dim.Update(), f"Dimension Update: {name}")
    require(dim.Associate(), f"Dimension Associate: {name}")
    links = dim.GetConstraints()
    for i, (partner, index) in enumerate(partners):
        require(any(link.IsValid() and link.GetConstraintType() == c.ksCMergePoints
                    and link.GetIndex() == i and link.GetPartnerIndex() == index
                    and any(obj.GetId() == partner.GetId() for obj in link.GetPartners())
                    for link in links), f"Dimension witness association: {name}/{i}")
    return drive(dim, name, value)


def radial(symbols, obj, center, radius, name):
    dim = require(symbols.GetRadialDimensions().Add(), "Radial dimension")
    dim.SetBaseObject(obj)
    dim.SetXc(center[0]); dim.SetYc(center[1])
    dim.SetRadius(radius); dim.SetAngle(55.)
    require(dim.Update(), f"Radial Update: {name}")
    require(any(item.IsValid() and item.GetConstraintType() == c.ksCAssociation
                for item in dim.GetConstraints()), f"Radial association: {name}")
    return drive(dim, name, radius)


def line(drawing, a, b):
    obj = require(drawing.GetLineSegments().Add(), "Line")
    obj.SetX1(a[0]); obj.SetY1(a[1])
    obj.SetX2(b[0]); obj.SetY2(b[1])
    require(obj.Update(), "Line Update")
    return obj


def merge(a, ia, b, ib):
    constraint(a, c.ksCMergePoints, partner=b, index=ia, partner_index=ib)


@contextmanager
def edit(sketch):
    fragment = require(sketch.BeginEdit(False), "BeginEdit")
    try:
        fragment.SetParametricMode(True)
        require(fragment.IsParametricMode(), "Parametric mode")
        view = require(fragment.GetViewsAndLayersManager().GetViews().GetActiveView(), "View")
        yield require(ksapi.IDrawingContainer(view), "Drawing"), require(ksapi.ISymbols2DContainer(view), "Symbols")
    finally:
        require(sketch.EndEdit(), "EndEdit")
    state = sketch.GetConstraintsState()
    print(json.dumps({"sketch": sketch.GetName(), "constraint_state": state}), flush=True)
    require(state == c.ksStateWellConstrained, f"Sketch not fully defined: {sketch.GetName()}, state={state}")


def sketch(model, part, name):
    obj = require(model.GetSketchs().Add(), "Sketch")
    obj.SetName(name)
    obj.SetPlane(require(part.GetDefaultObject(c3d.o3d_planeXOY), "XOY"))
    require(obj.Update(), "Sketch Update")
    return obj


def extrusion(model, profile, depth, name):
    obj = require(model.GetExtrusions().Add(c3d.o3d_bossExtrusion), "Boss extrusion")
    obj.SetName(name)
    obj.SetProfiles([profile])
    obj.SetDirection(c3d.dtNormal)
    require(obj.SetSideParameters(True, c3d.etBlind, depth, 0., False, None), "Extrusion depth")
    require(obj.Update(), f"Extrusion Update: {name}")
    return obj


def build(part, checks):
    model = require(part.GetModelContainer(), "Model container")
    base = sketch(model, part, "Основание — 125×15, начало в красной метке")
    with edit(base) as (drawing, symbols):
        p = [(0., 0.), (125., 0.), (125., 15.), (0., 15.)]
        edges = [line(drawing, p[i], p[(i+1) % 4]) for i in range(4)]
        for i, edge in enumerate(edges):
            merge(edge, 1, edges[(i+1) % 4], 0)
            constraint(edge, c.ksCHorizontal if i % 2 == 0 else c.ksCVertical)
        constraint(edges[0], c.ksCFixedPoint, index=0)
        linear(symbols, p[0], p[1], (60., -10.), c.ksLinDHorizontal,
               [(edges[0], 0), (edges[0], 1)], "base_length", 125.)
        linear(symbols, p[1], p[2], (140., 7.), c.ksLinDVertical,
               [(edges[1], 0), (edges[1], 1)], "base_thickness", 15.)
    checks.append("Эскиз основания полностью определён: совпадения, H/V, два управляющих размера и одна базовая точка; состояние=1")
    extrusion(model, base, 60., "Основание — глубина 60 мм")

    lug = sketch(model, part, "Проушина — Ø40, отверстие Ø20, центр 50×35")
    with edit(lug) as (drawing, symbols):
        origin = require(drawing.GetPoints().Add(), "Origin reference point")
        origin.SetX(0.); origin.SetY(0.)
        require(origin.Update(), "Origin point Update")
        constraint(origin, c.ksCFixedPoint, index=0)
        bottom = line(drawing, (30., 15.), (70., 15.))
        right = line(drawing, (70., 15.), (70., 35.))
        left = line(drawing, (30., 35.), (30., 15.))
        arc = require(drawing.GetArcs().Add(), "Semicircle")
        arc.SetXc(50.); arc.SetYc(35.); arc.SetRadius(20.)
        arc.SetAngle1(0.); arc.SetAngle2(180.); arc.SetDirection(False)
        require(arc.Update(), "Semicircle Update")
        hole = require(drawing.GetCircles().Add(), "Hole circle")
        hole.SetXc(50.); hole.SetYc(35.); hole.SetRadius(10.)
        require(hole.Update(), "Hole circle Update")
        merge(bottom, 1, right, 0)
        merge(right, 1, arc, 1)
        merge(arc, 2, left, 0)
        merge(left, 1, bottom, 0)
        constraint(bottom, c.ksCHorizontal)
        constraint(right, c.ksCVertical)
        constraint(left, c.ksCVertical)
        constraint(arc, c.ksCTangentTwoCurves, partner=right)
        constraint(arc, c.ksCTangentTwoCurves, partner=left)
        constraint(hole, c.ksCConcentricity, partner=arc)
        linear(symbols, (0.,0.), (50.,35.), (25.,-20.), c.ksLinDHorizontal,
               [(origin,0), (arc,0)], "lug_center_x", 50.)
        linear(symbols, (0.,0.), (50.,35.), (-12.,18.), c.ksLinDVertical,
               [(origin,0), (arc,0)], "lug_center_height", 35.)
        linear(symbols, (0.,0.), (30.,15.), (-23.,7.), c.ksLinDVertical,
               [(origin,0), (bottom,0)], "lug_base_height", 15.)
        radial(symbols, arc, (50.,35.), 20., "lug_radius")
        radial(symbols, hole, (50.,35.), 10., "hole_radius")
    checks.append("Эскиз проушины полностью определён: замкнутый контур, H/V, две касательности, концентричность, пять управляющих размеров; состояние=1; фиксирована только базовая точка")
    extrusion(model, lug, 40., "Проушина с отверстием — глубина 40 мм")
    checks.append("Оба нативных выдавливания успешно построены: глубины 60 и 40 мм")


def feature_errors(part):
    errors, seen = [], set()
    def visit(item):
        if item.reference in seen:
            return
        seen.add(item.reference)
        if item.GetObjectError():
            errors.append(f"{item.GetName()}: {item.GetObjectError()}")
        for child in item.GetSubFeatures(c.ksOperTree, True, True):
            if child:
                visit(child)
    visit(require(ksapi.IFeature(part), "Part feature"))
    return errors


def main():
    output = Path(tempfile.mkdtemp(prefix="attempt-", dir=ROOT)) / "model.m3d"
    absent(output)
    result = {"task": "1.16", "status": "failed", "title": "SOLIDWORKS Practice Problem 1.16 — проушина на основании", "script": "solution.py", "model": None,
              "volume_mm3": None, "reference_volume": 157066, "reference_units": "mm3", "volume_passed": False,
              "checks": [], "limitations": [], "tree": TREE}
    doc = None
    try:
        app = require(ksapi.GetKompas(), "Нет существующей API-сессии КОМПАС; запуск запрещён")
        doc = require(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart, True), "New owned part")
        doc3d = require(ksapi.IKompasDocument3D(doc), "3D document")
        part = require(doc3d.GetTopPart(), "Top part")
        part.SetName("Practice Problem 1.16 — проушина")
        build(part, result["checks"])
        require(part.RebuildModel(True), "RebuildModel")
        errors = feature_errors(part)
        require(not errors, f"Ошибки дерева: {errors}")
        result["checks"].append("После перестроения ошибок в нативном дереве операций нет")
        bodies = ksapi.IFeature(part).GetResultBodies()
        require(len(bodies) == 1 and bodies[0].IsSolid(), "One native solid")
        result["checks"].append("Получено одно твёрдое тело")
        mass = require(ksapi.IMassInertiaParam(part), "IMassInertiaParam")
        mass.SetLengthUnits(c.ksLUnMM)
        units = mass.GetLengthUnits()
        require(units == 1, f"Length units readback: {units}")
        require(mass.Calculate(), "Mass properties Calculate")
        volume = mass.GetVolume()
        require(math.isfinite(volume) and volume > 0, "Finite positive native volume")
        result["volume_mm3"] = volume
        result["volume_passed"] = 157065.5 <= volume < 157066.5
        result["checks"].append("МЦХ: SetLengthUnits(c.ksLUnMM), GetLengthUnits()=1; расчёт выполнен")
        result["checks"].append(f"Объём {volume:.9f} мм³; попадание в [157065.5,157066.5): {result['volume_passed']}")
        absent(output)
        require(doc.SaveAs(str(output)), "SaveAs new attempt/model.m3d")
        require(output.is_file() and output.stat().st_size > 0, "Saved nonempty native model")
        require(Path(doc.GetFullPath()).resolve() == output.resolve(), "Saved document path")
        result["model"] = str(output.relative_to(ROOT))
        result["checks"].append("SaveAs выполнен в заранее несуществующий путь; непустой model.m3d сохранён, путь документа подтверждён")
        result["status"] = "passed" if result["volume_passed"] else "partial"
    except Exception as exc:
        result["limitations"].append(f"{type(exc).__name__}: {exc}")
        if doc is None:
            result["status"] = "blocked"
        traceback.print_exc()
    finally:
        if doc is not None:
            try:
                require(doc.Close(c.kdDoNotSaveChanges), "Close owned document")
                result["checks"].append("Собственный документ закрыт в finally; чужие документы не изменялись")
            except Exception as exc:
                result["status"] = "partial" if result["model"] else "failed"
                result["limitations"].append(f"Закрытие собственного документа: {exc}")
        (ROOT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
