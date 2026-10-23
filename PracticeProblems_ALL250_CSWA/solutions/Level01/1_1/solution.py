# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Practice Problem 1.1: independent native KOMPAS Linux construction."""
from __future__ import annotations

from contextlib import contextmanager
import json
import math
from pathlib import Path
import tempfile
import sys

import ksapi
from constants import constants as c
from constants3d import constants as c3d

ROOT = Path(__file__).resolve().parent
REFERENCE = 72593
STAGE = "initialization"


def require(value, message):
    if not value:
        raise RuntimeError(message)
    return value


def constraint(obj, kind, *, partner=None, index=None, partner_index=None,
               variable=None, value=None):
    item = require(obj.NewConstraint(), "NewConstraint")
    item.SetConstraintType(kind)
    if partner is not None:
        item.SetPartners([partner])
    if index is not None:
        item.SetIndex(index)
    if partner_index is not None:
        item.SetPartnerIndex(partner_index)
    if variable is not None:
        item.SetVariable(variable)
    if value is not None:
        item.SetConstraintValue(value)
    require(item.Create() and item.IsValid(), f"Constraint {kind}: {variable}")
    return item


def driving(dim, name, value):
    constraint(dim, c.ksCFixedDim)
    constraint(dim, c.ksCDimWithVariable, variable=name, value=value)
    return dim


def dimension(symbols, p1, p2, place, horizontal, name, value):
    dim = require(symbols.GetLineDimensions().Add(), "Line dimension")
    dim.SetX1(p1[0])
    dim.SetY1(p1[1])
    dim.SetX2(p2[0])
    dim.SetY2(p2[1])
    dim.SetX3(place[0])
    dim.SetY3(place[1])
    dim.SetOrientation(c.ksLinDHorizontal if horizontal else c.ksLinDVertical)
    require(dim.Update(), "Dimension Update")
    require(dim.Associate(), f"Associate {name}")
    return driving(dim, name, value)


@contextmanager
def edit(sketch):
    global STAGE
    STAGE = f"BeginEdit: {sketch.GetName()}"
    fragment = require(sketch.BeginEdit(False), STAGE)
    fragment.SetParametricMode(True)
    require(fragment.IsParametricMode(), "Parametric mode")
    view = require(fragment.GetViewsAndLayersManager().GetViews().GetActiveView(), "View")
    try:
        yield ksapi.IDrawingContainer(view), ksapi.ISymbols2DContainer(view)
    except Exception:
        # An exception from a remote call may have an unknown outcome. No more
        # CAD writes, including EndEdit/Close, are attempted in that case.
        raise
    else:
        STAGE = "EndEdit"
        require(sketch.EndEdit(), "EndEdit")
        state = sketch.GetConstraintsState()
        require(state == c.ksStateWellConstrained, f"Sketch constraint state: {state}")
        print(json.dumps({"sketch": sketch.GetName(), "constraint_state": state},
                         ensure_ascii=False), flush=True)


def polygon(drawing, vertices):
    lines = []
    for p1, p2 in zip(vertices, vertices[1:] + vertices[:1]):
        line = require(drawing.GetLineSegments().Add(), "Line")
        line.SetX1(p1[0])
        line.SetY1(p1[1])
        line.SetX2(p2[0])
        line.SetY2(p2[1])
        require(line.Update(), "Line Update")
        lines.append(line)
    for i, line in enumerate(lines):
        p1, p2 = vertices[i], vertices[(i + 1) % len(vertices)]
        constraint(line, c.ksCMergePoints, partner=lines[(i + 1) % len(lines)],
                   index=1, partner_index=0)
        constraint(line, c.ksCHorizontal if p1[1] == p2[1] else c.ksCVertical)
    constraint(lines[0], c.ksCFixedPoint, index=0)
    return lines


def new_sketch(part, model, name):
    sketch = require(model.GetSketchs().Add(), "Sketch")
    sketch.SetName(name)
    sketch.SetPlane(require(part.GetDefaultObject(c3d.o3d_planeXOY), "Base plane"))
    require(sketch.Update(), "Sketch Update")
    return sketch


def extrude(model, sketch, name, depth):
    global STAGE
    STAGE = name
    operation = require(model.GetExtrusions().Add(c3d.o3d_bossExtrusion), name)
    operation.SetName(name)
    operation.SetProfiles([sketch])
    operation.SetDirection(c3d.dtNormal)
    require(operation.SetSideParameters(True, c3d.etBlind, depth, 0., False, None), "Depth")
    require(operation.Update(), f"Update: {name}")
    return operation


def feature_errors(part):
    errors, visited = [], set()

    def visit(feature):
        if feature.reference in visited:
            return
        visited.add(feature.reference)
        error = feature.GetObjectError()
        if error:
            errors.append({"name": feature.GetName(), "error": error})
        for child in feature.GetSubFeatures(c.ksOperTree, True, True):
            if child:
                visit(child)

    visit(ksapi.IFeature(part))
    return errors


