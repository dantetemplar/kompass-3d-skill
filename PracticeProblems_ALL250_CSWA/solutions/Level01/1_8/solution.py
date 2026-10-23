# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Practice 1.8: native dimension-driven roof and transverse stepped ribs."""
from __future__ import annotations

import json
import math
from pathlib import Path
import tempfile
import traceback

import ksapi
from constants import constants as c
from constants3d import constants as c3d

ROOT = Path(__file__).resolve().parent
REFERENCE = 2928250
TREE = "Основание: размерный эскиз двускатного профиля → симметричное выдавливание 175; рёбра: размерный ступенчатый эскиз → симметричное выдавливание 200"


def require(value, message):
    if not value:
        raise RuntimeError(message)
    return value


def report(result):
    (ROOT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def constraint(obj, kind, partners=(), index=None, partner_index=None, name=None, value=None):
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
    require(item.Create() and item.IsValid(), f"Constraint {kind}, {name}")
    return item


def dimension(symbols, lines, points, transform, orientation, witnesses, name, value):
    dim = require(symbols.GetLineDimensions().Add(), "Line dimension")
    a, b, position = [transform(*p) for p in points]
    dim.SetX1(a[0])
    dim.SetY1(a[1])
    dim.SetX2(b[0])
    dim.SetY2(b[1])
    dim.SetX3(position[0])
    dim.SetY3(position[1])
    # Canonical horizontal/vertical directions may be swapped by the YOZ plane.
    origin = transform(0, 0)
    axis = transform(1, 0) if orientation == "h" else transform(0, 1)
    horizontal = abs(axis[0] - origin[0]) > abs(axis[1] - origin[1])
    dim.SetOrientation(c.ksLinDHorizontal if horizontal else c.ksLinDVertical)
    require(dim.Update(), f"Dimension Update {name}")
    require(dim.Associate(), f"Associate dimension {name}")
    associations = dim.GetConstraints()
    require(all(any(item.IsValid() and item.GetConstraintType() == c.ksCMergePoints and item.GetIndex() == i for item in associations) for i in (0, 1)), f"Witness associations {name}")
    constraint(dim, c.ksCFixedDim)
    constraint(dim, c.ksCDimWithVariable, name=name, value=value)
    return dim


def make_sketch(part, model, name, plane_kind, vertices, equalities, dimensions, perpendicular=()):
    sketch = require(model.GetSketchs().Add(), "New sketch")
    sketch.SetName(name)
    sketch.SetPlane(require(part.GetDefaultObject(plane_kind), "Default plane"))
    require(sketch.Update(), "Sketch support")
    axes = [sketch.GetPoint3D(u, v, 0, 0, 0) for u, v in [(0, 0), (1, 0), (0, 1)]]
    require(all(item[0] for item in axes), "Sketch coordinate readback")
    print(json.dumps({"sketch": name, "coordinate_frame": axes}), flush=True)
    if plane_kind == c3d.o3d_planeXOY:
        require(all(abs(a - b) < 1e-8 for actual, expected in zip(axes, [(True, 0, 0, 0), (True, 1, 0, 0), (True, 0, 1, 0)]) for a, b in zip(actual[1:], expected[1:])), "XOY frame")
        transform = lambda u, v: (u, v)
    else:
        projected = [sketch.GetPointProjectionToXY(x, y, z, 0, 0) for x, y, z in [(0, 0, 0), (0, 0, 1), (0, 1, 0)]]
        require(all(item[0] for item in projected), "Side sketch projection")
        origin, along, up = [item[1:] for item in projected]
        transform = lambda u, v: tuple(origin[i] + u * (along[i] - origin[i]) + v * (up[i] - origin[i]) for i in range(2))
    fragment = require(sketch.BeginEdit(False), "BeginEdit")
    try:
        fragment.SetParametricMode(True)
        require(fragment.IsParametricMode(), "Parametric sketch")
        view = require(fragment.GetViewsAndLayersManager().GetViews().GetActiveView(), "Sketch view")
        drawing = require(ksapi.IDrawingContainer(view), "Drawing container")
        symbols = require(ksapi.ISymbols2DContainer(view), "Symbols container")
        lines = []
        local_vertices = [transform(*p) for p in vertices]
        for a, b in zip(local_vertices, local_vertices[1:] + local_vertices[:1]):
            line = require(drawing.GetLineSegments().Add(), "Line")
            line.SetX1(a[0])
            line.SetY1(a[1])
            line.SetX2(b[0])
            line.SetY2(b[1])
            require(line.Update(), "Line Update")
            lines.append(line)
        for i, (a, b) in enumerate(zip(local_vertices, local_vertices[1:] + local_vertices[:1])):
            constraint(lines[i], c.ksCMergePoints, [lines[(i + 1) % len(lines)]], index=1, partner_index=0)
            if abs(a[1] - b[1]) < 1e-8:
                constraint(lines[i], c.ksCHorizontal)
            elif abs(a[0] - b[0]) < 1e-8:
                constraint(lines[i], c.ksCVertical)
        # Exactly one anchored vertex, at the origin, per independent sketch.
        constraint(lines[0], c.ksCFixedPoint, index=0)
        for a, b in equalities:
            constraint(lines[a], c.ksCEqualLength, [lines[b]])
        for a, b in perpendicular:
            constraint(lines[a], c.ksCPerpendicular, [lines[b]])
        for points, orientation, witnesses, varname, value in dimensions:
            dimension(symbols, lines, points, transform, orientation, witnesses, varname, value)
    finally:
        require(sketch.EndEdit(), "EndEdit")
    state = sketch.GetConstraintsState()
    print(json.dumps({"sketch": name, "constraints_state": state}), flush=True)
    require(state == c.ksStateWellConstrained, f"Sketch not fully defined: {name}, state {state}")
    return sketch


def extrude(model, sketch, name, full_length):
    operation = require(model.GetExtrusions().Add(c3d.o3d_bossExtrusion), "Boss extrusion")
    operation.SetName(name)
    operation.SetProfiles([sketch])
    operation.SetDirection(c3d.dtBoth)
    for side in (True, False):
        require(operation.SetSideParameters(side, c3d.etBlind, full_length / 2, 0.0, False, None), "Symmetric depth")
    require(operation.Update(), f"Extrusion Update {name}")
    return operation


def check_tree(part):
    seen = set()
    errors = []
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
    feature = require(ksapi.IFeature(part), "Part feature")
    visit(feature)
    require(not errors, f"Tree errors: {errors}")
    bodies = feature.GetResultBodies()
    require(len(bodies) == 1 and bodies[0].IsSolid(), "Exactly one solid")
    return len(seen)


def main():
    attempt = Path(tempfile.mkdtemp(prefix="attempt-", dir=ROOT))
    target = attempt / "model.m3d"
    require(not target.exists(), "New model path")
    result = {
        "task": "1.8", "status": "blocked", "title": "Двускатное основание с поперечными рёбрами",
        "script": "solution.py", "model": None, "volume_mm3": None,
        "reference_volume": REFERENCE, "reference_units": "mm3", "volume_passed": None,
        "checks": ["solution.py проверен ast.parse до выполнения"],
        "limitations": [
            "Симметрия двускатного профиля и парных рёбер прочитана по согласованным видам и указанному началу координат.",
            "Ширина рёберного профиля 75 = 175 − 2×50; уровень перемычки 65 = 50 + 15 TYP. Эти производные размеры заданы нативно, но межэскизные формулы между ними не созданы.",
            "Пробные изменения размеров и повторное открытие не выполнялись."
        ], "tree": TREE
    }
    report(result)
    app = None
    doc = None
    previous = None
    unknown_outcome = False
    saved = False
    phase = "connection"
    exit_code = 1
    try:
        app = require(ksapi.GetKompas(), "Нет действующей API-сессии")
        previous = app.GetActiveDocument()
        phase = "new document"
        doc = require(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart, True), "New own part")
        doc3d = require(ksapi.IKompasDocument3D(doc), "3D document")
        part = require(doc3d.GetTopPart(), "Top part")
        part.SetName(result["title"])
        model = require(part.GetModelContainer(), "Model container")
        phase = "roof sketch"
        roof = make_sketch(part, model, "Двускатный профиль: 200 × 125; полка 50; прямой угол", c3d.o3d_planeXOY,
            [(0, 0), (100, 0), (100, 50), (75, 50), (0, 125), (-75, 50), (-100, 50), (-100, 0)],
            [(0, 7), (1, 6), (2, 5), (3, 4)],
            [([(-100, 0), (100, 0), (0, -15)], "h", [(7, 0), (0, 1)], "base_width", 200.0),
             ([(100, 0), (100, 50), (115, 25)], "v", [(1, 0), (1, 1)], "shelf_height", 50.0),
             ([(0, 0), (0, 125), (-120, 65)], "v", [(0, 0), (3, 1)], "apex_height", 125.0)],
            perpendicular=[(3, 4)])
        result["checks"].append("Первый эскиз: WellConstrained; совпадения, H/V, равенства и перпендикулярность скатов; одна базовая точка; управляющие размеры 200, 50, 125 мм")
        phase = "roof extrusion"
        extrude(model, roof, "Основание — 175 симметрично", 175.0)
        phase = "rib sketch"
        ribs = make_sketch(part, model, "Поперечные рёбра: 15; высота 100; перемычка 65", c3d.o3d_planeYOZ,
            [(0, 0), (37.5, 0), (37.5, 100), (22.5, 100), (22.5, 65), (-22.5, 65), (-22.5, 100), (-37.5, 100), (-37.5, 0)],
            [(0, 8), (1, 7), (2, 6)],
            [([(-37.5, 0), (37.5, 0), (0, -15)], "h", [(8, 0), (0, 1)], "rib_profile_width", 75.0),
             ([(37.5, 0), (37.5, 100), (55, 50)], "v", [(1, 0), (1, 1)], "rib_height", 100.0),
             ([(37.5, 100), (22.5, 100), (30, 112)], "h", [(2, 0), (2, 1)], "rib_thickness", 15.0),
             ([(0, 0), (22.5, 65), (-55, 32.5)], "v", [(0, 0), (3, 1)], "bridge_height", 65.0)])
        result["checks"].append("Второй эскиз: WellConstrained; совпадения, H/V и равенства парных элементов; одна базовая точка; управляющие размеры 75, 100, 15, 65 мм")
        phase = "rib extrusion"
        extrude(model, ribs, "Два ребра и перемычка — 200 симметрично", 200.0)
        phase = "rebuild and tree"
        require(doc3d.CompleteRebuildDocument(), "Complete rebuild")
        count = check_tree(part)
        result["checks"].append(f"CompleteRebuildDocument успешен; дерево без ошибок ({count} объектов); одно твёрдое тело")
        phase = "CAD volume"
        inertia = require(ksapi.IMassInertiaParam(part), "Native inertia")
        inertia.SetLengthUnits(c.ksLUnMM)
        require(inertia.GetLengthUnits() == c.ksLUnMM, "Length units readback")
        require(inertia.Calculate(), "Native mass properties calculation")
        volume = inertia.GetVolume()
        require(math.isfinite(volume) and volume > 0, "Finite positive CAD volume")
        result["volume_mm3"] = volume
        result["volume_passed"] = 2928249.5 <= volume < 2928250.5
        result["checks"].append(f"IMassInertiaParam: SetLengthUnits(ksLUnMM), GetLengthUnits == {c.ksLUnMM}; Calculate успешен; CAD-объём {volume:.9f} мм³")
        result["checks"].append(f"Интервал эталона [2928249.5, 2928250.5): {'пройден' if result['volume_passed'] else 'не пройден'}")
        phase = "save"
        require(not target.exists(), "No overwrite before SaveAs")
        require(doc.SaveAs(str(target)), "SaveAs native model")
        require(target.is_file() and target.stat().st_size > 0, "Nonempty saved native file")
        saved = True
        result["model"] = str(target.relative_to(ROOT))
        result["checks"].append("SaveAs успешен; новый непустой model.m3d существует")
        result["status"] = "passed" if result["volume_passed"] else "partial"
        exit_code = 0
    except Exception as error:
        text = f"{type(error).__name__}: {error}"
        unknown_outcome = isinstance(error, (ConnectionError, TimeoutError, BrokenPipeError)) or any(word in text.lower() for word in ["socket", "connection", "transport", "rpc", "disconnected", "server unavailable"])
        result["status"] = "blocked" if unknown_outcome or doc is None else "failed"
        result["limitations"].append(f"Этап {phase}: {text}" + ("; исход API неизвестен, дальнейшие API-вызовы прекращены" if unknown_outcome else ""))
        traceback.print_exc()
        if doc is not None and not unknown_outcome and not saved:
            try:
                require(not target.exists(), "No overwrite for partial model")
                require(doc.SaveAs(str(target)), "Save partial own model")
                require(target.is_file() and target.stat().st_size > 0, "Partial native file")
                result["model"] = str(target.relative_to(ROOT))
                result["checks"].append("Собственная незавершённая модель сохранена в новый attempt-*/model.m3d")
            except Exception as save_error:
                result["limitations"].append(f"Сохранение незавершённой модели: {save_error}")
                unknown_outcome = True
    finally:
        if doc is not None and not unknown_outcome:
            try:
                require(doc.Close(c.kdDoNotSaveChanges), "Close own document")
                result["checks"].append("Собственный документ закрыт после сохранения; чужие документы не изменялись и не закрывались")
                if previous:
                    previous.SetActive()
            except Exception as close_error:
                result["status"] = "blocked"
                result["limitations"].append(f"Закрытие/восстановление активного документа: {close_error}")
                exit_code = 1
        report(result)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
