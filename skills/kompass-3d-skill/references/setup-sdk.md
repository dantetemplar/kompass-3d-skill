# Установка, SDK и запуск макросов

Все командные пути `scripts/`, `examples/` и `.cache/` в этом справочнике указаны относительно корня установленного скилла, а не каталога `references/`. Команды выполнять из корня скилла.

## Установка

Нужны установленный КОМПАС-3D с нативным KsAPI и действительной лицензией, `uv` и Bash. Для команды установки скилла нужны Node.js и npm (`npx`). Python 3.11+ может установить `uv`.

Установить скилл для Cursor:

```bash
npx skills add dantetemplar/kompass-3d-skill --skill kompass-3d-skill -g -a cursor
```

Сгенерировать документацию и стабы из установленного SDK. Выполнить из каталога установленного скилла; при другом расположении скилла или КОМПАС заменить пути:

```bash
cd ~/.cursor/skills/kompass-3d-skill
export LD_LIBRARY_PATH="/opt/ascon/kompas3d-v25/Bin${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PYTHONPATH="/opt/ascon/kompas3d-v25/Bin${PYTHONPATH:+:$PYTHONPATH}"
uv run --script scripts/prepare/prepare_docs.py
uv run --script scripts/prepare/prepare_stubs.py
```

Подготовка читает официальную WebHelp (`SDK/Help/KOMPAS_SDK_ru-RU.zip`), метаданные `SDK/KsAPIC/C/Include/KsAPIC.json` и нативный KsAPI установленного КОМПАС. Генераторы не импортируют `ksapi`, не запускают КОМПАС и не используют сеть; `uv` при необходимости может загрузить Python. Для полностью офлайн-подготовки заранее установить Python 3.11+ и задать `UV_OFFLINE=1` и `UV_PYTHON_DOWNLOADS=never`. Параметры путей доступны через `--help` обоих скриптов.

Результаты находятся внутри установленного скилла:

- `.cache/kompas-sdk-docs/` — документация и поисковый индекс: `llm/pages.jsonl` — корпус, `llm/api_objects/` — страницы интерфейсов, `index.sqlite3` — поиск и навигация.
- `.cache/kompas-stubs/` — типизированные объявления с docstrings и отчёт о неизвестных типах и конфликтах. Стабы используются для анализа и подсказок; при выполнении макроса — установленные Python-модули КОМПАС.

