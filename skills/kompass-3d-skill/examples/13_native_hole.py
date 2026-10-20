# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Пластина 60 × 40 × 10 мм: родное глухое отверстие Ø10 × 6 в (12, 7).

Linux v25, Holes3D → IHole3D + IHoleDisposal, без выреза окружностью.
Проверяются геометрия, параметры операции и объём, затем save/reopen.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import math
from pathlib import Path
from tempfile import TemporaryDirectory

import ksapi
from constants import constants as c
from constants3d import constants as c3d


def require(value, message):
    if not value:
        raise RuntimeError(message)
    return value


@contextmanager
def sketch_xoy(part, model):
    sketch = require(model.GetSketchs().Add(), "Эскиз")
    sketch.SetPlane(require(part.GetDefaultObject(c3d.o3d_planeXOY), "Плоскость XOY"))
    require(sketch.Update(), "Плоскость эскиза")
    fragment = require(sketch.BeginEdit(False), "Редактирование эскиза")
    try:
        view = require(fragment.GetViewsAndLayersManager().GetViews().GetActiveView(), "Вид эскиза")
        yield sketch, require(ksapi.IDrawingContainer(view), "Геометрия эскиза")
    finally:
        require(sketch.EndEdit(), "Завершение эскиза")


def rectangle(drawing, x, y, width, height):
    obj = require(drawing.GetRectangles().Add(), "Прямоугольник")
    obj.SetX(x)
    obj.SetY(y)
    obj.SetWidth(width)
    obj.SetHeight(height)
    require(obj.Update(), "Обновление прямоугольника")
    return obj


def feature_errors(part):
    """Проверить все ветви дерева, включая скрытые эскизы."""
    errors, seen = [], set()

    def visit(feature, path):
        if feature.reference in seen:
            return
        seen.add(feature.reference)
        path = [*path, feature.GetName()]
        error = feature.GetObjectError()
        if error:
            errors.append((path, error))
        for child in feature.GetSubFeatures(c.ksOperTree, True, True):
            if child:
                visit(child, path)

    visit(require(ksapi.IFeature(part), "Дерево детали"), [])
    return errors


def face_bounds(face):
    """Габариты ограниченной грани по её рёбрам, не бесконечной поверхности."""
    rims = []
    for edge in face.GetLimitingEdges():
        curve = require(edge.GetMathCurve(), "Математическая кривая ребра")
        result = curve.GetGabarit(0, 0, 0, 0, 0, 0)
        require(result[0], "Габариты ребра")
        bounds = tuple(result[1:])
        require(len(bounds) == 6 and all(math.isfinite(v) for v in bounds),
                "Неконечные габариты ребра")
        rims.append(bounds)
    require(rims, "У грани отсутствуют ограничивающие рёбра")
    return tuple(min(r[i] for r in rims) for i in range(3)) + tuple(
        max(r[i] for r in rims) for i in range(3, 6)
    )


def top_face(part):
    """Найти верхнюю плоскую грань пластины по геометрии, не индексу."""
    faces = []
    feature = require(ksapi.IFeature(part), "Топология пластины")
    for obj in feature.GetModelObjects([c3d.o3d_face]):
        face = require(ksapi.IFace(obj), "Грань пластины")
        if face.IsPlanar():
            bounds = face_bounds(face)
            if all(abs(a - b) <= 1e-5
                   for a, b in zip(bounds, (-30, -20, 10, 30, 20, 10))):
                faces.append(face)
    require(len(faces) == 1, f"Ожидалась одна верхняя грань, получено {len(faces)}")
    return faces[0]


def verify_cylindrical_walls(part, expected, *, tolerance=1e-5):
    """Проверить радиусы, центры и высоту простых цилиндров вдоль Z."""
    feature = require(ksapi.IFeature(part), "Топология детали")
    actual = []
    for obj in feature.GetModelObjects([c3d.o3d_face]):
        face = require(ksapi.IFace(obj), "Грань")
        if not face.IsCylinder():
            continue
        rims = []
        for edge in face.GetLimitingEdges():
            if edge.IsCircle():
                curve = require(edge.GetMathCurve(), "Круговая граница цилиндра")
                bounds = curve.GetGabarit(0, 0, 0, 0, 0, 0)
                require(bounds[0], "Габариты круговой границы")
                rims.append(bounds[1:])
        require(len(rims) == 2, "Ожидались две круговые границы цилиндрической стенки")
        radius = face.GetRadius()
        require(math.isfinite(radius) and radius > 0, "Некорректный радиус цилиндра")
        centers = []
        for xmin, ymin, zmin, xmax, ymax, zmax in rims:
            require(all(math.isfinite(v) for v in (xmin, ymin, zmin, xmax, ymax, zmax)),
                    "Неконечные габариты границы")
            require(abs(zmax - zmin) <= tolerance
                    and abs((xmax - xmin) / 2 - radius) <= tolerance
                    and abs((ymax - ymin) / 2 - radius) <= tolerance,
                    "Граница не является окружностью в плоскости XY")
            centers.append(((xmin + xmax) / 2, (ymin + ymax) / 2, (zmin + zmax) / 2))
        require(math.dist(centers[0][:2], centers[1][:2]) <= tolerance,
                "Ось цилиндра не параллельна Z")
        actual.append((*centers[0][:2], radius,
                       min(p[2] for p in centers), max(p[2] for p in centers)))
    require(len(actual) == len(expected),
            f"Цилиндрические стенки: ожидалось {len(expected)}, получено {len(actual)}")
    for wall in expected:
        matches = [i for i, found in enumerate(actual)
                   if all(abs(a - b) <= tolerance for a, b in zip(found, wall))]
        require(len(matches) == 1, f"Не подтверждены центр, радиус или глубина стенки: {wall}")
        actual.pop(matches[0])


