# Рецепты для КОМПАС-3D на Python

Здесь собраны небольшие операции: создать эскиз, выдавить профиль, вставить деталь в сборку, изменить уже построенную модель. Выберите нужный раздел — читать весь файл подряд не требуется.

Если модель уже существует, **изменяйте её, а не создавайте заново**. Начните с §10 и §28. Для новой детали начните с §1–3.

## Каталог готовых примеров

Ссылки ведут на самостоятельные макросы; для адаптации читайте `build`. Изображения получены из КОМПАС-3D v25 / Linux, размеры — мм. [Запуск, проверки и отчёты →](examples.md)

| Пример | Код | Результат из КОМПАС |
| --- | --- | --- |
| **01. Пластина** 60 × 40 × 10. Эскиз → выдавливание (§3, §6) | [01_plate.py](../examples/01_plate.py) | [![Пластина](../examples/01_plate.jpg)](../examples/01_plate.jpg) |
| **02. Кольцо** Ø50, отверстие Ø10, толщина 10. Два контура в одном эскизе (§5) | [02_ring.py](../examples/02_ring.py) | [![Кольцо](../examples/02_ring.jpg)](../examples/02_ring.jpg) |
| **03. Четыре отверстия** Ø4 на R15 в пластине. Отдельный вырез (§6–7) | [03_holes.py](../examples/03_holes.py) | [![Четыре отверстия](../examples/03_holes.jpg)](../examples/03_holes.jpg) |
| **04. Втулка вращением** R5…15, длина 20 вокруг OY (§12) | [04_revolve.py](../examples/04_revolve.py) | [![Втулка вращением](../examples/04_revolve.jpg)](../examples/04_revolve.jpg) |
| **05. Смещённая плоскость** Z=15 и цилиндр Ø10 × 5 (§13) | [05_offset_plane.py](../examples/05_offset_plane.py) | [![Цилиндр на смещённой плоскости](../examples/05_offset_plane.jpg)](../examples/05_offset_plane.jpg) |
| **06. Три квадратных сечения** 20 → 14 → 10 на Z=0, 10, 20 (§19) | [06_loft.py](../examples/06_loft.py) | [![Элемент по трём сечениям](../examples/06_loft.jpg)](../examples/06_loft.jpg) |
| **07. Круговой массив тел** Четыре цилиндра Ø4 × 5 на R10 (§15) | [07_body_pattern.py](../examples/07_body_pattern.py) | [![Круговой массив тел](../examples/07_body_pattern.jpg)](../examples/07_body_pattern.jpg) |
| **08. Булева разность** Из цилиндра Ø30 вычесть цилиндр Ø10 (§19, §23) | [08_boolean.py](../examples/08_boolean.py) | [![Булева разность цилиндров](../examples/08_boolean.jpg)](../examples/08_boolean.jpg) |
| **09. Поворот и перенос тела** +90° вокруг Z, перенос (10,20,30) (§21) | [09_reposition.py](../examples/09_reposition.py) | [![Преобразованное тело](../examples/09_reposition.jpg)](../examples/09_reposition.jpg) |
| **10. Сборка из двух вхождений** Один блок закреплён, другой на X=30 (§16) | [10_assembly.py](../examples/10_assembly.py) | [![Два вхождения в сборке](../examples/10_assembly.jpg)](../examples/10_assembly.jpg) |
| **11. Скругление с правкой** Четыре угла R3 → R5 без пересоздания признака (§14) | [11_fillet_edit.py](../examples/11_fillet_edit.py) | [![Скругления R5](../examples/11_fillet_edit.jpg)](../examples/11_fillet_edit.jpg) |
| **12. Четыре фаски** 2 × 2 мм на вертикальных углах (§14) | [12_chamfer.py](../examples/12_chamfer.py) | [![Фаски углов](../examples/12_chamfer.jpg)](../examples/12_chamfer.jpg) |
| **13. Родное глухое отверстие** Holes3D Ø10 × 6, центр (12,7), вход сверху (§31) | [13_native_hole.py](../examples/13_native_hole.py) | [![Родное глухое отверстие](../examples/13_native_hole.jpg)](../examples/13_native_hole.jpg) |
| **14. Открытая коробка** 60 × 40 × 20, оболочка внутрь 2 мм (§32) | [14_shell.py](../examples/14_shell.py) | [![Оболочка коробки](../examples/14_shell.jpg)](../examples/14_shell.jpg) |
| **15. Массив операций 3 × 2** Сквозные Ø4, шаг 20 × 20 (§15) | [15_linear_pattern.py](../examples/15_linear_pattern.py) | [![Прямоугольный массив отверстий](../examples/15_linear_pattern.jpg)](../examples/15_linear_pattern.jpg) |

## Как читать примеры

- Код работает через нативный `ksapi` в Linux. КОМПАС должен быть уже запущен с API; подключение не запускает программу.
- Размеры и координаты — **миллиметры**. Единицы углов указаны отдельно.
- Большинство блоков — части макроса, а не отдельные программы. Перед блоком указано, какие объекты нужны.
- **Проверено в КОМПАС** означает, что описанный пример выполнялся на Linux v25. Это не обещание для любой формы и любых размеров.
- **Требует проверки** означает, что вызовы известны, но правильный результат в КОМПАС пока не подтверждён.

В коде используются следующие имена:

- `app` — приложение КОМПАС; `doc` — документ, например файл детали или сборки.
- `doc3d` — доступ к 3D-функциям документа; `part` — деталь или верхний компонент сборки.
- `model` — контейнер операций детали; `sketch` — эскиз; `drawing` — геометрия редактируемого эскиза.
- `operation` — операция построения, например выдавливание; `body` — полученное геометрическое тело.
- `component` — **вхождение** детали в сборку. Один файл может быть вставлен несколько раз: это разные вхождения.

`require`, `new_part`, `circle` и другие короткие функции — **наши функции, не методы КОМПАС**. Они находятся в [basic_part.py](../examples/basic_part.py). При создании отдельного макроса скопируйте нужные определения в него. Не добавляйте зависимость от расположения скилла или другого проекта.

## Понятия: деталь, сборка, подсборка

**Деталь** — изделие из одного материала без сборочных операций: вал, втулка, крышка. Файл `.m3d`.

**Сборка** — соединённые детали, стандартные изделия и другие сборки. Файл `.a3d`. Их взаимное положение задаётся размещениями и сопряжениями.

**Подсборка** — сборка, вставленная в другую сборку. Например, предварительно собранный редуктор, который затем устанавливают в станок. Это тоже файл `.a3d`.

Такое разделение соответствует ГОСТ 2.101. Не создавайте подсборку только ради совместного скрытия деталей: для этого есть слои (§26).

## 1. Взять основу макроса

[basic_part.py](../examples/basic_part.py) — настраиваемая пластина/кольцо с отверстиями. Копируйте нужные функции в самостоятельный макрос; далее показаны отдельные шаги построения. [Команды запуска →](examples.md)

## 2. Подключиться и создать документ

Этот пример создаёт **временную деталь** и закрывает её без сохранения. Поместите построение внутрь `try`, а сохранение — перед `finally`.

```python
import ksapi
from constants import constants as c
from constants3d import constants as c3d


def require(value, message):
    if not value:
        raise RuntimeError(message)
    return value


app = require(ksapi.GetKompas(), "Нет запущенной API-сессии КОМПАС")
previous = app.GetActiveDocument()
doc = None
try:
    doc = require(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart, True), "Новая деталь")
    doc3d = ksapi.IKompasDocument3D(doc)
    part = require(doc3d.GetTopPart(), "Верхний компонент")
    model = require(part.GetModelContainer(), "Операции детали")
    # Построение и проверка — здесь.
finally:
    if doc:
        require(doc.Close(c.kdDoNotSaveChanges), "Закрытие временной детали")
    if previous:
        previous.SetActive()
```

`require` проверяет результат вызова и выдаёт понятную ошибку. Не применяйте её к методам, которые ничего не возвращают: многие `Set…` возвращают `None` даже при успехе.

Для сборки используйте `c.ksDocumentAssembly`, для чертежа — `c.ksDocumentDrawing`. Для нескольких временных документов удобен список `owned` (§24).

Если `GetKompas()` не подключился, не запускайте и не перезапускайте КОМПАС автоматически. Команда запуска и окружение Python описаны в [SKILL.md](../SKILL.md).

## 3. Создать эскиз на базовой плоскости