Manifest фиксирует источники и их хеши. Эти данные генерируются локально и не входят в исходники скилла. При переносе подготовленного скилла копировать и `.cache/`. Если индекс отсутствует, `sdk.py` укажет команду подготовки, не скачивая данные. Использование справки и выбор других каталогов описаны в разделе [документации и сигнатур API](#документация-и-сигнатуры-api).

Пути `scripts/`, `examples/` и `.cache/` далее указаны относительно каталога установленного скилла. Перед первым макросом подключиться к API-сессии по разделу [подключения](documents.md#подключение-без-автоматического-запуска).

## Документация и сигнатуры API

Скилл собирает документацию, создаёт стабы для типизации на базе той справки, что есть в локальном КОМПАС-3D; читать их можно через `scripts/sdk.py`. Команды выполнять из каталога скилла либо по абсолютному пути к скрипту. Также скилл предоставляет `check` утилиту, для проверки типизации согласно стабам.

**Сигнатура и описание символа — `doc`**

> Для известного символа использовать `doc`; если имя неизвестно — сначала `local` или `search`.

```bash
uv run --script scripts/sdk.py doc IExtrusion.SetSideParameters
uv run --script scripts/sdk.py doc ksEndTypeEnum
uv run --script scripts/sdk.py doc ISketch.BeginEdit ISketch.GetPoint3D
uv run --script scripts/sdk.py doc IText GetKompas constants3d.constants.o3d_planeXOY
```

Пример вывода (`IExtrusion.SetSideParameters`):

```python
# IExtrusion.SetSideParameters — .cache/kompas-stubs/ksapi.pyi:58119
# Python binding: /opt/ascon/kompas3d-v25/Bin/ksapi.py:40127
class IExtrusion(IModelObject):
    """Интерфейс IExtrusion …"""

    # 14 methods above: GetSideParameters, GetDepthObject, SetDepthObject, ...

    def SetSideParameters(
        self,
        normal: bool,
        extrusionType: ksEndTypeEnum,
        depth: float,
        draftValue: float,
        draftOutward: bool,
        depthObject: IModelObject | None,
    ) -> bool:
        """Установить параметры выдавливания в одном направлении

        Входные параметры:

        | Column 1 | Column 2 |
        | --- | --- |
        | normal | направление (true - прямое направление, false - обратное). |
        | extrusionType | тип выдавливания. |
        | depth | глубина выдавливания. |
        | draftValue | угол уклона (в градусах). |
        | draftOutward | признак уклона внутрь (true - наружу, false - внутрь). |
        | depthObject | объект, задающий глубину выдавливания (при типе операции до/за). |

        Возвращаемое значение:

        Успешность установки

        Примечание:

        1. Метод позволяет получать параметры операции выдавливания.

        2. Параметр Depth в позволяет задать на сколько выдавить за объект, задающий глубину выдавливания, или какое расстояние оставить до объекта, задающего глубину выдавливания - в зависимости от типа построения (для типов построения "до поверхности" и "до вершины" см. перечисление ksEndTypeEnum).

        Python binding:
        - depthObject: None is passed as native handle 0 (not necessarily valid for this operation).
        """
        ...

    # 9 methods below: SetDirectionObject, GetDirectionObject, GetVector3D, ...
```

Пример вывода (`ksEndTypeEnum` из сигнатуры выше):

```python
# ksEndTypeEnum — .cache/kompas-stubs/constants3d.pyi:3649
# constants3d.constants.etBlind … etUpToNearSurface
ksEndTypeEnum: TypeAlias = Literal[0, 1, 2, 3, 4, 5, 6]
"""Типы операций выдавливания

0 — etBlind: строго на глубину
1 — etThroughAll: через всю деталь
2 — etUpToVertexTo: на расстояние до вершины
3 — etUpToVertexFrom: на расстояние за вершину
4 — etUpToSurfaceTo: на расстояние до поверхности
5 — etUpToSurfaceFrom: на расстояние за поверхность
6 — etUpToNearSurface: до ближайшей поверхности
"""
```

Модуль по умолчанию — `ksapi` (`IText.Assign` ≡ `ksapi.IText.Assign`); для `constants` / `constants3d` — полное имя, например `constants3d.constants.o3d_planeXOY`. Имена должны совпадать точно.


**Поиск и чтение справки SDK — `search`, `page`, `toc`, `links`**

```bash
uv run --script scripts/sdk.py search 'IExtrusions Add' --limit 3
uv run --script scripts/sdk.py page IExtrusions.Add ISketch.BeginEdit
uv run --script scripts/sdk.py toc ISketch
uv run --script scripts/sdk.py links ISketch.BeginEdit
```

- `search` — поиск по всем указанным словам или префиксам, без учёта регистра.
- `page` — текст страницы по символу, ID или полному ключу. Неоднозначный ID требует уточнения.
- `toc` — родительские и дочерние темы; без имени — корневые темы.
- `links` — ссылки с выбранной страницы.

По умолчанию используется раздел **KsAPI**. Для Windows API7/API5 или поиска по всем разделам явно указать `--section api7`, `--section api5` или `--section any`.


**Статическая проверка типов — `check`**

```bash
uv run --script scripts/sdk.py check /absolute/path/to/macro.py
```

`check` запускает `ty` с подготовленными стабами; отдельная настройка проекта не нужна. Сторонние импорты должны быть доступны в выбранном окружении; зависимости PEP 723 не устанавливаются. Успешная проверка не доказывает корректность геометрии или работоспособность API.

Для подсказок в редакторе использовать [расширение ty](https://docs.astral.sh/ty/editors/) и указать абсолютный путь к стабам в `environment.extra-paths` файла `ty.toml`.

**Поиск в нативном KsAPI — `local`, `constants`, `inspect`, `verify`**

```bash
uv run --script scripts/sdk.py local 'Bezier' --limit 15
uv run --script scripts/sdk.py constants 'плоскость XOY'
uv run --script scripts/sdk.py inspect IExtrusion --match 'side'
uv run --script scripts/sdk.py inspect ISketch.BeginEdit IExtrusion.SetSideParameters --source
uv run --script scripts/sdk.py verify --brief ISketch.BeginEdit IExtrusion.SetSideParameters
```

- `local` — поиск имён интерфейсов и методов; `constants` — поиск констант по имени или русскому комментарию.
- `inspect` — объявления нативного KsAPI. Для класса показаны сигнатуры, включая унаследованные; `--match` фильтрует методы по имени. Для метода `--source` добавляет тело: это позволяет уточнить преобразования массивов, нативных ссылок и выходных параметров.
- `verify` — только наличие перечисленных символов; `--brief` оставляет счётчики и отсутствующие имена. Корректность макроса и работоспособность API не проверяются.

В `inspect` поле `symbol` указывает фактический класс-владелец, `path`/`line`/`end_line` — расположение объявления. `constructed_interfaces` перечисляет конструкторы в теле, но не гарантирует тип результата; `returns_value` означает наличие `return` со значением, а не успешность операции. Сигнатуры включают `self`, который при вызове связанного метода не передаётся. `ksapi.IInterface(obj)` запрашивает другой интерфейс того же объекта, а не дочерний объект.

### Подготовка и запуск макроса

**Одноразовый макрос** должен быть самостоятельным: копировать нужные функции примера, не импортировать их из каталога скилла. Это правило относится к разовому скрипту под задачу, а не к библиотеке проекта, которую пользователь просит выделить или разложить по модулям.

Если задача — **реорганизовать CAD-код репозитория**, сначала ответить конкретной структурой, а не заготовкой макроса: слои вроде `helpers` → `parts` → `subassemblies` → `assembly`, плюс параметры и точки запуска; зависимости только сверху вниз. Перечислить существующие файлы и дать таблицу «текущий путь → целевой слой/файл» (что переименовать, объединить, оставить входом). Не предлагать модули без опоры на уже имеющийся код или явно названную потребность.

У функций указывать типы всех аргументов и возвращаемого значения; для объектов API использовать конкретные интерфейсы `ksapi`. Типизацию `validate` и габаритов (`Bounds`) можно опустить. В начале объявить только используемые зависимости:

```python
# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "scipy"]
# ///

import ksapi
import numpy as np
from scipy.optimize import root_scalar
```

Для простой геометрии достаточно `dependencies = []`. `numpy` — координаты и вращения; `scipy` — сплайны и численные решения; `shapely` — проверка плоских контуров; `cadquery-ocp` (импорт `OCP`) — независимый B-rep/STEP-контроль, только если нужен. `ksapi` и константы поставляются с КОМПАС, не устанавливать их из PyPI. Не писать условные импорты, не создавать проект/`.venv` и не запускать `pip install` ради одного макроса.

```bash
LD_LIBRARY_PATH="/opt/ascon/kompas3d-v25/Bin${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
PYTHONPATH="/opt/ascon/kompas3d-v25/Bin${PYTHONPATH:+:$PYTHONPATH}" \
uv run --script /absolute/path/to/main.py аргументы
```

`uv run --script main.py` и `uv run main.py` обрабатывают PEP 723, **`uv run python main.py` — нет**. Первый запуск новых пакетов может требовать сеть; следующие используют кэш. Необязательный `bash scripts/run.sh /absolute/path/to/main.py аргументы` задаёт то же окружение, сохраняет текущий каталог и не запускает КОМПАС. Это не песочница.

### Запуск и проверка результата

Команда запуска API-сервера не зависит от текущего каталога; пути `scripts/…` ниже указаны относительно каталога скилла. `scripts/run.sh` задаёт `LD_LIBRARY_PATH` и `PYTHONPATH` и запускает `uv run --script`, поэтому макрос напрямую импортирует `ksapi` и константы без правки `sys.path`, а зависимости берутся из PEP 723 в начале файла. Для другой установки заменить путь к `Bin` в команде сервера, а для `scripts/run.sh` задать `KOMPAS_BIN`. Принудительный выбор платформы Qt не требуется.

Сначала подключиться через `GetKompas()` к API-сессии пользователя. Если подключения нет, не запускать новый процесс: показать пользователю полную Bash-команду ниже (не наш `.sh`-файл) или предложить запуск агентом и дождаться явного согласия. Запрос на выполнение макроса не считается согласием на запуск КОМПАС.

```bash
# Команда для пользователя, если API-сессия ещё не запущена:
LD_LIBRARY_PATH="/opt/ascon/kompas3d-v25/Bin${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
LC_ALL="${LC_ALL:-C.UTF-8}" \
/opt/ascon/kompas3d-v25/Bin/kKompas -APIServer=10500
# При доступной API-сессии — запуск макроса в другом терминале:
bash scripts/run.sh /absolute/path/to/macro.py
```

`run.sh` не запускает КОМПАС самостоятельно. Макросы также должны использовать только `GetKompas()` и завершаться с понятной ошибкой при отсутствии подключения, без перехода к `OpenKompas()`. Не закрывать и не перезапускать процесс пользователя.

Перед исполнением:

1. Если есть ошибка, сомнение или существенный вызов вне рецепта, адресно проверить его сигнатуру, константы и ограничения. Не выполнять `inspect`/`verify` для каждого известного вызова перед пробой.
2. Проверить целевую API-сессию и документ. Создание нового документа не должно изменять чужую активную модель.

После исполнения кратко сообщить результат и существенные ограничения; отдельный протокол этапов нужен для диагностики или регрессии, не для каждого макроса. Проверять статус только у методов с соответствующим возвращаемым значением. Присутствие имени в нативном KsAPI не доказывает отсутствие ошибки в нативной реализации.