def volume_mm3(part):
    """Нативный расчёт МЦХ детали в мм³, независимо от параметров отверстия."""
    mass = require(ksapi.IMassInertiaParam(part), "МЦХ детали")
    mass.SetLengthUnits(c.ksLUnMM)
    require(mass.Calculate(), "Расчёт МЦХ")
    require(mass.IsActual(), "Неактуальный расчёт МЦХ")
    require(mass.GetLengthUnits() == c.ksLUnMM, "Единицы МЦХ не миллиметры")
    value = mass.GetVolume()
    require(math.isfinite(value) and value > 0, f"Некорректный объём: {value}")
    return value


def build(part, model):
    """Выдавить пластину Z=0…10, затем Holes3D: Ø10, дно Z=4, ось (12, 7)."""
    with sketch_xoy(part, model) as (profile, drawing):
        rectangle(drawing, -30, -20, 60, 40)
    plate = require(model.GetExtrusions().Add(c3d.o3d_bossExtrusion), "Выдавливание пластины")
    plate.SetProfiles([profile])
    plate.SetDirection(c3d.dtNormal)
    require(plate.SetSideParameters(True, c3d.etBlind, 10.0, 0.0, False, None), "Толщина пластины")
    require(plate.Update(), "Построение пластины")
    require(part.RebuildModel(True), "Перестроение пластины")
    # МЦХ впервые считаем только после финальной операции: промежуточный кэш
    # на Linux v25 может остаться актуальным после изменения геометрии.
    base = top_face(part)

    hole = require(require(model.GetHoles3D(), "Коллекция Holes3D").Add(), "Родное отверстие")
    hole.SetName("13 — Глухое Ø10 × 6, центр (12, 7)")
    hole.SetHoleType(c3d.ksHTBase)
    hole.SetDiameter(10.0)
    hole.SetDepthType(c3d.ksDTValue)
    hole.SetDepth(6.0)
    hole.SetEndFaceType(c3d.ksEFFlat)
    disposal = require(ksapi.IHoleDisposal(hole), "Расположение родного отверстия")
    disposal.SetBaseSurface(base)
    disposal.SetPerpendicular(True)
    # Полный режим задаётся ДО положения; все записи относятся к одному hole.
    disposal.SetOffsetType(c3d.ksOffsetByCoords)
    surface = require(ksapi.IPoint3DParamSurface(require(
        disposal.GetPoint3DParamSurface(), "Параметры точки на поверхности"
    )), "IPoint3DParamSurface")
    surface.SetOffset1(12.0)
    surface.SetOffset2(7.0)
    # Upstream измерил False даже при верной позиции. Не подменять геометрическую
    # проверку этим bool; Linux-результат оставляем видимым в диагностике.
    accepted = surface.SetSurfaceObject(base)
    print(f"Point3DParamSurface.SetSurfaceObject: {accepted}")
    require(hole.Update(), "Построение родного отверстия")
    return hole