Нужны `part` и её `model` из §2. Функция `sketch_xoy` из `basic_part.py` создаёт эскиз на XOY, открывает редактирование и обязательно завершает его при выходе из блока.

```python
with sketch_xoy(part, model) as (sketch, drawing):
    rectangle(drawing, -30, -20, 60, 40)

operation = extrude(model, sketch, 10)
```

**Результат:** прямоугольник 60 × 40 мм, выдавленный на 10 мм.

Внутри `sketch_xoy` выполняется последовательность:

1. `model.GetSketchs().Add()` — создать эскиз.
2. `sketch.SetPlane(part.GetDefaultObject(c3d.o3d_planeXOY))` — назначить плоскость.
3. `sketch.Update()`, затем `sketch.BeginEdit(False)` — открыть редактирование.
4. Получить активный вид фрагмента и `ksapi.IDrawingContainer(view)` — доступ к геометрии.
5. В `finally` вызвать `sketch.EndEdit()` — закончить редактирование.

Для XOZ или YOZ замените базовую плоскость и проверьте направление осей. Координаты внутри эскиза не обязательно совпадают с мировыми координатами (§19, §22).

## 4. Нарисовать отрезки и замкнутый контур

Нужен `drawing` открытого эскиза. Функции `line` и `rectangle` берутся из `basic_part.py`.

```python
points = [(0, 0), (40, 0), (30, 20), (0, 20)]
for start, end in zip(points, points[1:] + points[:1]):
    line(drawing, start, end)
```

Последний отрезок соединяет последнюю точку с первой. Для обычного прямоугольника достаточно `rectangle(drawing, x, y, width, height)`.

Прямые вызовы API:

- Отрезок: `GetLineSegments().Add()`, затем `SetX1/SetY1/SetX2/SetY2` и `Update()`.
- Прямоугольник: `GetRectangles().Add()`, затем `SetX/SetY/SetWidth/SetHeight` и `Update()`.
- Многоугольник одним вызовом — §19.

**Проверьте:** контур замкнут, не пересекает себя и не содержит рёбер нулевой длины. Для сложных контуров можно использовать `shapely.Polygon(points).is_valid` и `.area`.

## 5. Нарисовать окружность и отверстие

В открытом эскизе вызовите:

```python
circle(drawing, 0, 0, 25)  # Наружная окружность, радиус 25 мм.
circle(drawing, 0, 0, 5)   # Внутренняя окружность, радиус 5 мм.
```

После выдавливания получится кольцо. Внутренняя замкнутая окружность задаёт отверстие в профиле.

В API центр окружности задаётся через **`SetXc/SetYc`**, а не `SetX/SetY`: `drawing.GetCircles().Add()` → центр → `SetRadius` → `Update()`.

Для отверстия в уже существующем теле создайте отдельный эскиз и вырез (§6). Окружности не должны касаться друг друга или внешнего контура. Наличие окружности в эскизе ещё не доказывает наличие отверстия в теле — проверьте результат.

## 6. Выдавить профиль или сделать вырез

Нужны `model` и **завершённый** эскиз `sketch`. Задайте положительную глубину `depth` в мм и `cut`: `False` для добавления материала, `True` для выреза.

```python
kind = c3d.o3d_cutExtrusion if cut else c3d.o3d_bossExtrusion
operation = require(model.GetExtrusions().Add(kind), "Выдавливание")
operation.SetProfiles([sketch])
# В этом рецепте эскиз на нижней XOY, материал расположен в Z>0.
operation.SetDirection(c3d.dtReverse if cut else c3d.dtNormal)
require(operation.SetSideParameters(not cut, c3d.etBlind, depth, 0.0, False, None), "Глубина")
require(operation.Update(), "Построение")
```

В готовой функции это `extrude(model, sketch, depth, cut=False)`.

- `True/False` в `SetSideParameters` выбирает прямую/обратную сторону. Направление и сторона должны соответствовать друг другу.
- Для выреза из нижней XOY в материал Z>0 проверена пара `dtReverse` + `SetSideParameters(False, ...)`. `dtNormal` здесь давал успешную операцию без отверстий.
- `etBlind` — ограничение числовой глубиной; `0.0` — нулевой уклон.
- `None` — нет объекта, ограничивающего глубину в этом режиме.
- `SetProfiles` принимает список эскизов и возвращает `None`.

**Проверьте:** тело появилось с нужной стороны; вырез действительно удалил материал. Для сквозного отверстия в простой пластине из примера глубина равна её толщине. Это не универсальный режим «через всё»; не подменяйте его произвольно большим числом.

## 7. Повторить окружности в одном эскизе

Для нескольких одинаковых отверстий проще нарисовать все окружности в одном эскизе и сделать один вырез.

**По окружности.** Нужны `count` — число отверстий, `pitch_radius` — радиус расположения центров, `hole_radius` — радиус отверстия.

```python
import math

for i in range(count):
    angle = 2 * math.pi * i / count
    circle(drawing, pitch_radius * math.cos(angle), pitch_radius * math.sin(angle), hole_radius)
```

**По сетке.** Нужны число строк/столбцов `rows`, `cols`, начало `x0`, `y0`, шаги `step_x`, `step_y` и `hole_radius`.

```python
for row in range(rows):
    for col in range(cols):
        circle(drawing, x0 + col * step_x, y0 + row * step_y, hole_radius)
```

Выберите один рисунок. Проверьте, что отверстия не пересекаются и не выходят за материал. Для повторения самой операции или отдельных тел используйте §15.

## 8. Построить гладкую кривую Безье

Функция `bezier(drawing, nodes)` принимает узлы вида `(x, y, x_left, y_left, x_right, y_right)`. Последние четыре числа — **абсолютные координаты** управляющих точек, не смещения от узла.

Если известны функция кривой `p(t)` и её производная `d(t)`, один кубический участок между `t0` и `t1` можно приблизить так:

```python
h = (t1 - t0) / 3
p0, p3 = p(t0), p(t1)
p1 = p0 + h * d(t0)
p2 = p3 - h * d(t1)
```

Здесь `p(t)` и `d(t)` возвращают массивы `numpy`; для кортежей нужны покоординатные вычисления. `p0/p3` — концы, `p1/p2` — управляющие точки.

API: `GetBeziers().Add()` → `SetClosed(False)` → `AddPoint(index, x, y, x_left, y_left, x_right, y_right)` → `Update()`. `AddPoint` возвращает кортеж: проверяйте **первый элемент**, а не истинность всего кортежа.

**Проверьте сначала один участок:** концы, стыки и несколько внутренних точек. Для фактической кривой доступны `GetCurve2D().GetDistanceToPoint(x,y)` и `PointOn(parameter,0,0)`; границы параметра — `GetParamMin/Max`. Выборка точек не доказывает точность между ними. NURBS из другой библиотеки нельзя переносить без проверки полюсов, весов и узлов.

## 9. Проверить и сохранить результат

Для простого выдавливания готовые функции — `solid_bounds(part, operation)` и `save_new(doc, path)` из `basic_part.py`.

Габариты тела читаются через `body.GetGabarit(0,0,0,0,0,0)`. Возврат: `(status, xmin, ymin, zmin, xmax, ymax, zmax)`. Размер по каждой оси — разность максимума и минимума.

Для конечного результата обычно нужен `ksapi.IFeature(part).GetResultBodies()`. Список тел отдельной операции может быть пустым или содержать только новые копии (§15, §21).

Подробные измерения и ограничения `verify_cylindrical_walls` — в [документе о проверках](examples.md).

**Сохранение:** `doc.SaveAs(absolute_path)` возвращает статус. Проверьте, что появился непустой файл. `save_new` дополнительно запрещает перезапись существующего файла. Для уже открытого рабочего файла есть `doc.Save()`.

Сохраняйте только принятый результат. Если важно доказать сохранность, откройте проверочную копию и повторите проверки. `SaveAs` не собирает внешние файлы в переносимый комплект. Экспорт и изображения не обязательны после каждой правки (§30).

## 10. Открыть существующую модель

Нужны `app`, абсолютный путь `path` и список `owned` для документов, открытых этим макросом (§24).

```python
from pathlib import Path

path = str(Path(path).expanduser().resolve(strict=True))
documents = app.GetDocuments()
doc = documents.GetItemByFilePath(path)
if not doc:
    doc = require(documents.Open(path, True, False), "Открытие модели")
    owned.append(doc)

require(str(Path(doc.GetFullPath()).resolve()) == path, "Открыт другой файл")
```

