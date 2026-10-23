# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Practice Problem 1.9: native dimension-driven KOMPAS-3D part.

Drawing interpretation: 175 x 100 envelope; bottom corner recesses 40 x 22
and 30 deep, middle web 25 thick, upper corner bosses 40 x 22 and 25 high.
No geometry is derived from the reference volume. No dimension perturbations.
"""
from __future__ import annotations

import ast
import json
import math
from pathlib import Path
import tempfile
import traceback

import ksapi
from constants import constants as c
from constants3d import constants as c3d

ROOT = Path(__file__).resolve().parent
TREE = "Эскиз 175×100 → основание 55 → эскиз 4×40×22 → нижние вырезы 30 → плоскость Z=55 → эскиз 4×40×22 → верхние выступы 25"
INFLIGHT = False
LAST_CALL = ""


def api(method, *args):
    """An exception inside a native call leaves its outcome unknown: stop writing."""
    global INFLIGHT, LAST_CALL
    LAST_CALL = method.__qualname__
    INFLIGHT = True
    result = method(*args)
    INFLIGHT = False
    return result


def need(value, message):
    if not value:
        raise RuntimeError(message)
    return value


def link(obj, kind, partners=(), index=None, partner_index=None, name=None, value=None):
    relation = need(api(obj.NewConstraint), "NewConstraint")
    api(relation.SetConstraintType, kind)
    if partners:
        api(relation.SetPartners, list(partners))
    if index is not None:
        api(relation.SetIndex, index)
    if partner_index is not None:
        api(relation.SetPartnerIndex, partner_index)
    if name is not None:
        api(relation.SetVariable, name)
    if value is not None:
        api(relation.SetConstraintValue, value)
    need(api(relation.Create) and api(relation.IsValid), f"Constraint {kind}: {name}")


def dimension(symbols, p, q, horizontal, name, value, label):
    dims = need(api(symbols.GetLineDimensions), "Line dimensions")
    dim = need(api(dims.Add), "Dimension")
    for method, val in ((dim.SetX1, p[0]), (dim.SetY1, p[1]),
                        (dim.SetX2, q[0]), (dim.SetY2, q[1]),
                        (dim.SetX3, label[0]), (dim.SetY3, label[1])):
        api(method, float(val))
    api(dim.SetOrientation, c.ksLinDHorizontal if horizontal else c.ksLinDVertical)
    need(api(dim.Update), "Dimension Update")
    need(api(dim.Associate), f"Dimension association {name}")
    relations = api(dim.GetConstraints)
    need(all(any(api(r.IsValid) and api(r.GetConstraintType) == c.ksCMergePoints
                     and api(r.GetIndex) == i for r in relations) for i in (0, 1)),
         f"Witness-point associations {name}")
    link(dim, c.ksCFixedDim)
    link(dim, c.ksCDimWithVariable, name=name, value=float(value))


def rectangle(drawing, x, y, w, h):
    points = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    lines = []
    collection = need(api(drawing.GetLineSegments), "Line segments")
    for a, b in zip(points, points[1:] + points[:1]):
        line = need(api(collection.Add), "Line")
        for method, val in ((line.SetX1, a[0]), (line.SetY1, a[1]),
                            (line.SetX2, b[0]), (line.SetY2, b[1])):
            api(method, float(val))
        need(api(line.Update), "Line Update")
        lines.append(line)
    for i, line in enumerate(lines):
        link(line, c.ksCMergePoints, [lines[(i + 1) % 4]], 1, 0)
        link(line, c.ksCHorizontal if i % 2 == 0 else c.ksCVertical)
    return lines


def sketch(model, plane, name, corners, checks):
    sketches = need(api(model.GetSketchs), "Sketch collection")
    obj = need(api(sketches.Add), "Sketch")
    api(obj.SetName, name)
    api(obj.SetPlane, plane)
    need(api(obj.Update), "Sketch plane")
    axes = [api(obj.GetPoint3D, x, y, 0., 0., 0.) for x, y in ((0., 0.), (1., 0.), (0., 1.))]
    need(all(row[0] for row in axes), "Sketch coordinate mapping")
    origin, u, v = [row[1:] for row in axes]
    need(all(abs(a - b) < 1e-8 for a, b in zip(u, (origin[0] + 1, origin[1], origin[2])))
         and all(abs(a - b) < 1e-8 for a, b in zip(v, (origin[0], origin[1] + 1, origin[2]))),
         f"Expected XY sketch axes: {axes}")
    fragment = need(api(obj.BeginEdit, False), "BeginEdit")
    try:
        api(fragment.SetParametricMode, True)
        need(api(fragment.IsParametricMode), "Parametric mode")
        manager = api(fragment.GetViewsAndLayersManager)
        views = api(manager.GetViews)
        view = need(api(views.GetActiveView), "Sketch view")
        drawing = need(api(ksapi.IDrawingContainer, view), "Drawing")
        symbols = need(api(ksapi.ISymbols2DContainer, view), "Symbols")
        if not corners:
            r = rectangle(drawing, 0, 0, 175, 100)
            link(r[0], c.ksCFixedPoint, index=0)
            dimension(symbols, (0, 0), (175, 0), True, "overall_length", 175, (85, -12))
            dimension(symbols, (175, 0), (175, 100), False, "overall_width", 100, (190, 50))
        else:
            rs = [rectangle(drawing, x, y, 40, 22) for x, y in ((0, 0), (135, 0), (0, 78), (135, 78))]
            # Only one base vertex is anchored; no entire line or contour is fixed.
            link(rs[0][0], c.ksCFixedPoint, index=0)
            for r in rs[1:]:
                link(r[0], c.ksCEqualLength, [rs[0][0]])
                link(r[1], c.ksCEqualLength, [rs[0][1]])
            # Rows and columns retain the rectangular corner layout.
            link(rs[1][0], c.ksCHAlignPoints, [rs[0][0]], 0, 0)
            link(rs[2][0], c.ksCVAlignPoints, [rs[0][0]], 0, 0)
            link(rs[3][0], c.ksCVAlignPoints, [rs[1][0]], 0, 0)
            link(rs[3][0], c.ksCHAlignPoints, [rs[2][0]], 0, 0)
            prefix = "upper_" if name.startswith("06") else "lower_"
            dimension(symbols, (0, 0), (40, 0), True, prefix + "corner_length", 40, (20, -10))
            dimension(symbols, (40, 0), (40, 22), False, prefix + "corner_width", 22, (52, 11))
            dimension(symbols, (0, 0), (175, 0), True, prefix + "layout_length", 175, (85, -22))
            dimension(symbols, (0, 0), (0, 100), False, prefix + "layout_width", 100, (-16, 50))
    finally:
        if not INFLIGHT:
            need(api(obj.EndEdit), "EndEdit")
    state = api(obj.GetConstraintsState)
    checks.append(f"Эскиз «{name}»: GetConstraintsState={state}; H/V, совпадения, управляющие размеры; одна базовая точка.")
    need(state == c.ksStateWellConstrained, f"Sketch not fully constrained: {name}: {state}")
    return obj


def extrusion(model, profile, depth, name, cut=False):
    collection = need(api(model.GetExtrusions), "Extrusions")
    operation = need(api(collection.Add, c3d.o3d_cutExtrusion if cut else c3d.o3d_bossExtrusion), "Extrusion")
    api(operation.SetName, name)
    api(operation.SetProfiles, [profile])
    api(operation.SetDirection, c3d.dtReverse if cut else c3d.dtNormal)
    need(api(operation.SetSideParameters, not cut, c3d.etBlind, float(depth), 0., False, None), "Extrusion depth")
    need(api(operation.Update), f"Build {name}")
    return operation


def feature_errors(part):
    root = need(api(ksapi.IFeature, part), "Feature root")
    seen, errors = set(), []

    def visit(item):
        if item.reference in seen:
            return
        seen.add(item.reference)
        error = api(item.GetObjectError)
        if error:
            errors.append([api(item.GetName), error])
        for child in api(item.GetSubFeatures, c.ksOperTree, True, True):
            if child:
                visit(child)

    visit(root)
    return root, errors, len(seen)


def main():
    ast.parse(Path(__file__).read_text(encoding="utf-8"))
    attempt = Path(tempfile.mkdtemp(prefix="attempt-", dir=ROOT))
    output = attempt / "model.m3d"
    result = {"task": "1.9", "status": "failed", "title": "Пластина с угловыми выступами и вырезами",
              "script": "solution.py", "model": None, "volume_mm3": None,
              "reference_volume": 944900, "reference_units": "mm3", "volume_passed": None,
              "checks": ["Самостоятельный solution.py проверен ast.parse до подключения API."],
              "limitations": ["Верхний и нижний наборы имеют собственные размерные сети; сквозные межэскизные выражения не заданы.",
                              "Глубины 55, 30 и 25 мм и положение плоскости Z=55 — отдельные параметры операций, без общего выражения толщины перемычки.",
                              "Красное обозначение начала координат на предоставленном JPG не различимо; начало принято в нижнем углу габарита на нижней плоскости.",
                              "Пробные изменения размеров не выполнялись."], "tree": TREE}
    doc = app = previous = None
    built = saved = False
    try:
        need(not output.exists() and not output.is_symlink(), "New model path")
        app = need(api(ksapi.GetKompas), "Нет действующей API-сессии; автозапуск запрещён")
        previous = api(app.GetActiveDocument)
        documents = api(app.GetDocuments)
        doc = need(api(documents.AddWithDefaultSettings, c.ksDocumentPart, True), "Own new document")
        doc3d = need(api(ksapi.IKompasDocument3D, doc), "3D document")
        part = need(api(doc3d.GetTopPart), "Top part")
        api(part.SetName, "1.9 Пластина с угловыми выступами и вырезами")
        model = need(api(part.GetModelContainer), "Model container")
        xy = need(api(part.GetDefaultObject, c3d.o3d_planeXOY), "XY plane")
        base = sketch(model, xy, "01 Габарит основания 175 × 100", False, result["checks"])
        extrusion(model, base, 55, "02 Основание 30 + 25 = 55")
        bottom = sketch(model, xy, "03 Четыре одинаковых нижних угла 40 × 22", True, result["checks"])
        extrusion(model, bottom, 30, "04 Нижние угловые вырезы 30", cut=True)
        auxiliary = need(api(ksapi.IAuxiliaryGeomContainer, part), "Auxiliary geometry")
        planes = api(auxiliary.GetPlanes3D)
        plane = need(api(planes.Add, c3d.o3d_planeOffset), "Offset plane")
        api(plane.SetName, "05 Верх перемычки Z=55")
        offset = need(api(ksapi.IPlane3DByOffset, plane), "Offset interface")
        api(offset.SetBasePlane, xy)
        api(offset.SetOffset, 55.)
        api(offset.SetDirection, True)
        need(api(offset.Update), "Offset plane Update")
        top = sketch(model, plane, "06 Четыре одинаковых выступа 40 × 22", True, result["checks"])
        extrusion(model, top, 25, "07 Верхние угловые выступы 25")
        built = True
        need(api(doc3d.CompleteRebuildDocument), "CompleteRebuildDocument")
        need(api(part.RebuildModel, True), "RebuildModel")
        root, errors, count = feature_errors(part)
        result["checks"].append(f"Перестроение выполнено; рекурсивно проверено {count} объектов дерева; ошибки: {errors}.")
        need(not errors, f"Feature errors: {errors}")
        bodies = api(root.GetResultBodies)
        need(len(bodies) == 1 and api(bodies[0].IsSolid), "Exactly one solid body")
        result["checks"].append("Результат — ровно одно твёрдое тело.")
        inertia = need(api(ksapi.IMassInertiaParam, part), "Mass/inertia")
        api(inertia.SetLengthUnits, c.ksLUnMM)
        need(api(inertia.GetLengthUnits) == c.ksLUnMM, "Millimetres readback before Calculate")
        need(api(inertia.Calculate), "Mass/inertia Calculate")
        need(api(inertia.IsActual), "Actual mass properties")
        units = api(inertia.GetLengthUnits)
        need(units == c.ksLUnMM, "Millimetres readback after Calculate")
        volume = api(inertia.GetVolume)
        need(math.isfinite(volume) and volume > 0, "Finite positive CAD volume")
        result["volume_mm3"] = volume
        result["volume_passed"] = 944899.5 <= volume < 944900.5
        result["checks"].append(f"IMassInertiaParam.Calculate/IsActual; GetLengthUnits={units}=ksLUnMM до/после расчёта; CAD объём {volume:.12f} мм³.")
        result["checks"].append(f"Интервал эталона [944899.5,944900.5): {result['volume_passed']}.")
        analytic = 175 * 100 * (30 + 25) - 4 * 40 * 22 * 30 + 4 * 40 * 22 * 25
        result["checks"].append(f"Независимая формула из размеров чертежа: {analytic} мм³; разность CAD {volume - analytic:.12g} мм³.")
        need(not output.exists() and not output.is_symlink(), "SaveAs target must not exist")
        need(api(doc.SaveAs, str(output)), "SaveAs")
        need(output.is_file() and output.stat().st_size > 0, "Nonempty native model")
        need(Path(api(doc.GetFullPath)).resolve() == output.resolve(), "Saved path readback")
        saved = True
        result["model"] = str(output.relative_to(ROOT))
        result["checks"].append("SaveAs успешен: новый непустой model.m3d, GetFullPath подтверждён; экспорт не выполнялся.")
        result["status"] = "passed" if result["volume_passed"] else "partial"
        if not result["volume_passed"]:
            result["limitations"].append("CAD-объём вне интервала эталона; собственная модель сохранена без подгонки.")
    except Exception as exc:
        traceback.print_exc()
        result["status"] = "blocked" if INFLIGHT else "failed"
        result["limitations"].append(f"{type(exc).__name__}: {exc}; последний вызов: {LAST_CALL}.")
        if INFLIGHT:
            result["limitations"].append("Исход нативного вызова неизвестен: никаких новых CAD-записей, сохранения или закрытия не выполняется.")
        elif built and doc is not None and not saved:
            need(not output.exists() and not output.is_symlink(), "Recovery model path")
            if api(doc.SaveAs, str(output)) and output.is_file() and output.stat().st_size > 0:
                saved = True
                result["model"] = str(output.relative_to(ROOT))
                result["status"] = "partial"
                result["checks"].append("Собственная построенная модель сохранена после незавершённой проверки.")
    finally:
        if doc is not None and not INFLIGHT:
            need(api(doc.Close, c.kdDoNotSaveChanges), "Close own document")
            result["checks"].append("Собственный документ закрыт в finally; чужие документы не изменялись и не закрывались.")
            if previous:
                api(previous.SetActive)
        text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        (attempt / "result.json").write_text(text, encoding="utf-8")
        (ROOT / "result.json").write_text(text, encoding="utf-8")
        print(text, flush=True)
    return 0 if result["status"] in ("passed", "partial") else 1


if __name__ == "__main__":
    raise SystemExit(main())
