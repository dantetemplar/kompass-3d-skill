# kompass-3d-skill

Скилл для AI-агента: создание и изменение деталей, сборок и чертежей КОМПАС-3D через нативный Python KsAPI. Примеры адаптированы для КОМПАС-3D v25 в Linux; Windows COM и `pywin32` не используются.

Нужны установленный КОМПАС с действительной лицензией, Python 3.11+, `uv` и Bash. Подготовка справки дополнительно требует установленный SDK.

## Подключение скилла

Установка для Cursor:

```bash
npx skills add dantetemplar/kompass-3d-skill --skill kompass-3d-skill -g -a cursor
```

Для приватного репозитория необходимы доступ к нему и настроенная Git-аутентификация.

Для локальной разработки можно подключить каталог скилла из уже клонированного репозитория. Замените абсолютный путь в примере; ссылка создаётся только при отсутствии назначения, существующий каталог или ссылка не заменяются:

```bash
REPO=/absolute/path/to/kompass-3d-skill
mkdir -p ~/.cursor/skills
if [ ! -e ~/.cursor/skills/kompass-3d-skill ] && [ ! -L ~/.cursor/skills/kompass-3d-skill ]; then
    ln -s "$REPO/skills/kompass-3d-skill" ~/.cursor/skills/kompass-3d-skill
fi
```

Главная инструкция — [SKILL.md](skills/kompass-3d-skill/SKILL.md), готовые маршруты — [references/recipes.md](skills/kompass-3d-skill/references/recipes.md), примеры — [examples/](skills/kompass-3d-skill/examples/). Запрос агенту: «Используй kompass-3d-skill и создай деталь по подходящему рецепту».

Скилл автономен: для работы нужен только установленный каталог скилла, не исходный репозиторий. Команды ниже выполняются из `~/.cursor/skills/kompass-3d-skill`; при другой установке замените путь в `cd`.

## Подготовка SDK

Справка и стабы генерируются офлайн из установленного SDK, не импортируют `ksapi` и не запускают КОМПАС. Выполните из каталога установленного скилла:

```bash
cd ~/.cursor/skills/kompass-3d-skill
export LD_LIBRARY_PATH="/opt/ascon/kompas3d-v25/Bin${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PYTHONPATH="/opt/ascon/kompas3d-v25/Bin${PYTHONPATH:+:$PYTHONPATH}"
export UV_OFFLINE=1
export UV_PYTHON_DOWNLOADS=never
uv run --script scripts/prepare/prepare_docs.py
uv run --script scripts/prepare/prepare_stubs.py
```

Нужны подходящий локальный Python и установленный SDK; команды ничего не скачивают. `--help` описывает выбор установки и выходных каталогов. Справка сохраняется в `.cache/kompas-sdk-docs`, стабы — в `.cache/kompas-stubs` внутри скилла; кэши не включены в Git. При переносе подготовленного скилла копируйте `.cache` либо подготовьте SDK повторно. Для другого индекса используйте `KOMPAS_SDK_DOCS` или `scripts/sdk.py --docs /path/to/docs`.

```bash
cd ~/.cursor/skills/kompass-3d-skill
python3 scripts/sdk.py search 'IExtrusions Add'
python3 scripts/sdk.py page IExtrusions.Add ISketch.BeginEdit
python3 scripts/sdk.py inspect IExtrusion.SetSideParameters --source
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
./examples/macros/run.sh hello_box.py
./examples/macros/run.sh draw_rectangle.py
./examples/macros/run.sh touch_active.py ~/kompas-models/model.m3d
```

`touch_active.py` меняет документ без автоматического сохранения. Используйте копию модели. Галерея и статусы проверки операций описаны в [references/examples.md](skills/kompass-3d-skill/references/examples.md).

## Проверки без КОМПАС

Тесты разработки находятся вне скилла. Запускайте из корня репозитория:

```bash
cd /absolute/path/to/kompass-3d-skill
python3 -m unittest discover -s tests
```

Проверка подготовленных стабов и аудит артефактов выполняются из установленного скилла; для проверки стабов нужен локальный `mypy`:

```bash
cd ~/.cursor/skills/kompass-3d-skill
uv run --script scripts/prepare/check_stubs.py
uv run --script scripts/prepare/audit_artifacts.py
```

## Состав

- `skills/kompass-3d-skill/` — автономный переносимый скилл: `SKILL.md`, `references/`, `examples/`, `scripts/`.
- `skills/kompass-3d-skill/scripts/prepare/` — офлайн-подготовка справки и типизированных стабов.
- `skills/kompass-3d-skill/examples/macros/` — вводные макросы.
- `skills/kompass-3d-skill/.cache/` — локальные справка и стабы, не включены в Git.
- `tests/` — тесты разработки репозитория, не входят в устанавливаемый скилл.
- `INSIGHTS.md` — существующие заметки исследования итеративной работы с КОМПАС.
- `PracticeProblems_ALL250_CSWA/` — локальный учебный корпус, не включён в Git.

Скилл не зависит от патчей или изменённых библиотек лицензирования. Эти файлы и их Git-история в репозиторий не включены.

Справка извлекается из установленной официальной WebHelp SDK. Преобразование адаптировано из [dwnmf/kompas_3d_api](https://github.com/dwnmf/kompas_3d_api), подход к стабам исследован в [KompasAPI-stubs-generator](https://github.com/nikitamamay/KompasAPI-stubs-generator). КОМПАС-3D и SDK принадлежат АСКОН; проект неофициальный.