Проверьте также `doc.GetDocumentType()`: `c.ksDocumentPart` или `c.ksDocumentAssembly`.

**Сначала ищем среди открытых документов.** Уже открытая модель может содержать несохранённые изменения: нельзя заменять её дисковой версией, добавлять в `owned` или закрывать после макроса.

Если пользователь явно выбрал активное окно, допустим `app.GetActiveDocument()`, но всё равно проверьте тип и путь. Не считайте случайное активное окно нужной моделью.

## 11. Нарисовать геометрию в новом 2D-чертеже

Нужны `app`, `owned` и функции `require`, `rectangle`, `line`, `circle`. Код выполняется внутри блока с закрытием своих документов (§24).

```python
doc = require(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentDrawing, True), "Чертёж")
owned.append(doc)
doc2d = ksapi.IKompasDocument2D(doc)
view = doc2d.GetViewsAndLayersManager().GetViews().GetActiveView()
drawing = ksapi.IDrawingContainer(view)
rectangle(drawing, 50, 50, 100, 60)
line(drawing, (50, 50), (150, 110))
circle(drawing, 100, 80, 10)
```

В чертеже эти функции работают на активном виде; `BeginEdit/EndEdit` 3D-эскиза не нужны. Цепочка проверена тестами без запуска CAD. Размеры, листы и оформление в этот рецепт не входят.

## 12. Построить деталь вращением

Пример создаёт втулку вокруг OY: внутренний радиус 5 мм, наружный 15 мм, длина 20 мм. Нужны `app`, `owned` и функции из `basic_part.py`.

```python
doc, part, model = new_part(app, "Втулка вращением", owned=owned)
with sketch_xoy(part, model) as (profile, drawing):
    rectangle(drawing, 5, 0, 10, 20)

rotation = require(model.GetRotateds().Add(c3d.o3d_bossRotated), "Вращение")
rotation.SetProfile(profile)
rotation.SetAxis(part.GetDefaultObject(c3d.o3d_axisOY))
rotation.SetDirection(c3d.dtNormal)
rotation.SetRotatedType(True, c3d.ksRTAngle)
rotation.SetAngle(True, 360.0)
rotation.SetToroidShapeType(True)
require(rotation.Update(), "Построение вращения")
bounds = solid_bounds(part, rotation)
```

**Проверено в КОМПАС:** одно твёрдое тело, габариты `(-15, 0, -15, 15, 20, 15)`.

`SetProfile` принимает один эскиз. Ось вращения лежит в его плоскости. Угол — градусы; `True` в `SetAngle/SetRotatedType` выбирает прямую сторону. Незамкнутый профиль, тонкая стенка и вырез вращением требуют отдельной проверки.

## 13. Создать эскиз на смещённой плоскости

Пример: плоскость на Z=15 мм и цилиндр Ø10 высотой 5 мм. Нужны собственная `part`, её `model` и функции `require`, `circle`, `extrude`.

```python
aux = ksapi.IAuxiliaryGeomContainer(part)
plane = require(aux.GetPlanes3D().Add(c3d.o3d_planeOffset), "Плоскость")
offset = ksapi.IPlane3DByOffset(plane)
offset.SetBasePlane(part.GetDefaultObject(c3d.o3d_planeXOY))
offset.SetOffset(15.0)
offset.SetDirection(True)
require(offset.Update(), "Смещение плоскости")

sketch = require(model.GetSketchs().Add(), "Эскиз")
sketch.SetPlane(plane)
require(sketch.Update(), "Опора эскиза")
fragment = require(sketch.BeginEdit(False), "Редактирование эскиза")
try:
    view = fragment.GetViewsAndLayersManager().GetViews().GetActiveView()
    drawing = ksapi.IDrawingContainer(view)
    circle(drawing, 0, 0, 5)
finally:
    require(sketch.EndEdit(), "Завершение эскиза")

operation = extrude(model, sketch, 5)
```

**Проверено в КОМПАС:** одно тело, габариты `(-5, -5, 15, 5, 5, 20)`.

`IAuxiliaryGeomContainer` запрашивается у **детали**, не у `model`. `SetDirection(True)` выбирает прямое смещение, `False` — обратное; расстояние положительное. Для других базовых плоскостей проверьте нормаль (§22).

## 14. Сделать фаску или скругление

Самостоятельные сценарии: [11_fillet_edit.py](../examples/11_fillet_edit.py) — четыре вертикальных угла пластины, R3 → R5 на том же признаке; [12_chamfer.py](../examples/12_chamfer.py) — фаски 2 × 2 мм на тех же четырёх углах. Точный статус прогона указан в каталоге.

Нужны `model` и `edges` — список **выбранных** рёбер. Получить кандидатов можно через `ksapi.IFeature(base).GetModelObjects([c3d.o3d_edge])`, где `base` — исходная операция. Выбирайте рёбра по положению и геометрии, не просто `edges[0]`.

**Фаска 1 × 1 мм:**

```python
chamfer = require(model.GetChamfers().Add(), "Фаска")
chamfer.SetBaseObjects(edges)
chamfer.SetBuildingType(c3d.ksChamferTwoSides)
chamfer.SetDistance1(1.0)
chamfer.SetDistance2(1.0)
chamfer.SetTangent(False)
require(chamfer.Update(), "Фаска")
```

**Скругление R1 — отдельный пример, не продолжение фаски:**

```python
fillet = require(model.GetFillets().Add(), "Скругление")
fillet.SetBaseObjects(edges)
fillet.SetBuildingType(c3d.ksFilletCircleArc)
fillet.SetRadius1(1.0)
fillet.SetTangent(False)
require(fillet.Update(), "Скругление")
```

`SetBaseObjects` принимает список. В примерах рёбра выбираются по обоим концам: X=±30, Y=±20, Z=0…10; индекс ребра не используется. После изменения формы получайте топологию заново; конечные тела читайте у **детали**, не у операции.

**Правка живого скругления:** перечитать `model.GetFillets().GetFillet(0)` в собственной детали с единственным скруглением → `SetRadius1(5)` → `Update()` → проверить новые грани. Не пересоздавать признак и не править API5 definition вместо живого API7-объекта.

В `11_fillet_edit.py` проверяются четыре четверти цилиндра: радиус, площадь и диапазоны координат у каждого угла. Ось каждой поверхности параллельна Z и отстоит на R от двух исходных боковых плоскостей. Ожидаемый объём: `60*40*10 - 4*(1-pi/4)*R**2*10`.

В `12_chamfer.py` проверяются вершины и площадь каждой диагональной плоской грани; объём `24000 - 4*(2*2/2)*10 = 23920` мм³. Вместе эти проверки отличают реальное снятие материала от успешного `Update()` без нужной геометрии. Ограничение кэша МЦХ разобрано в начале файла.

## 15. Повторить тела или операции

### Прямоугольный массив операций

[15_linear_pattern.py](../examples/15_linear_pattern.py) создаёт пластину 60 × 40 × 10, один сквозной вырез Ø4 с центром (−20,−10), затем размножает **операцию**, не рисует ещё пять окружностей.

Маршрут: `model.GetFeaturePatterns().Add(c3d.o3d_meshCopy)` → `ksapi.ILinearPattern(feature)` → `SetInitialObjects([seed])` → оси `SetAxis1(OX)`, `SetAxis2(OY)` → шаги 20/20 → количества 3/2 → `SetBuildingType(c.ksLPSaveAll)` → `Update()`. В коде также явно заданы направления и режим шага между соседними экземплярами.

`Count1/Count2` включают исходный экземпляр. Не устанавливайте `Angle2=0`: штатные 90° сохраняют две независимые оси, а нулевой угол может свести сетку в линию.

Проверяются **все шесть стенок** Ø4 на Z=0…10, центры `X=(-20,0,20)`, `Y=(-10,10)`, объём `24000 - 6*pi*2**2*10`. Совпадения счётчиков недостаточно. Это квалификация прямоугольной сетки на плоской пластине, не произвольных криволинейных массивов.

### Круговой массив отдельных тел — проверено в КОМПАС

Нужны `part`, `model` и отдельное тело `body`. Пример делает четыре экземпляра с шагом 90° вокруг OZ; исходное тело должно находиться в стороне от оси.