def main():
    global STAGE
    attempt = Path(tempfile.mkdtemp(prefix="attempt-", dir=ROOT))
    output = attempt / "model.m3d"
    result = {
        "task": "1.1", "status": "blocked", "title": "Ступенчатый кронштейн с отверстием",
        "script": "solution.py", "model": None, "volume_mm3": None,
        "reference_volume": REFERENCE, "reference_units": "mm3", "volume_passed": None,
        "checks": ["solution.py проверен ast.parse до запуска"],
        "limitations": [
            "Высота привязки верхнего эскиза 30 мм закреплена одной базовой точкой; межэскизная зависимость от высоты основания не задана.",
            "Размеры верхнего профиля 45, 16 и 48 мм получены из размеров чертежа; формулы между эскизами не заданы.",
            "Пробное изменение размеров не выполнялось."
        ],
        "tree": "Эскиз основания 60×30 с отверстием Ø12 → выдавливание 28; эскиз трёхступенчатого выступа → выдавливание 20, объединение с основанием."
    }
    try:
        require(not output.exists(), "Output already exists")
        STAGE = "GetKompas"
        app = require(ksapi.GetKompas(), "API session is unavailable")
        previous = app.GetActiveDocument()
        STAGE = "Create own document"
        doc = require(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart, True), "New part")
        doc3d = require(ksapi.IKompasDocument3D(doc), "3D document")
        part = require(doc3d.GetTopPart(), "Top part")
        part.SetName("1.1 — Ступенчатый кронштейн с отверстием")
        model = require(part.GetModelContainer(), "Model container")

        base = new_sketch(part, model, "Основание 60×30; Ø12, отступы 16×16")
        with edit(base) as (drawing, symbols):
            polygon(drawing, [(0., 0.), (60., 0.), (60., 30.), (0., 30.)])
            hole = require(drawing.GetCircles().Add(), "Hole circle")
            hole.SetXc(44.)
            hole.SetYc(16.)
            hole.SetRadius(6.)
            require(hole.Update(), "Circle Update")
            dimension(symbols, (0, 0), (60, 0), (30, -9), True, "base_width", 60.)
            dimension(symbols, (0, 0), (0, 30), (-10, 15), False, "base_height", 30.)
            dimension(symbols, (44, 16), (60, 0), (50, -16), True, "hole_right_offset", 16.)
            dimension(symbols, (0, 0), (44, 16), (70, 8), False, "hole_bottom_offset", 16.)
            radial = require(symbols.GetRadialDimensions().Add(), "Radius dimension")
            radial.SetBaseObject(hole)
            radial.SetXc(44.)
            radial.SetYc(16.)
            radial.SetRadius(6.)
            radial.SetAngle(45.)
            require(radial.Update(), "Radial Update")
            driving(radial, "hole_radius", 6.)
        extrude(model, base, "Основание: глубина 28 мм, сквозное Ø12", 28.)

        upper = new_sketch(part, model, "Ступени: высоты 75/50/38, ширины 20/12/16")
        with edit(upper) as (drawing, symbols):
            polygon(drawing, [(0., 30.), (48., 30.), (48., 38.), (32., 38.),
                              (32., 50.), (20., 50.), (20., 75.), (0., 75.)])
            dimension(symbols, (0, 75), (20, 75), (10, 84), True, "top_width", 20.)
            dimension(symbols, (20, 50), (32, 50), (26, 59), True, "middle_width", 12.)
            dimension(symbols, (32, 38), (48, 38), (40, 43), True, "lower_width", 16.)
            dimension(symbols, (0, 30), (0, 75), (-14, 52), False, "rise_total", 45.)
            dimension(symbols, (0, 30), (32, 50), (58, 40), False, "rise_middle", 20.)
            dimension(symbols, (32, 38), (32, 50), (65, 44), False, "step_drop", 12.)
        extrude(model, upper, "Три ступени: глубина 20 мм", 20.)
        result["checks"].append("Оба эскиза полностью определены: H/V, совпадения концов, управляющие размеры; закреплено по одной базовой точке")

        STAGE = "Rebuild and tree check"
        require(doc3d.CompleteRebuildDocument(), "CompleteRebuildDocument")
        require(part.RebuildModel(True), "RebuildModel")
        errors = feature_errors(part)
        require(not errors, f"Feature errors: {errors}")
        result["checks"].append("Полная перестройка выполнена; дерево без ошибок")
        bodies = ksapi.IFeature(part).GetResultBodies()
        require(len(bodies) == 1 and bodies[0].IsSolid(), "Expected one solid body")
        result["checks"].append("Одно твёрдое тело")

        STAGE = "Native CAD volume"
        mass = require(ksapi.IMassInertiaParam(part), "Mass properties")
        mass.SetLengthUnits(c.ksLUMillimetres)
        require(mass.Calculate(), "Calculate mass properties")
        # Native Linux IMassInertiaParam reports this volume in cm³,
        # including after SetLengthUnits(mm); convert the returned unit, not geometry.
        volume = mass.GetVolume() * 1000.
        require(math.isfinite(volume) and volume > 0, "Invalid CAD volume")
        result["volume_mm3"] = volume
        result["volume_passed"] = REFERENCE - .5 <= volume < REFERENCE + .5
        analytical = 60 * 28 * 30 + 20 * (20 * 45 + 12 * 20 + 16 * 8) - math.pi * 6**2 * 28
        result["checks"].append(f"CAD объём {volume:.9f} мм³; эталон 72593±0.5 мм³; аналитический контроль {analytical:.9f} мм³")
        require(abs(volume - analytical) < 1e-5, "CAD volume differs from dimensions")

        STAGE = "SaveAs new native model"
        require(not output.exists(), "Refusing overwrite")
        require(doc.SaveAs(str(output)), "SaveAs")
        require(output.is_file() and output.stat().st_size > 0, "Saved model missing")
        result["model"] = str(output.relative_to(ROOT))
        result["checks"].append("Нативная модель сохранена в новый attempt-*; проверены статус SaveAs и непустой файл")
        result["status"] = "passed" if result["volume_passed"] else "partial"
        STAGE = "Close own saved document"
        require(doc.Close(c.kdDoNotSaveChanges), "Close own document")
        if previous:
            previous.SetActive()
        result["checks"].append("Свой сохранённый документ закрыт; чужие документы не изменялись и не закрывались")
    except Exception as exc:
        result["status"] = "blocked"
        result["limitations"].append(f"Остановлено без повторных CAD-записей; этап {STAGE}: {type(exc).__name__}: {exc}")
    finally:
        (ROOT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0 if result["status"] == "passed" else 1


def finish_existing():
    """Finish only this task's known, unsaved model after a local unit assertion.

    The first run completed every remote call normally; only a local numerical
    assertion failed. This continuation does not rebuild or replace geometry.
    """
    result_path = ROOT / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    stage = "Locate own existing unsaved document"
    try:
        app = require(ksapi.GetKompas(), "API session unavailable")
        doc = require(app.GetActiveDocument(), "No active document")
        require(doc.GetDocumentType() == c.ksDocumentPart and not doc.GetFullPath(),
                "Expected own unsaved part")
        part = require(ksapi.IKompasDocument3D(doc).GetTopPart(), "Top part")
        require(part.GetName() == "1.1 — Ступенчатый кронштейн с отверстием", "Ownership mismatch")
        bodies = ksapi.IFeature(part).GetResultBodies()
        require(len(bodies) == 1 and bodies[0].IsSolid(), "One solid")
        bounds = bodies[0].GetGabarit(0, 0, 0, 0, 0, 0)
        require(bounds[0], "Body bounds")
        require(all(abs(a - b) < 1e-5 for a, b in zip(bounds[1:], (0, 0, 0, 60, 75, 28))),
                f"Unexpected model dimensions: {bounds}")
        require(not feature_errors(part), "Tree errors")
        mass = require(ksapi.IMassInertiaParam(part), "Mass properties")
        require(mass.Calculate(), "Calculate")
        raw = mass.GetVolume()
        volume = raw * 1000.
        analytical = 60 * 28 * 30 + 20 * (20 * 45 + 12 * 20 + 16 * 8) - math.pi * 6**2 * 28
        require(abs(volume - analytical) < 1e-5, "Converted volume check")
        result["volume_mm3"] = volume
        result["volume_passed"] = REFERENCE - .5 <= volume < REFERENCE + .5
        result["checks"] = [check for check in result["checks"] if not check.startswith("CAD объём")]
        result["checks"].append(f"CAD GetVolume={raw:.12f} см³ = {volume:.9f} мм³; габариты B-rep 60×75×28 мм подтверждают масштаб модели")
        result["checks"].append(f"Аналитический объём {analytical:.9f} мм³; округление CAD до целых совпадает с эталоном 72593 мм³")
        result["limitations"] = [item for item in result["limitations"] if not item.startswith("Остановлено")]
        result["limitations"].append("Linux IMassInertiaParam.GetVolume вернул см³ несмотря на SetLengthUnits(mm); применён перевод см³→мм³ ×1000, размеры модели не менялись.")
        result["limitations"].append("После локальной ошибки проверки единиц продолжено сохранение той же собственной детали, без повторного построения.")
        attempt = Path(tempfile.mkdtemp(prefix="attempt-", dir=ROOT))
        output = attempt / "model.m3d"
        stage = "Save own existing model"
        require(not output.exists(), "Refusing overwrite")
        require(doc.SaveAs(str(output)), "SaveAs")
        require(output.is_file() and output.stat().st_size > 0, "Saved model missing")
        result["model"] = str(output.relative_to(ROOT))
        result["checks"].append("Модель сохранена нативно в новый attempt-*; статус SaveAs и непустой файл проверены")
        stage = "Close own saved document"
        require(doc.Close(c.kdDoNotSaveChanges), "Close own saved part")
        result["checks"].append("Свой сохранённый документ закрыт; чужие документы не изменялись и не закрывались")
        result["status"] = "passed" if result["volume_passed"] else "partial"
    except Exception as exc:
        result["status"] = "blocked"
        result["limitations"].append(f"{stage}: {type(exc).__name__}: {exc}; дальнейшие CAD-записи остановлены")
    finally:
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(finish_existing() if sys.argv[1:] == ["--finish-existing"] else main())
