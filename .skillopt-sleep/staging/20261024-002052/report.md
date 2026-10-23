# SkillOpt-Sleep — night 1 report

- project: `/home/dante/Projects/dantetemplar/kompass-3d-skill`
- backend: `cursor`  replay: `mock`
- sessions harvested: 1
- tasks mined: 2  (replayed: 2)
- held-out score: 0.040 -> 0.040
- gate: **reject** (accepted=False)
- no-regression gate: disabled
- tokens used: 158414

## Held-out task changes
_These are observed score changes under the configured gate metric; they do not establish that a particular edit caused the change._

### `skill` candidate — rejected (0.040 → 0.040)

| Task | Tags | Baseline | Candidate | Change |
|---|---|---:|---:|---|
| `llm_f0d032b257cd` | mined:llm | 0.040 | 0.040 | unchanged |

### `memory` candidate — rejected (0.040 → 0.025)

| Task | Tags | Baseline | Candidate | Change |
|---|---|---:|---:|---|
| `llm_f0d032b257cd` | mined:llm | 0.040 | 0.025 | regressed |

### `final` candidate — rejected (0.040 → 0.040)

| Task | Tags | Baseline | Candidate | Change |
|---|---|---:|---:|---|
| `llm_f0d032b257cd` | mined:llm | 0.040 | 0.040 | unchanged |

## Rejected by gate (kept as negative feedback)
- \[skill/add\] OVERRIDE \(приоритет выше правил «самостоятельного макроса»\): если задача — организовать/реструктурировать репозиторий CAD-кода, ответ обязан содержать конкретную структуру слоёв, а не макрос и не обзор. Минимум: дерево каталогов с явными слоями \(примитивы/хелперы → детали → подсборки → верхняя сборка\) плюс отдельные места для параметров, проверок и точек запуска; односторонние зависимости \(верхние слои импортируют нижние, обратных импортов нет\); правило, что общий код живёт в библиотеке пакета и импортируется, а не копируется. Требование «копировать функции и не импортировать модули проекта» относится только к одноразовым макросам и НЕ применяется к библиотеке, которую пользователь просит выделить.
- \[skill/add\] В задачах реструктуризации сначала перечислить фактически существующие файлы, затем дать таблицу переноса «текущий файл → целевой слой/путь» для КАЖДОГО из них, отметив, что переименовывается, что объединяется и что остаётся точкой запуска. Не предлагать слои без этого сопоставления и не придумывать модули, которым не соответствует существующий код или явно названная потребность. Указать порядок миграции и то, как запускается результат после переноса.
- \[skill/add\] Все операции с выбором стороны \(вырез, смещённая плоскость, оболочка, фаска/скругление, зеркало, направление сопряжения\) задавать по измеренной геометрии: прочитать нормаль опоры/грани или габариты до вызова и после построения подтвердить фактическое изменение \(габарит, объём, положение новой поверхности\). Знак параметра, имя плоскости и успешный Update стороной не доказывают; при расхождении остановиться и сообщить измеренное против ожидаемого, а не менять знак перебором.
- \[skill/add\] В сборке положение каждого вхождения задавать от общих баз \(базовые плоскости/оси корпусной детали\), а не цепочкой «деталь к предыдущей детали»: такие каскадные сопряжения накапливают смещение и дают ступенчатое расположение. Стандартный крепёж и типовые изделия брать из библиотеки/готового файла, а не моделировать вручную; совместное скрытие делать слоями, подсборку создавать только для реально предварительно собираемого узла. После решателя проверять фактические матрицы затронутых вхождений.
- \[memory/add\] CAD/geometry codebase restructuring: answer with the concrete layered layout first, not with exploration narration. Always name the layers explicitly — primitives \(parametric solids/sketch helpers\), parts \(single-body components\), subassemblies \(functional groups\), top-level assembly — plus a separate place for shared parameters/units and for imported library geometry. Map every existing file into exactly one layer, and state the one-way dependency rule: a layer may import only from layers below it, never sideways into a sibling part or upward into an assembly.
- \[memory/add\] Assembly placement: position every component by an explicit transform against one shared global reference frame \(named datum planes/axes/origin\) with absolute offsets. Never chain placements part-to-part or offset a part relative to the previous part's face, since accumulated relative offsets produce staircase/step drift and mates that break on any parameter change. Each mate should be named and state which datum of the parent it constrains.
- \[memory/add\] Chamfers and fillets: state the edge set and the direction unambiguously — which adjacent face the chamfer leans into, and whether the edge is convex \(external, material removed\) or concave \(internal, material added\). Sanity-check direction by the volume change: a chamfer or external fillet must reduce volume, an internal fillet must increase it. Apply edge treatments after the feature that creates the edge, and keep radius/leg length as named parameters validated against local wall thickness.
- \[memory/add\] Mechanical content completeness: import standard fasteners and bearings as library/STEP parts referenced by full designation and size \(e.g. ISO/DIN/ГОСТ \+ thread \+ length\) instead of hand-modeling them, and keep them in the imported-geometry layer. Do not drop human-interface or functional features — enumerate grips/handles/ухваты, knurling, detents, and working profiles such as burr/cutter geometry as parameterized parts in the parts layer, with the burr cone angle, tooth pitch and gap driven by named parameters.

_Review the staged artifacts, then use the adoption mode printed by the run command (`--skill` / `--all-skills` for fan-out proposals, `--legacy` for the managed skill or memory), or discard this folder._