```python
feature = require(model.GetFeaturePatterns().Add(c3d.o3d_BodiesCircularCopy), "Массив тел")
pattern = ksapi.ICircularPattern(feature)
pattern.SetInitialObjects([body])
pattern.SetAxis(part.GetDefaultObject(c3d.o3d_axisOZ))
pattern.SetBuildingType(c3d.ksCPSaveAll)
pattern.SetCount1(1)
pattern.SetCount2(4)
pattern.SetStep2(90.0)
pattern.SetBoundaryInstancesStepFactor2(False)
pattern.SetSaveInitialOrientation(False)
require(pattern.Update(), "Построение массива")
```

На четырёх цилиндрах с центрами на R10 получены центры `(±10,0)` и `(0,±10)`. Угол — градусы. `Count1/Step1` относятся к радиальному направлению, `Count2/Step2` — к обходу окружности. При `BoundaryInstancesStepFactor2=False` шаг — между соседними экземплярами.

`GetResultBodies()` массива вернул **три новые копии**, исходное тело учитывается отдельно. Проверяйте все конечные тела детали.

Для оси на пересечении двух плоскостей: `aux.GetAxes3D().Add(c3d.o3d_axis2Planes)` → `ksapi.IAxis3DBy2Planes(axis)` → `SetPlane1/SetPlane2` → `Update()`.

### Круговой массив операций — требует отдельной проверки

Если `seed` — операция выреза, цепочка настройки такая:

```python
feature = require(model.GetFeaturePatterns().Add(c3d.o3d_circularCopy), "Массив операций")
pattern = ksapi.ICircularPattern(feature)
pattern.SetInitialObjects([seed])
pattern.SetGeometryPattern(False)
pattern.SetAxis(part.GetDefaultObject(c3d.o3d_axisOZ))
pattern.SetBuildingType(c3d.ksCPSaveAll)
pattern.SetCount1(1)
pattern.SetStep1(0.0)
pattern.SetCount2(4)
pattern.SetBoundaryInstancesStepFactor2(False)
pattern.SetStep2(90.0)
pattern.SetStepByAxis(0.0)
pattern.SetReverseDirection(False)
pattern.SetSaveInitialOrientation(False)
require(pattern.Update(), "Массив операций")
```

Полный результат этой пробы не подтверждён: соединение оборвалось, причина не установлена. `GetExemplarsCounts(0,0)` возвращает `(status,count1,count2)`, но дополнительно нужно проверить сами отверстия.

Для сложных тел проверяйте сначала две копии, затем небольшой массив и только потом нужное количество. Успех маленькой пробы не гарантирует успех большого массива или последующего объединения.

## 16. Вставить деталь в сборку и переместить вхождение

Нужны открытая сборка `doc`, путь детали `component_path` и `require`. Для новой сборки документ создаётся как в §2 с типом `c.ksDocumentAssembly`.

```python
from pathlib import Path

source = Path(component_path).expanduser().resolve(strict=True)
require(source.is_file() and source.suffix.lower() == ".m3d", "Нужен файл детали")
assembly = ksapi.IKompasDocument3D(doc).GetTopPart()
parts = assembly.GetParts()
before = parts.GetCount()
component = require(parts.AddFromFile(str(source), True, True), "Вставка детали")
require(parts.GetCount() == before + 1, "Число вхождений")
```

В `AddFromFile(fileName, externalFile, redraw)` первый `True` сохраняет внешнюю ссылку, второй запрашивает перерисовку. Исходный файл должен оставаться доступным. Вставка не создаёт сопряжений.

**Перенос на X=30 мм.** Нужен свободный от сопряжений компонент; проверьте его фиксацию. В существующем механизме положение обычно меняют через сопряжения (§27), а не принудительный перенос.

```python
expected = list(component.GetPlacement().GetMatrix3D())
expected[12:15] = [30.0, 0.0, 0.0]
require(component.GetPlacement().SetOrigin(30.0, 0.0, 0.0), "Перенос")
update_ok = component.UpdatePlacement(True)
require(assembly.RebuildModel(True), "Перестроение сборки")
actual = list(component.GetPlacement().GetMatrix3D())
require(len(actual) == len(expected), "Размер матрицы")
require(all(abs(a - b) < 1e-6 for a, b in zip(actual, expected)), "Положение и ориентация")
print("UpdatePlacement:", update_ok)
```

**Проверено в КОМПАС:** перенос свободного вхождения и его Undo/Redo. На этой установке `UpdatePlacement(True)` возвращал `False`, хотя матрица уже изменилась и перестроение прошло. Поэтому проверка выше читает фактическую матрицу. При несовпадении остановитесь, не повторяйте перенос вслепую. Для существующей сборки дополнительно сравните остальные вхождения, фиксацию и сопряжения (§28).

## 17. Построить дугу с нужным направлением

Нужны `drawing` и функция `arc` из `basic_part.py`.

```python
import math

# Дуга от 350° до 10° против часовой стрелки: размах 20°.
obj = arc(drawing, (10, 20), 5, math.radians(350), math.radians(10))
```

Функция принимает **радианы**, а API `SetAngle1/SetAngle2` — **градусы**. `IArc.SetDirection(True)` означает по часовой стрелке, `False` — против. Центр задаётся `SetXc/SetYc`.

Функция проверяет длину дуги и её начало, середину и конец. Одних концов недостаточно: у малой и дополняющей дуг они совпадают. Для полной окружности используйте `circle`, а не одинаковые начальный и конечный углы.

Размах против часовой стрелки — `(a2-a1) % math.tau`, по часовой — `(a1-a2) % math.tau`. Длина — `radius * sweep`.

Направление и единицы подтверждены справкой и построением; расширенная проверка середины покрыта тестами без запуска CAD.

## 18. Соединить два участка касательной дугой

### Готовый случай: два отрезка

`blend_lines(p0, corner, p1, radius)` из `basic_part.py` рассчитывает обрезку ломаной и вставку дуги. Она **только считает координаты**, не меняет КОМПАС.

Для ломаной `(0,0) → (10,0) → (10,10)` и радиуса 2 мм:

```python
segment_a, arc_params, segment_b = blend_lines((0, 0), (10, 0), (10, 10), 2)
center, radius, a1, a2, clockwise = arc_params
line(drawing, *segment_a)
arc(drawing, center, radius, a1, a2, clockwise=clockwise)
line(drawing, *segment_b)
```

Получатся отрезки `(0,0) → (8,0)` и `(10,2) → (10,10)`, между ними дуга R2 с центром `(8,2)`. Код рисует итоговый контур в новом эскизе; при правке старого нужно отдельно заменить исходные отрезки.

Функция не продолжает линии и отвергает радиус, при котором не остаётся двух ненулевых отрезков. Длина обрезки от угла — `radius * tan(abs(turn)/2)`, где `turn` — угол поворота. Расчёт проверен тестами; отдельный новый прогон CAD не выполнялся.

### Произвольные кривые — алгоритм, не готовая функция

Для кривых `A(t)` и `B(u)`:

1. Задайте радиус, стороны сопряжения и разрешённые интервалы. Не продолжайте кривые без требования задачи.
2. Для единичной левой нормали `N=(-dy,dx)/hypot(dx,dy)` решите уравнение `A(t)+side_a*r*N_a(t) = B(u)+side_b*r*N_b(u)`, где стороны равны −1 или +1.
3. Проверьте найденные точки касания, радиус, сторону и допустимые интервалы. Численному решателю недостаточно вернуть `success`; нужна проверка невязки в мм.
4. Обрежьте исходные участки и вставьте дугу с согласованным направлением. Безье делится алгоритмом де Кастельжо, NURBS — корректным разбиением по узлам; простая перестановка конца меняет форму.
5. Проверьте концы, касательные и отсутствие самопересечений. Линейный и угловой допуски задаются отдельно.

Метод требует ненулевых производных; несколько начальных приближений не гарантируют поиск всех решений. Радиус и конструкцию перехода определяет инженерная задача. Например, круговая галтель ножки зуба не равнозначна профилю обкатки.

**Непроверенный API:** `curve_a.CouplingCurveCurve(curve_b, radius)` существует, но возвращает список чисел, не готовую дугу. Формат списка и обрезка исходных кривых не установлены — не угадывайте индексы и не используйте его как готовое сопряжение.

## 19. Создать отдельные тела, объединить их или построить по сечениям

Все операции ниже проверены в КОМПАС на простых примерах. Нужны объекты одной детали.

### Отдельное тело

