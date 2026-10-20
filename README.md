# kompass-3d-skill

Скилл для AI-агента: создание и изменение деталей, сборок и чертежей КОМПАС-3D через нативный Python KsAPI. Примеры адаптированы для КОМПАС-3D v25 в Linux; Windows COM и `pywin32` не используются.

Нужны установленный КОМПАС с действительной лицензией, `uv` и Bash. Python 3.11+ может установить `uv`. Подготовка справки дополнительно требует установленный SDK.

## Подключение скилла

Установка для Cursor:

```bash
npx skills add dantetemplar/kompass-3d-skill --skill kompass-3d-skill -g -a cursor
```

Для приватного репозитория необходимы доступ к нему и настроенная Git-аутентификация.

Запрос агенту: «Используй kompass-3d-skill и создай деталь по подходящему рецепту».

## Подготовка SDK

Справка и стабы генерируются офлайн из файлов установленного КОМПАС и SDK. Генератор стабов анализирует исходный `ksapi.py`, не выполняя его и не запуская КОМПАС. Для офлайн-режима нужен заранее доступный Python 3.11+ — системный или установленный через `uv python install`. Выполните из каталога установленного скилла:

```bash
cd ~/.cursor/skills/kompass-3d-skill
export LD_LIBRARY_PATH="/opt/ascon/kompas3d-v25/Bin${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PYTHONPATH="/opt/ascon/kompas3d-v25/Bin${PYTHONPATH:+:$PYTHONPATH}"
export UV_OFFLINE=1
export UV_PYTHON_DOWNLOADS=never
uv run --script scripts/prepare/prepare_docs.py
uv run --script scripts/prepare/prepare_stubs.py
```

Команды подготовки ничего не скачивают. `--help` описывает выбор установки и выходных каталогов. Справка сохраняется в `.cache/kompas-sdk-docs`, стабы — в `.cache/kompas-stubs` внутри скилла; кэши не включены в Git. При переносе подготовленного скилла копируйте `.cache` либо подготовьте SDK повторно. Для другого индекса используйте `KOMPAS_SDK_DOCS` или `scripts/sdk.py --docs /path/to/docs`.

```bash
cd ~/.cursor/skills/kompass-3d-skill
uv run --script scripts/sdk.py search 'IExtrusions Add'
uv run --script scripts/sdk.py page IExtrusions.Add ISketch.BeginEdit
uv run --script scripts/sdk.py inspect IExtrusion.SetSideParameters --source
```

По умолчанию используется нативный KsAPI; Windows API7/API5 доступны только при явном `--section`. Подробности — в [references/ksapi.md](skills/kompass-3d-skill/references/ksapi.md).

## Запуск макросов

Запустите отдельную API-сессию КОМПАС:

```bash
LD_LIBRARY_PATH="/opt/ascon/kompas3d-v25/Bin${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
LC_ALL="${LC_ALL:-C.UTF-8}" \
/opt/ascon/kompas3d-v25/Bin/kKompas -APIServer=10500
```

В другом терминале:

```bash
cd ~/.cursor/skills/kompass-3d-skill
./scripts/run.sh /absolute/path/to/macro.py
```

Обычный запуск из меню не создаёт API-сессию. Макросы подключаются через `ksapi.GetKompas()`; автоматически КОМПАС не запускают. Произвольные зависимости задаются в самом макросе через PEP 723 и устанавливаются `uv`; `ksapi` берётся из установленного КОМПАС, не из PyPI.

Учебные макросы находятся в [examples/macros/](skills/kompass-3d-skill/examples/macros/):

```bash
cd ~/.cursor/skills/kompass-3d-skill
./scripts/run.sh examples/macros/hello_box.py
./scripts/run.sh examples/macros/draw_rectangle.py
./scripts/run.sh examples/macros/touch_active.py ~/kompas-models/model.m3d
```

`touch_active.py` меняет документ без автоматического сохранения. Используйте копию модели. Галерея и статусы проверки операций описаны в [references/examples.md](skills/kompass-3d-skill/references/examples.md).

## Проверки без КОМПАС

Тесты разработки находятся вне скилла. Запускайте из корня репозитория:

```bash
cd /absolute/path/to/kompass-3d-skill
uv run --no-project --python '>=3.11' python -m unittest discover -s tests
```

Проверка подготовленных стабов и аудит артефактов выполняются из установленного скилла; для проверки стабов нужен локальный `mypy`:

```bash
cd ~/.cursor/skills/kompass-3d-skill
uv run --script scripts/prepare/check_stubs.py
uv run --script scripts/prepare/audit_artifacts.py
```

## Проверка галереи в КОМПАС

Инструмент разработки [tools/run_examples.py](tools/run_examples.py) не входит в устанавливаемый скилл. При уже работающей API-сессии выполните из корня репозитория:

```bash
bash skills/kompass-3d-skill/scripts/run.sh tools/run_examples.py --output-dir /tmp/kompas-examples-check

# Только выбранные примеры; каталог результатов должен быть новым.
bash skills/kompass-3d-skill/scripts/run.sh tools/run_examples.py --only 02_ring 03_holes --output-dir /tmp/kompas-holes-check
```

Стенд строит примеры, проверяет геометрию, сохраняет и повторно открывает временные модели, получает JPEG через КОМПАС. В новом каталоге остаются изображения и `verification.json`; временные модели удаляются, чужие документы не меняются. Зависимость `pillow` устанавливается через `uv` из PEP 723 скрипта; первая установка может требовать сеть.

## Состав

- `skills/kompass-3d-skill/` — автономный переносимый скилл: `SKILL.md`, `references/`, `examples/`, `scripts/`.
- `skills/kompass-3d-skill/scripts/prepare/` — офлайн-подготовка справки и типизированных стабов.
- `skills/kompass-3d-skill/examples/macros/` — вводные макросы.
- `skills/kompass-3d-skill/.cache/` — локальные справка и стабы, не включены в Git.
- `tests/` — тесты разработки репозитория, не входят в устанавливаемый скилл.
- `tools/` — инструменты разработки: регрессия галереи и генерация JPEG.
- `INSIGHTS.md` — существующие заметки исследования итеративной работы с КОМПАС.
- `PracticeProblems_ALL250_CSWA/` — локальный учебный корпус, не включён в Git.

Скилл не зависит от патчей или изменённых библиотек лицензирования. Эти файлы и их Git-история в репозиторий не включены.

Справка извлекается из установленной официальной WebHelp SDK. Преобразование адаптировано из [dwnmf/kompas_3d_api](https://github.com/dwnmf/kompas_3d_api), подход к стабам исследован в [KompasAPI-stubs-generator](https://github.com/nikitamamay/KompasAPI-stubs-generator). КОМПАС-3D и SDK принадлежат АСКОН; проект неофициальный.
