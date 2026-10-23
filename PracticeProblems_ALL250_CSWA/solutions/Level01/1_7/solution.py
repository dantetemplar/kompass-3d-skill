# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Practice Problem 1.7: native KOMPAS feature tree, no exports or edits tests."""
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
TITLE = "Кронштейн с двумя стенками и лапкой"
TREE = "Основание с перемычкой и лапкой 15 → задняя стенка 45 → передняя стойка 30 → верхняя полка 15 → отверстие Ø20 → отверстие Ø13"


class ModelError(Exception):
    pass


def need(value, message):
    if not value:
        raise ModelError(message)
    return value


def relation(obj, kind, *, partners=(), index=None, partner_index=None,
             name=None, value=None):
    item = need(obj.NewConstraint(), "NewConstraint")
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
    need(item.Create() and item.IsValid(), f"Связь {kind}: {name}")
    return item


def drive(dim, name, value):
    relation(dim, c.ksCFixedDim)
    relation(dim, c.ksCDimWithVariable, name=name, value=value)


def length(symbols, a, b, horizontal, name, value):
    dim = need(symbols.GetLineDimensions().Add(), "Линейный размер")
    dim.SetX1(a[0]); dim.SetY1(a[1])
    dim.SetX2(b[0]); dim.SetY2(b[1])
    dim.SetX3((a[0] + b[0]) / 2 + (0 if horizontal else 8))
    dim.SetY3((a[1] + b[1]) / 2 + (8 if horizontal else 0))
    dim.SetOrientation(c.ksLinDHorizontal if horizontal else c.ksLinDVertical)
    need(dim.Update(), "Обновление линейного размера")
    need(dim.Associate(), "Ассоциация линейного размера")
    drive(dim, name, value)


@contextmanager
def editing(sketch):
    fragment = need(sketch.BeginEdit(False), "BeginEdit")
    unknown = False
    try:
        fragment.SetParametricMode(True)
        need(fragment.IsParametricMode(), "Параметрический режим")
        view = need(fragment.GetViewsAndLayersManager().GetViews().GetActiveView(), "Вид")
        yield ksapi.IDrawingContainer(view), ksapi.ISymbols2DContainer(view)
    except ModelError:
        raise
    except BaseException:
        unknown = True
        raise
    finally:
        if not unknown:
            need(sketch.EndEdit(), "EndEdit")
    state = sketch.GetConstraintsState()
    print(json.dumps({"sketch": sketch.GetName(), "constraints_state": state}), flush=True)
    need(state == c.ksStateWellConstrained, f"Эскиз не полностью определён: {state}")


def sketch(model, plane, name):
    obj = need(model.GetSketchs().Add(), "Новый эскиз")
    obj.SetName(name)
    obj.SetPlane(plane)
    need(obj.Update(), "Опора эскиза")
    return obj


def segment(drawing, a, b):
    line = need(drawing.GetLineSegments().Add(), "Отрезок")
    line.SetX1(a[0]); line.SetY1(a[1]); line.SetX2(b[0]); line.SetY2(b[1])
    need(line.Update(), "Обновление отрезка")
    return line


def polygon(model, plane, vertices, names, name):
    obj = sketch(model, plane, name)
    with editing(obj) as (drawing, symbols):
        lines = [segment(drawing, a, b) for a, b in zip(vertices, vertices[1:] + vertices[:1])]
        for i, line in enumerate(lines):
            relation(line, c.ksCMergePoints, partners=[lines[(i + 1) % len(lines)]], index=1, partner_index=0)
            a, b = vertices[i], vertices[(i + 1) % len(vertices)]
            relation(line, c.ksCHorizontal if a[1] == b[1] else c.ksCVertical)
        # One point anchors the contour; every remaining freedom is dimensional.
        relation(lines[0], c.ksCFixedPoint, index=0)
        for i, variable in enumerate(names):
            a, b = vertices[i], vertices[i + 1]
            length(symbols, a, b, a[1] == b[1], variable, math.dist(a, b))
    return obj


def rectangle(model, plane, x, y, w, h, prefix, name):
    return polygon(model, plane, [(x, y), (x+w, y), (x+w, y+h), (x, y+h)],
                   [prefix + "_width", prefix + "_thickness"], name)


def offset(part, z):
    plane = need(ksapi.IAuxiliaryGeomContainer(part).GetPlanes3D().Add(c3d.o3d_planeOffset), "Смещённая плоскость")
    plane.SetName(f"База Z={z:g}")
    param = need(ksapi.IPlane3DByOffset(plane), "Параметры плоскости")
    param.SetBasePlane(part.GetDefaultObject(c3d.o3d_planeXOY))
    param.SetOffset(abs(z)); param.SetDirection(z >= 0)
    need(param.Update(), "Построение плоскости")
    return plane