До `operation.Update()` вызовите `operation.SetOperationResult(c3d.ksOperationNewBody)`.

Режимы результата операции: `ksOperationUnion=0`, `ksOperationNewBody=1`, `ksOperationCut=2`, `ksOperationIntersect=3`.

### Вычитание одного тела из другого

Нужны `model`, основное тело `base_body` и тело-инструмент `tool_body`.

```python
boolean = require(model.GetBooleans().Add(), "Булева операция")
boolean.SetBaseObject(base_body)
boolean.SetModifyObjects([tool_body])
boolean.SetBooleanType(c.ksDifference)
boolean.SetSaveCopyBaseObject(False)
boolean.SetSaveCopyModifyObjects(False)
require(boolean.Update(), "Вычитание")
```

Для объединения — `c.ksUnion`, для пересечения — `c.ksIntersect`. Значения **другого перечисления**: пересечение 1, вычитание 2, объединение 3. Не путайте их с режимами результата выше. Тип задавайте после объектов. На простых телах также проверен `SetBodies([base_body, *tool_bodies])`.

### Замкнутый многоугольник одним вызовом

```python
polyline = require(drawing.GetPolyLines2D().Add(), "Полилиния")
polyline.SetPoints([0, 0, 40, 0, 30, 20, 0, 20])
polyline.SetClosed(True)
require(polyline.Update(), "Контур")
```

### Элемент по сечениям

Нужны завершённые эскизы `sk0`, `sk1`, `sk2`.

```python
loft = require(model.GetLofts().Add(c3d.o3d_bossLoft), "Элемент по сечениям")
loft.SetProfiles([sk0, sk1, sk2])
loft.SetClosed(False)
loft.SetOperationResult(c3d.ksOperationNewBody)
require(loft.Update(), "Построение по сечениям")
```

Проверьте форму между сечениями, а не только число тел.

### Перевод координат эскиза в мировые

`sketch.GetPoint3D(0,0,0,0,0)`, `GetPoint3D(1,0,0,0,0)` и `GetPoint3D(0,1,0,0,0)` возвращают `(status,x,y,z)`. Разности точек дают две оси эскиза. Считайте их один раз, затем преобразуйте все координаты локально. Обратная проекция: `GetPointProjectionToXY(x,y,z,0,0)` возвращает статус и две координаты.

## 20. Построить спираль и протянуть по ней профиль

Нужны `part`, её `model`, базовая плоскость `base_plane`, радиус `radius`, шаг `pitch`, число витков `turns` и замкнутый эскиз `profile`. Длины — мм. Для описанного случая спираль начинается на +X, а профиль лежит в радиально-осевой плоскости XOZ.

```python
aux = ksapi.IAuxiliaryGeomContainer(part)
spiral = require(aux.GetSpirals3D().Add(c3d.o3d_cylindricSpiral), "Спираль")
parameters = ksapi.ICylindricSpiral3D(spiral)
parameters.SetBasePlane(base_plane)
parameters.SetBasePoint(0, 0)
parameters.SetDiameter(2 * radius)
parameters.SetBuildingType(c3d.ksSBTByStepAndTurnCount)
parameters.SetStep(pitch)
parameters.SetTurnsCount(turns)
parameters.SetBuildingDirection(True)
parameters.SetTurnDirection(True)
parameters.SetTurningAngle(0)  # Градусы.
require(parameters.Update(), "Построение спирали")

operation = require(model.GetEvolutions().Add(c3d.o3d_bossEvolution), "Кинематическая операция")
operation.SetSketch(profile)
operation.SetEdges([spiral])
operation.SetOperationResult(c3d.ksOperationNewBody)
operation.SetSketchShiftType(c3d.ksEvShiftKeepAngle)
require(operation.Update(), "Профиль вдоль спирали")
```

`ksEvShiftParallel=0` сохраняет параллельность профиля, `ksEvShiftKeepAngle=1` — угол с направляющей, `ksEvShiftOrtogonal=2` ставит профиль по нормали.

**Проверено в КОМПАС:** короткий образец с профилем по радиусам 9,5…10,5 мм, шагом 1 мм и тремя витками; габариты ±10,5 мм и Z=−0,3…3,3 мм. Для пружины отдельно проверьте опорную плоскость (§25), для резьбы — форму и посадку. Короткая спираль не доказывает пригодность длинной резьбы.

## 21. Повернуть и перенести тело внутри детали

Это меняет **геометрию детали**, а не положение её вхождения в сборке. Для сборки используйте §16 или §27.

Нужны `model`, тело `body`, угол `angle` в радианах и перенос `tx`, `ty`, `tz` в мм.

```python
import math

co, si = math.cos(angle), math.sin(angle)
matrix = [co, si, 0, 0, -si, co, 0, 0, 0, 0, 1, 0, tx, ty, tz, 1]
operation = require(model.GetBodyRepositions().Add(), "Перенос тела")
operation.SetRepositionBody(body)
operation.SetCopyBody(False)
operation.GetPosition().InitByMatrix3D(matrix)
require(operation.Update(), "Преобразование тела")
```

**Проверено в КОМПАС:** призма 4×2×3 мм после поворота +90° вокруг Z и переноса `(10,20,30)` получила габариты `(8,20,30)…(10,24,33)`.

У этой операции `GetResultBodies()` оказался пустым, хотя тело было преобразовано. Проверяйте конечные тела через `ksapi.IFeature(part).GetResultBodies()` и их габариты. Не переносите это объяснение на любую неудачную операцию.

## 22. Не перепутать направление смещения плоскости

Имя XOZ или YOZ не говорит, куда направлена её нормаль. Из-за этого положительное расстояние может дать смещение не в ту мировую сторону.

1. Прочитайте начало и две оси пробного эскиза на базовой плоскости (§19).
2. Вычислите единичную нормаль: векторное произведение осей, делённое на его длину.
3. Для плоскости, перпендикулярной мировой оси `axis`, используйте `SetOffset(abs(offset))` и `SetDirection(offset * normal[axis] > 0)`.
4. Прочитайте начало полученного эскиза и проверьте направление будущего выреза.

`offset` здесь — разность целевой и исходной координаты в мм. Для произвольно наклонённой плоскости сначала вычислите подписанное расстояние вдоль её нормали, а не мировую координату.

**Проверено в КОМПАС:** радиальные отверстия показывали зеркальный перенос при выборе направления только по `offset > 0`. Общая формула для произвольных наклонов отдельным прогоном не подтверждена.

## 23. Разобраться с ошибкой булевой операции

Ошибка 5 («объект не найден») **не обязательно означает потерянную ссылку на тело**. Она встречалась и при касании инструмента с уже существующим отверстием.

`body.CheckIntersectionWithBody(other, True)` в простых пробах возвращал:

- `[]` — тела раздельны;
- `[3]` — внешнее касание;
- `[4]` — объёмное пересечение, вложение или совпадение.

Это проверенные случаи, не полный справочник всех кодов. Для вычитания нужен удаляемый объём. Если инструмент доказанно не пересекает материал, повтор той же операции ничего не исправит.

Ненужное вспомогательное тело удаляется через `ksapi.ISurfaceContainer(part).GetBodySurfaceRemovers().Add()` → `SetDeletingObjects([tool])` → `Update()`. Скрыть тело недостаточно: оно останется в геометрии.

При объединении сложных совпадающих торцов помогал общий цилиндрический сердечник внутри исходной формы: одна половина + сердечник, затем другая. Это допустимо только если сердечник не добавляет материал за заданную оболочку. Полностью вложенный заполнитель может быть лишней операцией.

### Ускорить повторные вырезы

Создайте один инструмент или минимальную группу, размножьте тела (§15), затем вычтите исходники и копии одной булевой операцией. Непересекающиеся инструменты передаются списком в `SetInitialObjects`; объединять их заранее не нужно. Такой способ проверен в КОМПАС, но сравнительное ускорение времени не измерено.

### Импортировать сложную деталь, если пользователь разрешил STEP

Сначала проверьте `documents.GetItemByFilePath(absolute_source_step)`: уже открытый чужой документ не меняйте ради импорта. Для своего документа используйте `documents.Open(absolute_source_step, True, True)`, сразу зарегистрируйте его в `owned`, проверьте тела/форму и сохраните в новый `.m3d`. Закройте свой документ в `finally`.

Импорт и сохранение проверены в КОМПАС. Однако импортированное тело без эскизов — не нативное параметрическое построение. Сохраняйте отметку `imported_geometry=True` и `source_step`. Если STEP уже в мировых координатах, не переносите его повторно. Не переходите к импорту автоматически после ошибки.

