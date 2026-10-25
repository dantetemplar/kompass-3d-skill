# Операции и тела

#### Выдавливание и вырез

1. Прочитать `iextrusions_add`: разрешены `o3d_bossExtrusion` и `o3d_cutExtrusion`.
2. `IModelContainer.GetExtrusions()` → `IExtrusions`; `IExtrusions.Add(extrusionType)` → `IExtrusion`.
3. В нативном KsAPI `IExtrusion.SetProfiles(profiles)` принимает коллекцию ссылок через `ToObjectReferenceVector`. Документационный поиск по слову `Profile` может показывать другой интерфейс, например `IExtrusion1`; проверить владельца перед переносом.
4. Проверить `IExtrusion.SetDirection` и константы направления; для сторон операции изучить `SetSideParameters(self, normal, extrusionType, depth, draftValue, draftOutward, depthObject)`.
5. Константу способа ограничения, допустимость `depthObject` и поведение первой операции брать из справки. `normal` задаёт сторону, `extrusionType` здесь — способ ограничения, не тип операции из `IExtrusions.Add`. Для выреза из нижней XOY в материал Z>0 использовать `SetDirection(c3d.dtReverse)` и `SetSideParameters(False, ...)`; направление и сторона глубины задаются согласованно.
6. Вызвать унаследованный `IModelObject.Update()`, проверить его результат; выполнить `IPart.RebuildModel(redraw)`.
7. Проверить фактические глубину, направление, число тел и габариты через доступные getters. Для выреза проверить изменение геометрии, а не только наличие операции в дереве.

### 6. Выдавить профиль или сделать вырез

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
- Для выреза из нижней XOY в материал Z>0 используйте пару `dtReverse` + `SetSideParameters(False, ...)`, не `dtNormal`. Успешный статус операции не доказывает наличие отверстий.
- `etBlind` — ограничение числовой глубиной; `0.0` — нулевой уклон.
- `None` — нет объекта, ограничивающего глубину в этом режиме.
- `SetProfiles` принимает список эскизов и возвращает `None`.

**Проверьте:** тело появилось с нужной стороны; вырез действительно удалил материал. Для сквозного отверстия в простой пластине из примера глубина равна её толщине. Это не универсальный режим «через всё»; не подменяйте его произвольно большим числом.

### 12. Построить деталь вращением

