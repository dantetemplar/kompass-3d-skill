# kompass-3d-skill

Скилл для AI-агента: создание и изменение деталей, сборок и чертежей КОМПАС-3D через нативный Python KsAPI. Примеры адаптированы для КОМПАС-3D v25 в Linux; Windows COM и `pywin32` не используются.

Нужны установленный КОМПАС с действительной лицензией, Python 3.11+, `uv` и Bash. Подготовка справки дополнительно требует установленный SDK.

## Подключение скилла

Клонируйте репозиторий в каталог скиллов вашего агента, например для Cursor:

```bash
git clone https://github.com/dantetemplar/kompass-3d-skill.git ~/.cursor/skills/kompass-3d-skill
cd ~/.cursor/skills/kompass-3d-skill
```

Главная инструкция — [SKILL.md](SKILL.md), готовые маршруты — [references/recipes.md](references/recipes.md), примеры — [examples/](examples/). Запрос агенту: «Используй kompass-3d-skill и создай деталь по подходящему рецепту».

## Подготовка SDK

Справка и стабы генерируются офлайн из установленного SDK, не импортируют `ksapi` и не запускают КОМПАС. Выполните из корня репозитория:

```bash
export LD_LIBRARY_PATH="/opt/ascon/kompas3d-v25/Bin${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PYTHONPATH="/opt/ascon/kompas3d-v25/Bin${PYTHONPATH:+:$PYTHONPATH}"
export UV_OFFLINE=1
export UV_PYTHON_DOWNLOADS=never
uv run --script prepare/prepare_docs.py
uv run --script prepare/prepare_stubs.py
```

Нужны подходящий локальный Python и установленный SDK; команды ничего не скачивают. `--help` описывает выбор установки и выходных каталогов. Справка сохраняется в `.cache/kompas-sdk-docs`, стабы — в `.cache/kompas-stubs`; кэши не включены в Git. При переносе подготовленного скилла копируйте `.cache` либо подготовьте SDK повторно. Для другого индекса используйте `KOMPAS_SDK_DOCS` или `scripts/sdk.py --docs /path/to/docs`.

```bash
python3 scripts/sdk.py search 'IExtrusions Add'
python3 scripts/sdk.py page IExtrusions.Add ISketch.BeginEdit
python3 scripts/sdk.py inspect IExtrusion.SetSideParameters --source
```

По умолчанию используется нативный KsAPI; Windows API7/API5 доступны только при явном `--section`. Подробности — в [references/ksapi.md](references/ksapi.md).

## Запуск макросов

Запустите отдельную API-сессию КОМПАС:

```bash
LD_LIBRARY_PATH="/opt/ascon/kompas3d-v25/Bin${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
LC_ALL="${LC_ALL:-C.UTF-8}" \
/opt/ascon/kompas3d-v25/Bin/kKompas -APIServer=10500
```

В другом терминале:

```bash
./scripts/run.sh /absolute/path/to/macro.py
```

Обычный запуск из меню не создаёт API-сессию. Макросы подключаются через `ksapi.GetKompas()`; автоматически КОМПАС не запускают. Произвольные зависимости задаются в самом макросе через PEP 723 и устанавливаются `uv`; `ksapi` берётся из установленного КОМПАС, не из PyPI.

Учебные макросы находятся в [macros/](macros/):

```bash
./macros/run.sh hello_box.py
./macros/run.sh draw_rectangle.py
./macros/run.sh touch_active.py ~/kompas-models/model.m3d
```

`touch_active.py` меняет документ без автоматического сохранения. Используйте копию модели. Галерея и статусы проверки операций описаны в [references/examples.md](references/examples.md).

## Проверки без КОМПАС

```bash
python3 -m unittest discover -s prepare
python3 -m unittest discover -s scripts
python3 -m unittest discover -s macros
```

Проверка подготовленных стабов: `uv run --script prepare/check_stubs.py` (нужен локальный `mypy`); аудит артефактов: `uv run --script prepare/audit_artifacts.py`.

## Состав

- `SKILL.md`, `references/`, `examples/`, `scripts/` — переносимый скилл и инструменты SDK.
- `prepare/` — офлайн-подготовка справки и типизированных стабов.
- `macros/` — вводные макросы и проверки.
- `INSIGHTS.md` — существующие заметки исследования итеративной работы с КОМПАС.
- `PracticeProblems_ALL250_CSWA/` — локальный учебный корпус, не включён в Git.

Скилл не зависит от патчей или изменённых библиотек лицензирования. Эти файлы и их Git-история в репозиторий не включены.

Справка извлекается из установленной официальной WebHelp SDK. Преобразование адаптировано из [dwnmf/kompas_3d_api](https://github.com/dwnmf/kompas_3d_api), подход к стабам исследован в [KompasAPI-stubs-generator](https://github.com/nikitamamay/KompasAPI-stubs-generator). КОМПАС-3D и SDK принадлежат АСКОН; проект неофициальный.