## 24. Закрыть только свои временные документы

`owned` — обычный Python-список документов, созданных или открытых **этим запуском**. Это не свойство КОМПАС.

```python
owned = []
try:
    doc, part, model = new_part(app, "Временная деталь", owned=owned)
    # Построение, проверка, при необходимости сохранение.
finally:
    close_owned(owned)
```

`new_part` регистрирует документ сразу после создания, до получения `part`. Это позволяет закрыть его даже при ошибке подготовки.

`close_owned` из `basic_part.py` делает следующее:

```python
def close_owned(owned):
    while owned:
        doc = owned[-1]
        require(doc.Close(c.kdDoNotSaveChanges), "Закрытие собственного документа")
        owned.pop()
```

Закрытие идёт в обратном порядке, **без сохранения новых изменений**. Ранее сохранённый файл остаётся на диске. Это уборка временных документов, не Undo.

Уже открытые документы пользователя в список не добавляются. Название «Деталь без имени» не доказывает, что документ ваш. После обрыва API не продолжайте вызовы закрытия вслепую.

Для перечисления документов используется `documents.GetItem(i)` с индексами **от 1 до Count**: `range(1, documents.GetCount()+1)`. Сначала получите список, потом закрывайте свои документы — не меняйте коллекцию во время индексного обхода. Путь документа — `GetFullPath()`, не `GetPathName`.

## 25. Проверить ошибки дерева и опору эскиза

Для обычной правки начните с `GetObjectError()` затронутой операции. Полный обход нужен для регрессии, неясной ошибки/сломанных зависимостей или явно запрошенного аудита, а не после каждого изменения. `Update=True`, успешное перестроение и одно тело не означают, что все операции исправны.

Готовая функция `feature_errors(part)` из `basic_part.py` обходит полное дерево, включая скрытые эскизы. Для самостоятельного обхода нужны `ksapi.IFeature(obj).GetObjectError()` и рекурсивный `GetSubFeatures(c.ksOperTree, True, True)`. Пропускайте пустые ссылки и уже посещённые `reference`. В ошибке полезны путь элемента, тип, код и состояние.

`GetState()` — набор флагов, не код ошибки: `0x8` — зависимость от ЛСК, `0x100` — недоопределённый эскиз, `0x200` — определённый, `0x2` — нужно перестроение, `0x2000` — фиксация компонента. Ненулевое значение само по себе не ошибка.

Код `GetObjectError()==54` означает «Неизвестная ошибка». В одной пробе причина оказалась потерянной опорной плоскостью: `sketch.GetPlane()` вернул `None`. Не расшифровывайте код 54 всегда как потерю плоскости.

### Эскизу с собственной системой координат всё равно нужна плоскость

Одного `sketch.SetCoordinateSystem(lcs)` недостаточно. Перед первым обновлением и редактированием:

1. Создайте три точки `origin`, `origin+u`, `origin+v`, где `u/v` — независимые направления плоскости. API: `model.GetPoints3D().Add()`, `SetX/SetY/SetZ`, `Update()`.
2. Создайте плоскость: `aux.GetPlanes3D().Add(c3d.o3d_plane3Points)` → `ksapi.IPlane3DBy3Points(plane)` → `SetPoint1/2/3` → `Update()`.
3. Назначьте эскизу и `SetPlane(plane)`, и `SetCoordinateSystem(lcs)`.

Точки и плоскость можно скрыть, но не удалять. Для спирали с началом на +X касательная равна `(0,R,pitch/(2*pi))`; с ней согласуется нормаль круглого профиля пружины.

Такой профиль проверен в КОМПАС на короткой пружине: R3, проволока радиуса 0,5 мм, шаг 2 мм, три витка. Позднее назначение плоскости уже ошибочному эскизу не сняло ошибку: не считайте это готовым ремонтом.

## 26. Скрыть группу деталей, не меняя структуру сборки

Для совместного скрытия используйте слой, а не искусственную подсборку. Нужны `doc` и выбранные вхождения `components`.

```python
manager = ksapi.IKompasDocument3D(doc).GetDocument3DManager()
layers = manager.GetLayers3D()
layer = layers.GetLayer3DByName("Опоры")
if not layer:
    layer = require(layers.Add(), "Новый слой")
    layer.SetName("Опоры")
layer.SetVisible(True)
require(layer.Update(), "Слой")
for component in components:
    component.SetLayerNumber(layer.GetNumber())
    component.Update()
manager.Update()
```

Для скрытия — `layer.SetVisible(False)`, затем `layer.Update()` и `manager.Update()`; для показа — `True`. **Проверено в КОМПАС.** `component.GetVisibleState()` не обязательно отражает скрытие через слой; проверяйте и слой, и вид сборки.

Менеджер получается через `GetDocument3DManager()`: прямое приведение `IDocument3DManager(doc)` не сработало. `PartsGroupNumber` — группировка позиций спецификации, не видимость; пользовательские папки в прежней пробе не создались.

Меняйте иерархию только ради реальной структуры монтажа. Для разворачивания подсборки нужно сохранить мировые размещения, ссылки, цвета, фиксацию, слои и сопряжения; при неединичных размещениях родителя/детей требуется композиция матриц. Удаляется вставка через `IFeature(instance).Delete()`, а не файлы деталей. Подсчёт деталей должен рекурсивно считать конечные детали, не только верхние узлы.

Не считайте готовым способом создания подсборки `AddFromFile(..., externalFile=False)`: в пробе он вставлял тело. `CreateDocument('', c.ksDocumentAssembly, True, True)` дал локальную `.m3d`, а `MoveParts=True` не создал нужного дерева.

## 27. Задать сопряжения и ограничить ход

Сопряжение задаёт связь между вхождениями: соосность, совпадение плоскостей, расстояние, параллельность. **Проверено в КОМПАС** на простых сборках и механизме.

Нужны `doc`, выбранные объекты `base1/base2`, тип `kind`, ориентация `alignment` и значение `value` в единицах этого типа.

```python
mates = ksapi.IKompasDocument3D(doc).GetMateConstraints()
mate = require(mates.Add(kind), "Сопряжение")
mate.SetBaseObject1(base1)
mate.SetBaseObject2(base2)
mate.SetFixed(c3d.ksMFixedPart1)
mate.SetAlignment(alignment)
mate.SetParamValue(value)
require(mate.Update(), "Применение сопряжения")
require(ksapi.IFeature(mate).GetObjectError() == 0, "Ошибка сопряжения")
```

Типы: `c3d.mc_Concentric`, `mc_Coincidence`, `mc_Distance`, `mc_Parallel`. Расстояния — мм; единицы угла смотрите для конкретного типа.

**Не путайте два вида фиксации:** `mate.SetFixed(ksMFixedPart1)` выбирает сохраняемую сторону решения; `component.SetFixed(True)` закрепляет само вхождение в сборке. Для подвижного вхождения — `False`, проверка — `IsFixed()`.

Выбирайте поверхности по форме, размеру и назначению, не по номеру грани. Они доступны через `ksapi.IModelContainer(component).GetObjects(c3d.o3d_face)`. Для общей исходной системы координат можно использовать базовые плоскости `GetDefaultObject(o3d_planeXOY/XOZ/YOZ)`.

### Проверить, куда переместил детали решатель

Чистое дерево не гарантирует правильного положения. После сопряжения сравните положение затронутых вхождений с ожидаемым; если меняется ориентация, учитывайте полную матрицу, не только перенос. Не требуется обходить все неизменившиеся вхождения сборки. Для расстояния `abs(z2-z1)` может выбрать неверную сторону. У внутренних цилиндров направление параметрической оси не определяет нужное выравнивание; в проверенном случае использовалось `c3d.ksMCAlignmentClosest`.

Для совпадающих физических торцов учитывайте ориентацию граней; общие исходные XY-базы подходят только деталям, действительно построенным в общей системе координат. Три независимых сонаправленных совпадения XY/XZ/YZ могут задать жёсткую связь, но это связь технологических баз, не модель физических контактов.

Соосность + торец оставляют вращение; параллельность поперечной плоскости запрещает проворот. Лишние упоры с обеих сторон могут переопределить механизм.

### Ограничить осевой ход

Нужны сопряжение расстояния `distance_mate` и границы `min_value/max_value` в мм.