def validate(part):
    """Проверить конечное тело, native feature, дно, стенку, МЦХ; вернуть bounds tuple.

    Коллекция и все topology references получаются заново: работает и после reopen.
    """
    require(part.RebuildModel(True), "Перестроение")
    feature = require(ksapi.IFeature(part), "Топология детали")
    bodies = feature.GetResultBodies()
    require(len(bodies) == 1, f"Ожидалось одно тело, получено {len(bodies)}")
    require(bodies[0].IsSolid(), "Тело не твёрдое")
    result = bodies[0].GetGabarit(0, 0, 0, 0, 0, 0)
    require(result[0], "Габариты")
    bounds = tuple(result[1:])
    expected = (-30, -20, 0, 30, 20, 10)
    require(len(bounds) == 6 and all(math.isfinite(a) and abs(a - b) <= 1e-5
                                   for a, b in zip(bounds, expected)), f"Габариты: {bounds}")
    errors = feature_errors(part)
    require(not errors, f"Ошибки дерева операций: {errors}")
    verify_cylindrical_walls(part, [(12, 7, 5, 4, 10)])

    bottoms = []
    for obj in feature.GetModelObjects([c3d.o3d_face]):
        face = require(ksapi.IFace(obj), "Грань дна")
        if face.IsPlanar():
            candidate = face_bounds(face)
            if all(abs(a - b) <= 1e-5
                   for a, b in zip(candidate, (7, 2, 4, 17, 12, 4))):
                edges = face.GetLimitingEdges()
                if len(edges) == 1 and edges[0].IsCircle():
                    bottoms.append(face)
    require(len(bottoms) == 1, "Не подтверждено единственное плоское круглое дно Ø10 на Z=4")

    model = require(part.GetModelContainer(), "Контейнер модели после перестроения")
    holes = require(model.GetHoles3D(), "Сохранённая коллекция Holes3D")
    require(holes.GetCount() == 1, f"Ожидалось одно родное отверстие: {holes.GetCount()}")
    hole = require(holes.GetHole3D(0), "Отверстие из коллекции, не build reference")
    require(hole.GetHoleType() == c3d.ksHTBase, "Тип родного отверстия")
    require(hole.GetDepthType() == c3d.ksDTValue, "Отверстие не глухое по значению")
    require(hole.GetEndFaceType() == c3d.ksEFFlat, "Родной параметр дна не плоский")
    for value, expected_value, label in ((hole.GetDiameter(), 10.0, "Диаметр"),
                                         (hole.GetDepth(), 6.0, "Глубина")):
        require(math.isfinite(value) and abs(value - expected_value) <= 1e-5,
                f"{label} родного отверстия: {value}")
    disposal = require(ksapi.IHoleDisposal(hole), "Сохранённое расположение отверстия")
    require(disposal.IsPerpendicular(), "Отверстие не перпендикулярно базовой грани")
    require(disposal.GetOffsetType() == c3d.ksOffsetByCoords, "Не координатное расположение")
    base = require(ksapi.IFace(require(disposal.GetBaseSurface(), "Базовая грань отверстия")),
                   "Сохранённая базовая грань")
    require(base.IsPlanar() and all(abs(a - b) <= 1e-5 for a, b in zip(
        face_bounds(base), (-30, -20, 10, 30, 20, 10)
    )), "База отверстия не верхняя грань пластины")
    surface = require(ksapi.IPoint3DParamSurface(require(
        disposal.GetPoint3DParamSurface(), "Сохранённая точка на поверхности"
    )), "Сохранённый IPoint3DParamSurface")
    for value, expected_value in ((surface.GetOffset1(), 12.0), (surface.GetOffset2(), 7.0)):
        require(math.isfinite(value) and abs(value - expected_value) <= 1e-5,
                f"Смещение родного отверстия: {value}, ожидалось {expected_value}")

    # Независимая аналитика: 60*40*10 − π*5²*6; не вычислять ожидание из readback.
    volume = volume_mm3(part)
    expected_volume = 24000.0 - 150.0 * math.pi
    require(abs(volume - expected_volume) <= 0.01,
            f"Объём: {volume} мм³; ожидалось {expected_volume} мм³")
    return bounds


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Новый файл .m3d; без него — временная деталь")
    args = parser.parse_args(argv)
    output = args.output.expanduser().resolve() if args.output is not None else None
    if output is not None:
        if output.suffix.lower() != ".m3d":
            parser.error("Нужен файл .m3d")
        if output.exists():
            parser.error(f"Файл уже существует: {output}")

    app = require(ksapi.GetKompas(), "Нет запущенной API-сессии КОМПАС")
    previous = app.GetActiveDocument()
    doc = None
    with TemporaryDirectory(prefix="kompas-native-hole-") as directory:
        target = output if output is not None else Path(directory) / "native-hole.m3d"
        try:
            documents = require(app.GetDocuments(), "Документы")
            doc = require(documents.AddWithDefaultSettings(c.ksDocumentPart, True), "Новая деталь")
            part = require(ksapi.IKompasDocument3D(doc).GetTopPart(), "Верхний компонент")
            part.SetName("13 — Родное глухое отверстие")
            model = require(part.GetModelContainer(), "Контейнер модели")
            build(part, model)
            validate(part)
            if target.exists():
                raise FileExistsError(f"Не перезаписываем {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            require(doc.SaveAs(str(target)), "Сохранение")
            require(target.is_file() and target.stat().st_size > 0, "Файл результата отсутствует")
            require(doc.Close(c.kdDoNotSaveChanges), "Закрытие перед reopen")
            doc = None
            # Только собственный новый файл; пользовательские документы не переоткрываются.
            doc = require(documents.Open(str(target), True, False), "Reopen собственной детали")
            part = require(ksapi.IKompasDocument3D(doc).GetTopPart(), "Верхний компонент после reopen")
            bounds = validate(part)
            print(f"Проверено после reopen: {bounds}; файл: {output or 'временная деталь'}")
        finally:
            try:
                if doc is not None:
                    require(doc.Close(c.kdDoNotSaveChanges), "Закрытие собственной детали")
            finally:
                if previous:
                    previous.SetActive()


if __name__ == "__main__":
    main()