def extrude(model, profile, depth, name, *, cut=False, positive_normal=True):
    op = need(model.GetExtrusions().Add(c3d.o3d_cutExtrusion if cut else c3d.o3d_bossExtrusion), "Выдавливание")
    op.SetName(name); op.SetProfiles([profile])
    # Cuts use the side opposite to boss extrusions in the Linux API.
    normal = positive_normal != cut
    op.SetDirection(c3d.dtNormal if normal else c3d.dtReverse)
    need(op.SetSideParameters(normal, c3d.etBlind, depth, 0.0, False, None), "Глубина выдавливания")
    need(op.Update(), f"Построение: {name}")
    return op


def hole(model, plane, x, y, radius, name, center_dimension=None):
    obj = sketch(model, plane, name)
    with editing(obj) as (drawing, symbols):
        circle = need(drawing.GetCircles().Add(), "Окружность")
        circle.SetXc(x); circle.SetYc(y); circle.SetRadius(radius)
        need(circle.Update(), "Обновление окружности")
        if center_dimension is None:
            relation(circle, c.ksCFixedPoint, index=0)
        else:
            axis = segment(drawing, (0, 0), (x, y))
            axis.SetStyle(c.ksCSConstruction)
            need(axis.Update(), "Вспомогательная ось")
            relation(axis, c.ksCFixedPoint, index=0)
            relation(axis, c.ksCHorizontal)
            relation(circle, c.ksCMergePoints, partners=[axis], index=0, partner_index=1)
            length(symbols, (0, 0), (x, y), True, center_dimension, x)
        dim = need(symbols.GetRadialDimensions().Add(), "Радиальный размер")
        dim.SetBaseObject(circle); dim.SetXc(x); dim.SetYc(y); dim.SetRadius(radius)
        dim.SetAngle(35.0)  # IRadialDimension.SetAngle uses degrees.
        need(dim.Update(), "Обновление радиального размера")
        drive(dim, "radius_" + str(int(radius * 2)), radius)
    return obj


def check_tree(part):
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
    need(not errors, f"Ошибки дерева: {errors}")