```python
interval = ksapi.IMateInterval(distance_mate)
interval.SetUseInterval(True)
require(interval.SetValueRange(min_value, max_value), "Границы хода")
require(distance_mate.Update(), "Применение интервала")
require(abs(interval.GetMinValue() - min_value) < 1e-6, "Нижняя граница")
require(abs(interval.GetMaxValue() - max_value) < 1e-6, "Верхняя граница")
```

**Сначала включите интервал, затем задайте диапазон.** Обратный порядок в пробе приводил к сохранённым границам `0..0` без ошибки дерева. Не фиксируйте обе стороны, если решатель должен переместить одну из них.

Диапазон −2…+1 мм проверен после сохранения и повторного открытия копии; реальное смещение составило около −0,9974 мм для пробы примерно на −1 мм. Это не гарантия произвольной точности. Проверяйте реальный ход и запрещённые перемещения на копии.

После удаления сопряжений в коллекции возможны пустые места — пропускайте `None`. Заданное через `SetName` имя в пробе не сохранялось; не используйте выдуманное имя для поиска. Сопряжения не создают автоматически передачу вращения, винтовую связь, упругость или контактную динамику.

### Тонкость выбора поверхности

У проверенной цилиндрической поверхности `GetMathSurface().GetPoint(0,0)` и `GetPoint(pi,0)` давали противоположные точки; их среднее лежит на оси, а разность `GetPoint(0,1)-GetPoint(0,0)` задаёт её направление. `pi` — радианы. Для других поверхностей параметризацию нужно проверять.

Математическую нормаль плоскости читайте через `GetMathSurface().GetNormal`. Для ориентации физического торца отдельно учитывайте топологическую `IFace.GetNormal(0,0)`; она в пробе не соответствовала параметрам точки математической поверхности. Принудительное выравнивание по параметрическим осям давало ошибку 59.

## 28. Изменить существующую сборку без пересоздания

Перед правкой коротко запишите: **что добавить, изменить, удалить и сохранить неизменным**.

1. Найдите документ по полному пути (§10). Не создавайте новую сборку вместо существующей и не переоткрывайте несохранённый документ пользователя.
2. Снимите только состояние, нужное для правки: для цвета — прежний цвет, для переноса — матрицу вхождения и влияющие сопряжения, для замены детали — источник и затронутые связи. Полный снимок сборки для локального изменения не нужен.
3. Выберите минимальную правку. Цвет — только свойства отображения; видимость — слой; положение — размещение или параметр сопряжения; размер — параметр существующей операции.
4. Измените выбранные объекты. Не вставляйте заново остальные детали и не пересоздавайте все сопряжения.
5. Перестройте зависимую часть и проверьте как изменение, так и то, что должно было остаться прежним.
6. Сохраните проверенный результат. Если важна сохранность ссылок и параметров на диске, проверьте повторное открытие копии.

`RebuildModel(True)` обновляет существующую модель. Это не то же самое, что удалить сборку и построить её заново.

При изменении формы могут исчезнуть прежние грани и рёбра. Заново получите нужные поверхности и исправьте только затронутые сопряжения. Универсальная замена детали с автоматическим сохранением всех связей не подтверждена; не подменяйте её незаметным удалением и повторной вставкой.

`reference` действует в текущей сессии, не является постоянным идентификатором после открытия файла. Различайте вхождения по пути в дереве и источнику; одного имени или индекса недостаточно.

В КОМПАС записывает **один процесс**. Независимые расчёты можно выполнять отдельно, но передавайте им зафиксированные входные данные и версию задачи; устаревший результат не применяйте. Undo — §29, повторное использование проверок — §30.

## 29. Сгруппировать правки и выполнить Undo/Redo

Группа позволяет отменить несколько изменений **одного документа** одним шагом. Полный работающий пример — [incremental_edit.py](../examples/incremental_edit.py): он создаёт свою временную деталь, меняет одну операцию и проверяет геометрию после Undo/Redo.

Нужны `doc3d = ksapi.IKompasDocument3D(doc)`, известная операция выдавливания `operation` и положительная глубина `depth` в мм. Во время пробы никто другой не должен менять документ.

```python
require(doc3d.IsEnableUndo(), "Undo выключен")
require(not doc3d.IsUndoContainer(), "Уже открыта чужая группа")
doc3d.SetUndoContainer(True)
try:
    require(doc3d.IsUndoContainer(), "Группа не открылась")
    require(operation.GetExtrusionType(True) == c3d.etBlind, "Нужна числовая глубина")
    operation.SetDepth(True, depth)
    require(operation.Update(), "Изменение глубины")
finally:
    doc3d.SetUndoContainer(False)
require(not doc3d.IsUndoContainer(), "Группа не закрылась")
```

`SetDepth(True, depth)` меняет прямую сторону, сохраняя профиль и остальные параметры. `SetDepth`, `SetUndoContainer` и `SetEnableUndo` возвращают `None`; успех проверяется чтением состояния.

**Закрытие группы не отменяет изменения.** Даже при исключении `finally` лишь завершает группу.

Для явного Undo, когда собственная непустая группа точно завершена и её результат проверен:

```python
doc.SetActive()
frame = require(doc.GetDocumentFrame(), "Окно документа")
active = app.GetActiveDocument()
require(active and active.reference == doc.reference and doc.IsActive() and frame.IsActive(), "Неверный документ")
require(not doc3d.IsUndoContainer(), "Сначала закройте группу")
command = c.ksCMEditUndo  # Для Redo: c.ksCMEditRedo.
require(frame.IsKompasCommandEnable(command), "Команда недоступна")
require(frame.ExecuteKompasCommand(command, False), "Команда Undo/Redo")
```

`False` во втором аргументе означает синхронное выполнение. Команды: Undo **57643**, Redo **57644**; не путайте с `prUndo/prRedo`. После команды заново получите используемые объекты и проверьте восстановленное значение/геометрию; матрицы и сопряжения — только если они затронуты.

**Проверено в КОМПАС:** одиночная и групповая правка глубины; перенос вхождения; создание, изменение расстояния и удаление сопряжений. Для двух переносов X `0→30→40` один Undo вернул `0`, Redo — `40`. Для расстояния `0→7→12` восстановились параметр и положение. Сравнивались полные матрицы, фиксация, базы сопряжений и дерево. Возврат `False` у `UpdatePlacement` разобран в §16.

**Ограничения:**

- Пустая группа не даёт права отменять предыдущий шаг. Доступная команда Undo может относиться к работе пользователя.
- При неизвестном результате вызова или обрыве API не выполняйте автоматическую отмену: сначала выясните состояние.
- Undo не отменяет запись файлов и не является общей транзакцией нескольких документов.
- Сложные смены формы, вращения и 2D Undo этой пробой не проверены.
- `ClearUndo()` очищает историю и возвращает bool; `SetEnableUndo(False)` отключает запись в историю. Они проверены только на временных документах и не нужны для обычной правки.

## 30. Не повторять неизменившуюся работу

Отдельно учитывайте **форму детали**, **положение в сборке**, **внешний вид** и **результаты проверок**. Изменение цвета не требует заново строить геометрию; перенос детали требует перепроверить сборочные зазоры, но не обязательно локальную форму детали.

**Чтобы повторно использовать результат, нужно знать, из чего он получен.** Запишите параметры, исходные файлы, версию кода/SDK и зависимости. Для автоматической проверки можно вычислять хеш содержимого. Наличие файла и время его изменения сами по себе не доказывают актуальность.

У проверки тоже есть условия: форма, положение, область, единицы, допуски и версия алгоритма. После изменения этих условий старый результат проверки нельзя считать актуальным.

Для дорогих проверок зазоров сначала используйте расчётные ограничения и габаритные коробки в общей системе координат, затем точную проверку нужных пар поверхностей. Быстрое отсечение должно быть консервативным. Несколько проверенных положений не доказывают отсутствие столкновений на всём ходе. Не импортируйте повторно неизменную геометрию только ради её размеров.

**Контрольное сохранение** — проверенная версия, к которой можно вернуться. Для длительного процесса храните путь, версию входных данных и последний успешный этап. Хеширование и замеры времени нужны для автоматического reuse и оптимизации, не для каждой ручной правки. Если делаете benchmark, отдельно измеряйте построение/правку, перестроение, проверку, сохранение и экспорт. Сравнивайте одинаковую правку одной исходной модели с одинаковыми проверками; число операций не равно времени.