Пример создаёт втулку вокруг OY: внутренний радиус 5 мм, наружный 15 мм, длина 20 мм. Нужны `app` и образец документа из [04_revolve.py](../examples/04_revolve.py) / [§2](documents.md#2-подключиться-и-создать-документ).

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

**Результат:** одно твёрдое тело, габариты `(-15, 0, -15, 15, 20, 15)`.

`SetProfile` принимает один эскиз. Ось вращения лежит в его плоскости. Угол — градусы; `True` в `SetAngle/SetRotatedType` выбирает прямую сторону. Незамкнутый профиль, тонкая стенка и вырез вращением требуют отдельной проверки.

### 13. Создать эскиз на смещённой плоскости

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

**Результат:** одно тело, габариты `(-5, -5, 15, 5, 5, 20)`.

`IAuxiliaryGeomContainer` запрашивается у **детали**, не у `model`. `SetDirection(True)` выбирает прямое смещение, `False` — обратное; расстояние положительное. Для других базовых плоскостей проверьте нормаль ([§22](#22-не-перепутать-направление-смещения-плоскости)).

### 14. Сделать фаску или скругление

Самостоятельные сценарии: [11_fillet_edit.py](../examples/11_fillet_edit.py) — четыре вертикальных угла пластины, R3 → R5 на том же признаке; [12_chamfer.py](../examples/12_chamfer.py) — фаски 2 × 2 мм на тех же четырёх углах. См. [каталог примеров](examples.md#каталог-готовых-примеров).

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

Перед построением явно решить: какие рёбра, в какую соседнюю грань «смотрит» фаска, выпуклое ребро (материал снимается) или вогнутое (скругление добавляет материал). Проверка по объёму: внешняя фаска/скругление уменьшает объём, внутреннее скругление — увеличивает. Обработку кромок ставить после операции, создавшей ребро; радиус/катет сверять с толщиной стенки.

### 15. Повторить тела или операции

#### Прямоугольный массив операций

[15_linear_pattern.py](../examples/15_linear_pattern.py) создаёт пластину 60 × 40 × 10, один сквозной вырез Ø4 с центром (−20,−10), затем размножает **операцию**, не рисует ещё пять окружностей.

Маршрут: `model.GetFeaturePatterns().Add(c3d.o3d_meshCopy)` → `ksapi.ILinearPattern(feature)` → `SetInitialObjects([seed])` → оси `SetAxis1(OX)`, `SetAxis2(OY)` → шаги 20/20 → количества 3/2 → `SetBuildingType(c.ksLPSaveAll)` → `Update()`. В коде также явно заданы направления и режим шага между соседними экземплярами.

`Count1/Count2` включают исходный экземпляр. Не устанавливайте `Angle2=0`: штатные 90° сохраняют две независимые оси, а нулевой угол может свести сетку в линию.

Проверяются **все шесть стенок** Ø4 на Z=0…10, центры `X=(-20,0,20)`, `Y=(-10,10)`, объём `24000 - 6*pi*2**2*10`. Совпадения счётчиков недостаточно. Этот пример относится к прямоугольной сетке на плоской пластине, не к произвольным криволинейным массивам.

#### Круговой массив отдельных тел

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

Для четырёх цилиндров на R10 ожидаемые центры — `(±10,0)` и `(0,±10)`. Угол — градусы. `Count1/Step1` относятся к радиальному направлению, `Count2/Step2` — к обходу окружности. При `BoundaryInstancesStepFactor2=False` шаг — между соседними экземплярами.

Для этого массива `GetResultBodies()` содержит **три новые копии**, исходное тело учитывается отдельно. Проверяйте все конечные тела детали.

Для оси на пересечении двух плоскостей: `aux.GetAxes3D().Add(c3d.o3d_axis2Planes)` → `ksapi.IAxis3DBy2Planes(axis)` → `SetPlane1/SetPlane2` → `Update()`.

#### Круговой массив операций — требует отдельной проверки

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

`GetExemplarsCounts(0,0)` возвращает `(status,count1,count2)`, но дополнительно нужно проверить сами отверстия.

Для сложных тел проверяйте сначала две копии, затем небольшой массив и только потом нужное количество. Успех маленькой пробы не гарантирует успех большого массива или последующего объединения.

### 19. Создать отдельные тела, объединить их или построить по сечениям

Нужны объекты одной детали.

#### Отдельное тело

До `operation.Update()` вызовите `operation.SetOperationResult(c3d.ksOperationNewBody)`.

Режимы результата операции: `ksOperationUnion=0`, `ksOperationNewBody=1`, `ksOperationCut=2`, `ksOperationIntersect=3`.

#### Вычитание одного тела из другого

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

Для объединения — `c.ksUnion`, для пересечения — `c.ksIntersect`. Значения **другого перечисления**: пересечение 1, вычитание 2, объединение 3. Не путайте их с режимами результата выше. Тип задавайте после объектов. Для простых тел также можно задать `SetBodies([base_body, *tool_bodies])`.

#### Замкнутый многоугольник одним вызовом

```python
polyline = require(drawing.GetPolyLines2D().Add(), "Полилиния")
polyline.SetPoints([0, 0, 40, 0, 30, 20, 0, 20])
polyline.SetClosed(True)
require(polyline.Update(), "Контур")
```

#### Элемент по сечениям

Нужны завершённые эскизы `sk0`, `sk1`, `sk2`.

```python
loft = require(model.GetLofts().Add(c3d.o3d_bossLoft), "Элемент по сечениям")
loft.SetProfiles([sk0, sk1, sk2])
loft.SetClosed(False)
loft.SetOperationResult(c3d.ksOperationNewBody)
require(loft.Update(), "Построение по сечениям")
```

Проверьте форму между сечениями, а не только число тел.

#### Перевод координат эскиза в мировые

`sketch.GetPoint3D(0,0,0,0,0)`, `GetPoint3D(1,0,0,0,0)` и `GetPoint3D(0,1,0,0,0)` возвращают `(status,x,y,z)`. Разности точек дают две оси эскиза. Считайте их один раз, затем преобразуйте все координаты локально. Обратная проекция: `GetPointProjectionToXY(x,y,z,0,0)` возвращает статус и две координаты.

### 20. Построить спираль и протянуть по ней профиль

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

Для образца с профилем по радиусам 9,5…10,5 мм, шагом 1 мм и тремя витками ожидаемые габариты — ±10,5 мм и Z=−0,3…3,3 мм. Для пружины отдельно проверьте опорную плоскость ([§25](validation.md#25-проверить-ошибки-дерева-и-опору-эскиза)), для резьбы — форму и посадку. Короткая спираль не доказывает пригодность длинной резьбы.

### 21. Повернуть и перенести тело внутри детали

Это меняет **геометрию детали**, а не положение её вхождения в сборке. Для сборки используйте [§16](assemblies.md#16-вставить-деталь-в-сборку-и-переместить-вхождение) или [§27](assemblies.md#27-задать-сопряжения-и-ограничить-ход).

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

**Результат:** призма 4×2×3 мм после поворота +90° вокруг Z и переноса `(10,20,30)` имеет габариты `(8,20,30)…(10,24,33)`.

У этой операции `GetResultBodies()` может быть пустым даже после преобразования тела. Проверяйте конечные тела через `ksapi.IFeature(part).GetResultBodies()` и их габариты. Не переносите это объяснение на любую неудачную операцию.

### 22. Не перепутать направление смещения плоскости

Имя XOZ или YOZ не говорит, куда направлена её нормаль. Из-за этого положительное расстояние может дать смещение не в ту мировую сторону.

1. Прочитайте начало и две оси пробного эскиза на базовой плоскости ([§19](#19-создать-отдельные-тела-объединить-их-или-построить-по-сечениям)).
2. Вычислите единичную нормаль: векторное произведение осей, делённое на его длину.
3. Для плоскости, перпендикулярной мировой оси `axis`, используйте `SetOffset(abs(offset))` и `SetDirection(offset * normal[axis] > 0)`.
4. Прочитайте начало полученного эскиза и проверьте направление будущего выреза.

`offset` здесь — разность целевой и исходной координаты в мм. Для произвольно наклонённой плоскости сначала вычислите подписанное расстояние вдоль её нормали, а не мировую координату.

Не выбирайте направление только по `offset > 0`: учитывайте нормаль базовой плоскости, иначе возможно зеркальное смещение радиальных отверстий. Для произвольных наклонов проверяйте полученное положение эскиза.

### 23. Разобраться с ошибкой булевой операции

Ошибка 5 («объект не найден») **не обязательно означает потерянную ссылку на тело**. Она может возникать и при касании инструмента с уже существующим отверстием.

Для простых тел результаты `body.CheckIntersectionWithBody(other, True)` трактуются так:

- `[]` — тела раздельны;
- `[3]` — внешнее касание;
- `[4]` — объёмное пересечение, вложение или совпадение.

Это не полный справочник всех кодов. Для вычитания нужен удаляемый объём. Если инструмент доказанно не пересекает материал, повтор той же операции ничего не исправит.

Ненужное вспомогательное тело удаляется через `ksapi.ISurfaceContainer(part).GetBodySurfaceRemovers().Add()` → `SetDeletingObjects([tool])` → `Update()`. Скрыть тело недостаточно: оно останется в геометрии.

При объединении сложных совпадающих торцов можно использовать общий цилиндрический сердечник внутри исходной формы: одна половина + сердечник, затем другая. Это допустимо только если сердечник не добавляет материал за заданную оболочку. Полностью вложенный заполнитель может быть лишней операцией.

#### Ускорить повторные вырезы

Создайте один инструмент или минимальную группу, размножьте тела ([§15](#15-повторить-тела-или-операции)), затем вычтите исходники и копии одной булевой операцией. Непересекающиеся инструменты передаются списком в `SetInitialObjects`; объединять их заранее не нужно.
#### Импортировать сложную деталь, если пользователь разрешил STEP

Сначала проверьте `documents.GetItemByFilePath(absolute_source_step)`: уже открытый чужой документ не меняйте ради импорта. Для своего документа используйте `documents.Open(absolute_source_step, True, True)`, сразу зарегистрируйте его в `owned`, проверьте тела/форму и сохраните в новый `.m3d`. Закройте свой документ в `finally`.

Импортированное тело без эскизов — не нативное параметрическое построение. Сохраняйте отметку `imported_geometry=True` и `source_step`. Если STEP уже в мировых координатах, не переносите его повторно. Не переходите к импорту автоматически после ошибки.

### 31. Родное отверстие, а не окружность-вырез

[13_native_hole.py](../examples/13_native_hole.py) делает **Holes3D** в пластине 60 × 40 × 10: Ø10, глубина 6, плоское дно, центр (12,7), вход с верхней грани Z=10. В дереве сохраняются диаметр, глубина и опорная поверхность родной операции.

Основная цепочка:

1. Найти верхнюю плоскую грань по геометрии, не по номеру.
2. `model.GetHoles3D().Add()`; `SetHoleType(c3d.ksHTBase)`, `SetDiameter(10)`, `SetDepthType(c3d.ksDTValue)`, `SetDepth(6)`, `SetEndFaceType(c3d.ksEFFlat)`.
3. Через `ksapi.IHoleDisposal(hole)` назначить `SetBaseSurface(face)`, `SetPerpendicular(True)`, `SetOffsetType(c3d.ksOffsetByCoords)`.
4. Получить `disposal.GetPoint3DParamSurface()`, задать `SetOffset1/SetOffset2` и `SetSurfaceObject(face)`, затем `hole.Update()`.

Координаты точки поверхности относятся к её параметризации; нельзя переносить `(12,7)` на произвольную грань как гарантированные мировые XY.

`SetSurfaceObject(base)` в этом примере может вернуть `False` при построенном отверстии. Выводите этот статус и принимайте результат только после проверки геометрии. Это не основание игнорировать `False` у других методов.

Режимы «через всё», цековка, зенковка и резьба требуют собственных примеров и геометрических проверок; успешное простое глухое отверстие не подтверждает остальные режимы.

### 32. Оболочка: коробка с открытым верхом

[14_shell.py](../examples/14_shell.py) выдавливает блок 60 × 40 × 20, удаляет верхнюю грань Z=20 и делает стенку 2 мм **внутрь**. Это родной `IShell`, не булево вычитание второго блока.

Маршрут: найти верхнюю грань по положению → `model.GetShells().Add()` → `SetDeletedFaces([top_face], False)` → `SetThinType(c3d.dtReverse)` → `SetThickness(2)` → `Update()`. Второй аргумент `SetDeletedFaces` управляет включением касательных граней. Для оболочки этот `dtReverse` означает внутрь; не переносите семантику направления выреза на другую операцию.

Наверху остаётся плоский ободок — это нормально, он не закрывает коробку.
