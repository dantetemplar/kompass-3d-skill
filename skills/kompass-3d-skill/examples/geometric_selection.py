# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Селекторы аналитических граней/окружностей; запуск — проба на своей детали.

Не импортировать из скилла в рабочий макрос: скопировать нужные функции.
Координаты в системе детали, мм; углы в радианах. Нормали без знака.
Цилиндры: полные круговые торцы и прямые швы, не произвольные обрезки.
"""
import json
import math

import ksapi
from constants import constants as c
from constants3d import constants as c3d


def require(value, message):
    if not value:
        raise RuntimeError(message)
    return value


def vector(values):
    values = tuple(values)
    if len(values) != 3 or not all(math.isfinite(v) for v in values):
        raise ValueError(f"Некорректный вектор: {values}")
    return values


def output_point(result, label):
    require(result[0], label)
    return vector(result[1:])


def subtract(a, b):
    return tuple(x - y for x, y in zip(a, b))


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def unit(values):
    values = vector(values)
    length = math.hypot(*values)
    if not math.isfinite(length) or length == 0:
        raise ValueError("Нулевое или неконечное направление")
    return tuple(v / length for v in values)


def tolerances(length_tol, angle_tol):
    if not math.isfinite(length_tol) or length_tol <= 0:
        raise ValueError("length_tol должен быть положительным, мм")
    if not math.isfinite(angle_tol) or not 0 < angle_tol < math.pi / 2:
        raise ValueError("angle_tol должен быть между 0 и pi/2, радианы")


def parallel(a, b, angle_tol):
    """Сравнить неориентированные оси: n и -n задают одну плоскость/ось."""
    return math.atan2(math.hypot(*cross(a, b)), abs(dot(a, b))) <= angle_tol


def placement_geometry(geometry):
    placement = require(geometry.GetPlacement(), "Локальная система аналитической геометрии")
    origin = output_point(placement.GetOrigin(0., 0., 0.), "Начало ЛСК")
    axis = unit(output_point(placement.GetVector(c3d.o3d_axisOZ, 0., 0., 0.), "Ось Z ЛСК"))
    return origin, axis


def topology(part, body, kind):
    """Свежая выборка с принадлежностью ровно заданному текущему телу."""
    feature = require(ksapi.IFeature(part), "Топология детали")
    bodies = feature.GetResultBodies()
    require(any(item.reference == body.reference for item in bodies), "Тело не в текущем результате детали")
    interface = ksapi.IFace if kind == c3d.o3d_face else ksapi.IEdge
    for obj in feature.GetModelObjects([kind]):
        obj = require(interface(obj), "Интерфейс топологии")
        owner = require(obj.GetBody(), "Тело объекта")
        if owner.reference == body.reference:
            yield obj


def positive_radius(radius):
    if not math.isfinite(radius) or radius <= 0:
        raise ValueError(f"Некорректный радиус: {radius}")
    return radius


def circle_geometry(edge):
    curve = require(edge.GetMathCurve(), "Математическая окружность")
    center = output_point(curve.GetCentre(0., 0., 0.), "Центр окружности")
    _, normal = placement_geometry(curve)
    return center, normal, positive_radius(curve.GetRadius())


def unique(candidates, wanted, predicate):
    """Никакого ranking/fallback: ноль или несколько совпадений — диагностика."""
    matches = [item for item in candidates if predicate(item[1])]
    if len(matches) != 1:
        report = {"wanted": wanted, "matches": len(matches),
                  "candidates": [features for _, features in candidates]}
        raise ValueError("Неоднозначный или пустой выбор: " + json.dumps(report, ensure_ascii=False))
    return matches[0][0]


def select_plane(part, body, *, point, normal, length_tol, angle_tol):
    """Плоскость через point, normal без знака. Не тест попадания point в контур."""
    tolerances(length_tol, angle_tol)
    point, normal = vector(point), unit(normal)
    candidates = []
    for face in topology(part, body, c3d.o3d_face):
        if face.IsPlanar():
            origin, direction = placement_geometry(require(face.GetMathSurface(), "Плоская поверхность"))
            candidates.append((face, {"point": origin, "normal": direction,
                                      "plane_distance": abs(dot(subtract(point, origin), direction))}))
    return unique(candidates, {"point": point, "normal": normal, "length_tol": length_tol,
                               "angle_tol": angle_tol},
                  lambda item: parallel(item["normal"], normal, angle_tol)
                  and item["plane_distance"] <= length_tol)


def select_circle(part, body, *, center, radius, normal, length_tol, angle_tol):
    """Только целые окружности IEdge.IsCircle(), не дуги и не эллипсы."""
    tolerances(length_tol, angle_tol)
    center, normal, radius = vector(center), unit(normal), positive_radius(radius)
    candidates = []
    for edge in topology(part, body, c3d.o3d_edge):
        if edge.IsCircle():
            origin, direction, found_radius = circle_geometry(edge)
            candidates.append((edge, {"center": origin, "normal": direction, "radius": found_radius}))
    return unique(candidates, {"center": center, "normal": normal, "radius": radius,
                               "length_tol": length_tol, "angle_tol": angle_tol},
                  lambda item: math.dist(item["center"], center) <= length_tol
                  and abs(item["radius"] - radius) <= length_tol
                  and parallel(item["normal"], normal, angle_tol))


def cylinder_span(face, axis_point, axis, length_tol, angle_tol):
    """Точные осевые экстремумы для полных круговых торцов и прямых швов.

    Для наклонных/сплайновых обрезок нужен другой маршрут; не заменять AABB.
    """
    projections = []
    for edge in face.GetLimitingEdges():
        if edge.IsCircle():
            center, normal, _ = circle_geometry(edge)
            if not parallel(normal, axis, angle_tol):
                raise ValueError("Торец цилиндра не перпендикулярен запрошенной оси")
            if math.hypot(*cross(subtract(center, axis_point), axis)) > length_tol:
                raise ValueError("Торец цилиндра не соосен запрошенной оси")
            projections.append(dot(subtract(center, axis_point), axis))
        elif edge.IsStraight():
            for start in (True, False):
                point = output_point(edge.GetPoint(start, 0., 0., 0.), "Конец прямого шва")
                projections.append(dot(subtract(point, axis_point), axis))
        else:
            raise ValueError("Неподдерживаемая обрезка цилиндра: нужны целые окружности/прямые швы")
    require(projections, "Нет границ цилиндрической грани")
    return min(projections), max(projections)


def select_cylinder(part, body, *, radius, axis_point, axis, span, length_tol, angle_tol):
    """span — осевые координаты от axis_point вдоль заданного axis, в мм."""
    tolerances(length_tol, angle_tol)
    radius, axis_point, axis = positive_radius(radius), vector(axis_point), unit(axis)
    span = tuple(span)
    if len(span) != 2 or not all(math.isfinite(v) for v in span) or span[0] >= span[1]:
        raise ValueError("Нужен возрастающий конечный span из двух осевых координат")
    candidates = []
    for face in topology(part, body, c3d.o3d_face):
        if not face.IsCylinder():
            continue
        origin, direction = placement_geometry(require(face.GetMathSurface(), "Цилиндрическая поверхность"))
        features = {"radius": positive_radius(face.GetRadius()), "axis_point": origin, "axis": direction,
                    "axis_distance": math.hypot(*cross(subtract(origin, axis_point), axis))}
        # Границы читаем только у геометрически подходящих опорных цилиндров.
        support_matches = (abs(features["radius"] - radius) <= length_tol
                           and parallel(direction, axis, angle_tol)
                           and features["axis_distance"] <= length_tol)
        features["span"] = cylinder_span(face, axis_point, axis, length_tol, angle_tol) if support_matches else None
        candidates.append((face, features))
    return unique(candidates, {"radius": radius, "axis_point": axis_point, "axis": axis, "span": span,
                               "length_tol": length_tol, "angle_tol": angle_tol},
                  lambda item: item["span"] is not None
                  and all(abs(a - b) <= length_tol for a, b in zip(item["span"], span)))


def build(part, model):
    """Собственная кольцевая деталь R5…15, Z=0…10 для квалификации выбора."""
    sketch = require(model.GetSketchs().Add(), "Эскиз кольца")
    sketch.SetPlane(require(part.GetDefaultObject(c3d.o3d_planeXOY), "Плоскость XOY"))
    require(sketch.Update(), "Опора эскиза")
    fragment = require(sketch.BeginEdit(False), "Редактирование эскиза")
    try:
        view = require(fragment.GetViewsAndLayersManager().GetViews().GetActiveView(), "Вид")
        drawing = require(ksapi.IDrawingContainer(view), "Контейнер эскиза")
        for radius in (15., 5.):
            circle = require(drawing.GetCircles().Add(), "Окружность")
            circle.SetXc(0.)
            circle.SetYc(0.)
            circle.SetRadius(radius)
            require(circle.Update(), "Обновление окружности")
    finally:
        require(sketch.EndEdit(), "Завершение эскиза")
    operation = require(model.GetExtrusions().Add(c3d.o3d_bossExtrusion), "Выдавливание")
    operation.SetProfiles([sketch])
    operation.SetDirection(c3d.dtNormal)
    require(operation.SetSideParameters(True, c3d.etBlind, 10., 0., False, None), "Высота")
    require(operation.Update(), "Построение кольца")


def validate(part, *, origin=(0, 0, 0), axis=(0, 0, 1)):
    # Допуски выбраны для этой аналитической детали, не defaults селекторов.
    options = {"length_tol": 1e-5, "angle_tol": 1e-7}
    bodies = require(ksapi.IFeature(part), "Результат детали").GetResultBodies()
    require(len(bodies) == 1 and bodies[0].IsSolid(), "Одно твёрдое тело")
    body = bodies[0]
    axis = unit(axis)
    top = tuple(p + 10 * n for p, n in zip(origin, axis))
    reverse = tuple(-n for n in axis)
    selected = [
        select_plane(part, body, point=top, normal=reverse, **options),
        select_circle(part, body, center=top, radius=5, normal=axis, **options),
        select_cylinder(part, body, radius=5, axis_point=origin, axis=axis, span=(0, 10), **options),
        select_cylinder(part, body, radius=15, axis_point=origin, axis=reverse, span=(-10, 0), **options),
    ]
    require(len({item.reference for item in selected}) == 4, "Разные целевые объекты")
    for index, wanted in (([selected[0], selected[0]], 2), ([], 0)):
        try:
            unique([(item, {"probe": True}) for item in index], {}, lambda item: True)
        except ValueError as error:
            require(f'"matches": {wanted}' in str(error), "Диагностика количества кандидатов")
        else:
            raise AssertionError("Ноль/несколько кандидатов не отклонены")
    print("PASS: плоскость, окружность, внутренний/наружный цилиндры, пустой/неоднозначный выбор")


def main():
    app = require(ksapi.GetKompas(), "Нет запущенной API-сессии КОМПАС")
    previous = app.GetActiveDocument()
    doc = None
    try:
        doc = require(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart, True), "Своя временная деталь")
        part = require(ksapi.IKompasDocument3D(doc).GetTopPart(), "Верхний компонент")
        build(part, require(part.GetModelContainer(), "Модель"))
        require(part.RebuildModel(True), "Перестроение")
        validate(part)
        # Повторная выборка после rebuild, без использования прежних ссылок.
        require(part.RebuildModel(True), "Повторное перестроение")
        validate(part)
        # Повернуть свою деталь на 45° вокруг Y и перенести: не только ось Z.
        body = ksapi.IFeature(part).GetResultBodies()[0]
        move = require(part.GetModelContainer().GetBodyRepositions().Add(), "Поворот своей детали")
        move.SetRepositionBody(body)
        move.SetCopyBody(False)
        s = math.sqrt(0.5)
        matrix = [s, 0, -s, 0, 0, 1, 0, 0, s, 0, s, 0, 10, 20, 30, 1]
        require(move.GetPosition().InitByMatrix3D(matrix), "Матрица поворота/переноса")
        require(move.Update(), "Преобразование своей детали")
        require(part.RebuildModel(True), "Перестроение наклонённой детали")
        validate(part, origin=(10, 20, 30), axis=(s, 0, s))
    finally:
        try:
            if doc is not None:
                require(doc.Close(c.kdDoNotSaveChanges), "Закрытие своей временной детали")
        finally:
            if previous:
                previous.SetActive()


if __name__ == "__main__":
    main()