def run():
    attempt = Path(tempfile.mkdtemp(prefix="attempt-", dir=ROOT))
    target = attempt / "model.m3d"
    result_path = ROOT / "result.json"
    if result_path.exists():
        # Retain the previous report byte-for-byte; never overwrite attempt outputs.
        result_path.rename(attempt / "previous-result.json")
    result = {"task": "1.7", "status": "failed", "title": TITLE, "script": "solution.py",
              "model": None, "volume_mm3": None, "reference_volume": 148172,
              "reference_units": "mm3", "volume_passed": None, "checks": [],
              "limitations": ["Пробные изменения размеров и повторное открытие не выполнялись.",
                              "Контуры связаны внутри эскизов; одинаковые размеры и базовые точки разных эскизов не объединены общей формулой.",
                              "Положение начала координат принято в центре Ø20 на внутренней плоскости задней стенки по красным осям чертежа."],
              "tree": TREE}
    doc = None
    unknown = False
    exit_code = 1
    try:
        need(not target.exists(), "Целевой файл уже существует")
        app = need(ksapi.GetKompas(), "Нет действующей API-сессии")
        doc = need(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart, True), "Собственный документ")
        doc3d = need(ksapi.IKompasDocument3D(doc), "3D документ")
        part = need(doc3d.GetTopPart(), "Деталь")
        part.SetName(TITLE)
        model = need(part.GetModelContainer(), "Контейнер модели")
        low, mid, high = offset(part, -30), offset(part, -15), offset(part, 15)
        # The front wall is an inverted L: no lower rail below its 75 mm opening.
        # y=15 is the end of the 30 mm tab; inner front face y=38 is 23 mm farther.
        vertices = [(-50,-15), (75,-15), (75,15), (50,15), (50,53),
                    (25,53), (25,0), (-50,0)]
        profile = polygon(model, low, vertices,
                          ["overall_length", "tab_width", "tab_extension", "remaining_width",
                           "front_pillar_width", "inside_to_front_outer"],
                          "План основания и лапки")
        extrude(model, profile, 15, "Основание и лапка 15")
        profile = rectangle(model, mid, -50, -15, 100, 15, "rear", "План задней стенки")
        extrude(model, profile, 45, "Задняя стенка до высоты 60")
        profile = rectangle(model, mid, 25, 38, 25, 15, "pillar", "План передней стойки")
        extrude(model, profile, 30, "Передняя стойка до высоты 45")
        profile = rectangle(model, high, -50, 38, 100, 15, "upper", "План верхней полки")
        extrude(model, profile, 15, "Передняя верхняя полка до высоты 60")
        vertical = need(part.GetDefaultObject(c3d.o3d_planeXOZ), "Плоскость XOZ")
        profile = hole(model, vertical, 0, 0, 10, "Отверстие Ø20 на начале координат")
        points = [profile.GetPoint3D(u, v, 0, 0, 0) for u, v in [(0,0), (1,0), (0,1)]]
        need(all(p[0] for p in points), "Система координат XOZ")
        origin, px, py = [p[1:] for p in points]
        u = [a-b for a,b in zip(px,origin)]; v = [a-b for a,b in zip(py,origin)]
        normal = [u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0]]
        need(abs(normal[1]) > 0.999, f"Нормаль XOZ: {normal}")
        print(json.dumps({"XOZ_origin": origin, "u": u, "v": v, "normal": normal}), flush=True)
        extrude(model, profile, 15, "Сквозное отверстие Ø20", cut=True, positive_normal=normal[1] < 0)
        profile = hole(model, low, 63, 0, 6.5, "Отверстие лапки Ø13, 12 от торца", "tab_hole_x")
        extrude(model, profile, 15, "Сквозное отверстие лапки Ø13", cut=True)
        result["checks"].append("Все шесть эскизов после EndEdit имеют ksStateWellConstrained; созданы H/V, совпадения, минимальные базовые фиксации и управляющие размеры.")
        need(doc3d.CompleteRebuildDocument(), "Полное перестроение")
        need(part.RebuildModel(True), "Перестроение детали")
        check_tree(part)
        result["checks"].append("Полное перестроение выполнено; рекурсивный обход дерева не обнаружил ошибок операций.")
        bodies = ksapi.IFeature(part).GetResultBodies()
        need(len(bodies) == 1 and bodies[0].IsSolid(), "Ожидалось одно твёрдое тело")
        result["checks"].append("Результат содержит ровно одно твёрдое тело.")
        mass = need(ksapi.IMassInertiaParam(part), "МЦХ детали")
        mass.SetLengthUnits(c.ksLUnMM)
        units = mass.GetLengthUnits()
        need(units == c.ksLUnMM, f"Неверные единицы МЦХ: {units}")
        need(mass.Calculate(), "Расчёт МЦХ")
        volume = mass.GetVolume()
        need(math.isfinite(volume) and volume > 0, "Неверный объём")
        result["volume_mm3"] = volume
        result["volume_passed"] = 148171.5 <= volume < 148172.5
        result["checks"].append(f"IMassInertiaParam: SetLengthUnits(ksLUnMM), GetLengthUnits={units}; Calculate выполнен, CAD объём {volume:.9f} мм³.")
        result["checks"].append(f"Интервал эталона [148171.5,148172.5) мм³: {'пройден' if result['volume_passed'] else 'не пройден'}.")
        expected = 100*15*60 + (100*60 - 75*45)*15 + 25*38*15 + 25*30*15 - math.pi*(10**2+6.5**2)*15
        result["checks"].append(f"Независимая формула из размеров чертежа: {expected:.9f} мм³; разность CAD {volume-expected:.9g} мм³.")
        need(not target.exists(), "Целевой файл появился до сохранения")
        need(doc.SaveAs(str(target)), "SaveAs")
        need(target.is_file() and target.stat().st_size > 0, "Файл модели отсутствует")
        need(Path(doc.GetFullPath()).resolve() == target, "Путь сохранённого документа")
        result["model"] = str(target.relative_to(ROOT))
        result["checks"].append("SaveAs выполнен в новый attempt-*; проверены GetFullPath и наличие непустого model.m3d.")
        result["status"] = "passed" if result["volume_passed"] else "partial"
        exit_code = 0
    except ModelError as exc:
        result["limitations"].append(str(exc))
        traceback.print_exc()
        # Known synchronous rejection: preserve any constructed native model.
        if doc is not None and not target.exists():
            try:
                if doc.SaveAs(str(target)) and target.is_file():
                    result["model"] = str(target.relative_to(ROOT))
                    result["status"] = "partial"
                    result["checks"].append("Незавершённая собственная модель сохранена после известного отказа проверки.")
            except BaseException:
                unknown = True
                result["status"] = "blocked"
                result["limitations"].append("Неизвестный исход сохранения; дальнейшие обращения к CAD остановлены.")
        exit_code = 0 if result["status"] == "partial" else 1
    except BaseException as exc:
        unknown = True
        result["status"] = "blocked"
        result["limitations"].append(f"Неизвестный исход API/вызова: {type(exc).__name__}: {exc}; новых записей и перезапуска нет.")
        traceback.print_exc()
    finally:
        if doc is not None and not unknown:
            try:
                need(doc.Close(c.kdDoNotSaveChanges), "Закрытие собственного документа")
                result["checks"].append("Собственный документ закрыт в finally; чужие документы не изменялись и не закрывались.")
            except BaseException as exc:
                result["status"] = "blocked"
                result["limitations"].append(f"Закрытие собственного документа не подтверждено: {exc}")
                exit_code = 1
        with result_path.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(run())