Экспорт STEP/STL, сетка и рендер нужны только как отдельный запрошенный результат, после проверки CAD. Для нового массового экспорта сначала проверьте два разных компонента: геометрию, единицы, соответствие вхождениям и ориентацию. Не угадывайте соответствие по порядку объектов. Сетку можно сохранить, если форма и настройки разбиения не изменились; положение и цвет обновляются отдельно.

Переносимый комплект требует всех внешних зависимостей. Проверьте его открытие из нового расположения без старых путей: один `SaveAs` этого не обеспечивает. Не выдавайте промежуточный или устаревший результат за окончательный.

## 31. Родное отверстие, а не окружность-вырез

[13_native_hole.py](../examples/13_native_hole.py) делает **Holes3D** в пластине 60 × 40 × 10: Ø10, глубина 6, плоское дно, центр (12,7), вход с верхней грани Z=10. В дереве сохраняются диаметр, глубина и опорная поверхность родной операции.

Основная цепочка:

1. Найти верхнюю плоскую грань по геометрии, не по номеру.
2. `model.GetHoles3D().Add()`; `SetHoleType(c3d.ksHTBase)`, `SetDiameter(10)`, `SetDepthType(c3d.ksDTValue)`, `SetDepth(6)`, `SetEndFaceType(c3d.ksEFFlat)`.
3. Через `ksapi.IHoleDisposal(hole)` назначить `SetBaseSurface(face)`, `SetPerpendicular(True)`, `SetOffsetType(c3d.ksOffsetByCoords)`.
4. Получить `disposal.GetPoint3DParamSurface()`, задать `SetOffset1/SetOffset2` и `SetSurfaceObject(face)`, затем `hole.Update()`.

Координаты точки поверхности относятся к её параметризации; нельзя переносить `(12,7)` на произвольную грань как гарантированные мировые XY.

В Linux-прогоне `SetSurfaceObject(base)` вернул `False`, но отверстие построилось точно в (12,7) и прошло повторное открытие. Пример выводит этот статус, а принимается только по последующей проверке геометрии. Это не основание игнорировать `False` у других методов.

Режимы «через всё», цековка, зенковка и резьба требуют собственных примеров и геометрических проверок; успешное простое глухое отверстие не подтверждает остальные режимы.

## 32. Оболочка: коробка с открытым верхом

[14_shell.py](../examples/14_shell.py) выдавливает блок 60 × 40 × 20, удаляет верхнюю грань Z=20 и делает стенку 2 мм **внутрь**. Это родной `IShell`, не булево вычитание второго блока.

Маршрут: найти верхнюю грань по положению → `model.GetShells().Add()` → `SetDeletedFaces([top_face], False)` → `SetThinType(c3d.dtReverse)` → `SetThickness(2)` → `Update()`. Второй аргумент `SetDeletedFaces` управляет включением касательных граней. Для оболочки этот `dtReverse` означает внутрь; не переносите семантику направления выреза на другую операцию.

Наверху остаётся плоский ободок — это нормально, он не закрывает коробку. Подробные измерения примера — в [документе о проверках](examples.md).

## 33. Выбрать грань или окружность по геометрии

[geometric_selection.py](../examples/geometric_selection.py) — самостоятельный пример: скопировать в макрос только нужные функции, не импортировать скилл как библиотеку. Селекторы не меняют модель и не запускают CAD; запуск примера создаёт и закрывает только свою временную деталь. Нужны `part` и **текущее результирующее тело** `body`; принадлежность объектов телу проверяется через `GetBody()`. После rebuild/Undo/reopen заново получить тело и вызвать селектор, не хранить прежние topology references.

- `select_plane(part, body, point=..., normal=..., length_tol=..., angle_tol=...)`: плоская грань с нормалью, параллельной заданной, и опорной плоскостью через `point`. Сравниваются нормализованные направления и расстояние до плоскости. **Не проверяет попадание точки внутрь обрезанного контура**; несколько копланарных граней — неоднозначность, а не право выбрать первую.
- `select_circle(part, body, center=..., radius=..., normal=..., length_tol=..., angle_tol=...)`: целое круговое ребро по центру, радиусу и нормали плоскости. Дуги и эллипсы исключены. Центр/радиус читаются из `IMathCurve3D`, не вычисляются по bounding box.
- `select_cylinder(part, body, radius=..., axis_point=..., axis=..., span=(t0, t1), length_tol=..., angle_tol=...)`: радиус, направление и положение осевой прямой, затем осевая протяжённость ограниченной грани. `span` задаётся в мм от `axis_point` вдоль нормализованного **заданного** `axis`; при смене знака оси меняются знаки/порядок интервала. Не путать диапазон вдоль оси с мировыми Z.

Начало и ось аналитической поверхности/окружности читаются через `GetPlacement().GetOrigin(...)` и `GetVector(c3d.o3d_axisOZ, ...)`. Нормаль/ось сравниваются **без знака**: `n` и `−n` эквивалентны; это не выбор внешней стороны тела. Координаты должны быть в одной системе детали; размещения вхождений сборки автоматически не применяются.

Допуски **обязательны**: `length_tol` — положительное расстояние в мм для координат/радиусов; `angle_tol` — угловое отклонение в радианах. Значения `1e-5` мм и `1e-7` рад в пробе относятся только к её аналитической геометрии, не универсальный производственный допуск. Проверяются статусы выходных кортежей, конечность чисел и ненулевые направления; ошибка чтения не маскируется пропуском кандидата.

Ноль или несколько совпадений дают `ValueError` с запросом, количеством совпадений и измеренными признаками кандидатов. Нет выбора по индексу, ближайшему объекту или автоматического расширения допуска. Для уточнения ограничить тело/геометрические признаки под задачу.

**Граница цилиндрического рецепта:** протяжённость читается по полным круговым торцам, перпендикулярным оси, и концам прямых швов. Подходящий по опорному цилиндру кандидат с дуговой/сплайновой или иной неподдерживаемой обрезкой останавливает выбор: нужен отдельный маршрут точного анализа границ, не подмена мировым AABB или выборкой точек. Совпадение опорного цилиндра и осевого диапазона не доказывает полноту стенки, отсутствие разрывов или назначение «отверстие»; это выбор объекта, не общий валидатор топологии.

**Проверено в КОМПАС Linux v25:** своя временная кольцевая деталь R5…15 × 10; выбор верхней плоскости, внутренней верхней окружности и обеих цилиндрических стенок, повтор после rebuild и после поворота на 45° вокруг Y с переносом (10,20,30). Противоположные направления нормали/оси принимаются. Отказ при нуле/двух совпадениях проверен на списках кандидатов; mock-тесты отдельно проверяют фильтрацию тела, неверные признаки, ошибки чтения и неподдерживаемую обрезку. Пример завершился с кодом 0, собственный документ закрыт без сохранения. Сборочные координаты, произвольные обрезки и Undo/reopen этим прогоном не квалифицированы.

## 34. Диагностический указатель: симптом → действие

Читать только ветку наблюдаемой ошибки; это не обязательный checklist построения.

- **Грань/ребро недоступны после rebuild, Undo или reopen:** получить текущие тела и повторить геометрический выбор (§33). Старый `reference` не постоянный ID; затронутые зависимости — §28, Undo — §29.
- **Нет совпадения или совпадений несколько:** прочитать признаки кандидатов, проверить тело, систему координат, радиус, осевую прямую и диапазон (§33). Уточнить запрос; не брать первый индекс и не увеличивать допуск вслепую.
- **Setter/Update прошёл, но форма прежняя или другая:** проверить фактическую затронутую геометрию и применимость режима. Для глубины проверить сторону операции (§6), для управляющего размера — [квалифицированный маршрут](ksapi.md#размерные-зависимости-эскиза-доступность-и-квалификация); не подбирать цепочки rebuild. `None` у setter не ошибка, `True` не доказательство формы.
- **Вызов оборвался или не завершился, результат неизвестен:** остановить новые записи; сохранить последний этап/traceback, проверить документ и возможную модальность после восстановления доступа. Не повторять запись и не делать автоматический Undo (§29); правила модальных диалогов — [сохранение без диалогов](../SKILL.md#сохранение-без-диалогов-перезаписи).

Если неизвестно имя/маршалинг конкретного метода — адресный `sdk.py inspect`/`page` из [диагностики скилла](../SKILL.md#адресная-диагностика), не повторное исследование всех уже известных операций.
