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

По умолчанию используется нативный KsAPI; Windows API7/API5 доступны только при явном `--section`. Подробности — в [справочнике KsAPI](skills/kompass-3d-skill/SKILL.md#справочник-рабочего-процесса-с-нативным-ksapi).

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

Тестовые макросы находятся в корневом [macros/](macros/) и не входят в устанавливаемый скилл. Запускайте из корня репозитория:

```bash
cd /absolute/path/to/kompass-3d-skill
bash skills/kompass-3d-skill/scripts/run.sh macros/hello_box.py
bash skills/kompass-3d-skill/scripts/run.sh macros/draw_rectangle.py
bash skills/kompass-3d-skill/scripts/run.sh macros/touch_active.py ~/kompas-models/model.m3d
```

`touch_active.py` меняет документ без автоматического сохранения. Используйте копию модели. Документация разработки, галерея и статусы проверки операций описаны в [examples.md](examples.md).

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

Источник учебных заданий, чертежей, превью и исходных компонентов — [официальный каталог SOLIDWORKS Practice Problems](https://www.solidworks.com/solution/education/practice-problems). Материалы принадлежат Dassault Systèmes; условия использования приведены в оригиналах.

## Источники и подробности

Справочные ссылки ниже не являются списком обязательного чтения.

- [Рецепты](skills/kompass-3d-skill/SKILL.md#рецепты-для-компас-3d-на-python) и [01_plate.py](skills/kompass-3d-skill/examples/01_plate.py) — готовые реализации для адаптации и уточнения деталей.
- [Справочник рабочего процесса с нативным KsAPI](skills/kompass-3d-skill/SKILL.md#справочник-рабочего-процесса-с-нативным-ksapi) — подробности при диагностике.
- [Официальный SDK](https://help.ascon.ru/KOMPAS_SDK/25/ru-RU/) — назначение и ограничения операций.
- Локальные `ksapi.py`, `constants.py`, `constants3d.py` — фактические имена, сигнатуры и маршалинг; импорт ради этих данных не нужен.

### Внешние проекты и интеграции

Это источники идей, адресных примеров и необязательные дополнения, не обязательные зависимости.

#### Дополнительные скиллы

- [earthtojake/text-to-cad](https://github.com/earthtojake/text-to-cad): `cad` — постановка задачи и проверка геометрии; `dfm` — технологичность; `dfam-check` — проверки для аддитивного производства; `step-parts` — поиск стандартных и покупных деталей; `engineering-drawing` — оформление чертежей. Установка описана в [upstream README](https://github.com/earthtojake/text-to-cad#install). Инженерные рекомендации можно использовать для отдельных задач, а создание и изменение `.m3d`/`.a3d`, API-сессию, сохранение и изображения выполнять через нативный KsAPI. Маршрут `cadgen/build123d → STEP` не заменяет нативное дерево КОМПАС; STEP-детали остаются импортированными компонентами. Ссылка не устанавливает скиллы и не запускает MCP-серверы, viewer или оборудование.
- [kompas-guard-sdk](https://github.com/dwnmf/kompas-3d-guard-bin/blob/master/.agents/skills/kompas-guard-sdk/SKILL.md) — дополнительный источник подходов к работе с SDK КОМПАС.

#### Реализации и примеры

- [IsWaFF/kompas3d-skill](https://github.com/IsWaFF/kompas3d-skill), MIT: нативный `ksapi`, в основном 2D. Полезны примеры размеров, дуг, заливок, поиска наложений и selftest; тонкости направления дуг и экспорта проверять на своей установке. Его distrobox/Xephyr-схему запуска сюда не переносить.
- [kostia-egik/geomwright](https://github.com/kostia-egik/geomwright), MIT: Windows COM, не нативный KsAPI. Полезны [CAD-инварианты](https://github.com/kostia-egik/geomwright/blob/main/CAD_PATTERNS.md): разделение расчёта и построения, чтение конечной геометрии независимо от истории и остановка после неизвестного исхода вызова. Сложные инженерные семейства и проверки сохранения не добавлять в простую задачу без необходимости.
- [SergeySklyarov/Kompas3D-MCP](https://github.com/SergeySklyarov/Kompas3D-MCP): Windows COM/.NET. Полезно различение «вызов вернулся», «геометрия проверена», «сохранение/повторное открытие проверены» и явное перечисление непроверенного. После изменения топологии заново выбирать грани/рёбра; после обрыва соединения не повторять запись до проверки состояния. Его механизм автозапуска/перезапуска не переносить.
- [hymaxo/kompas3d-mcp](https://github.com/hymaxo/kompas3d-mcp), MIT: Windows COM/API5/API7. Полезна [коллекция рецептов](https://github.com/hymaxo/kompas3d-mcp/blob/main/skills/kompas-modeling/references/recipes.md) с входными размерами, ожидаемыми габаритами, числом тел и аналитическим объёмом. Использовать её как источник геометрии и критериев результата, а вызовы адаптировать по нативной обёртке. Объём проверять, когда он нужен для подтверждения внутренней операции, не как обязательный этап каждой задачи.
- [xomyachok-shaolin/kompas-3d-mcp-linux](https://github.com/xomyachok-shaolin/kompas-3d-mcp-linux): нативный C++ KsAPI v24 в Linux. [bridge.cpp](https://github.com/xomyachok-shaolin/kompas-3d-mcp-linux/blob/main/src/bridge.cpp) полезен для поиска цепочек 2D-размеров, штампа и экспорта. Явная лицензия на повторное использование не установлена: код не копировать; его запуск, IPC и threading-схему не переносить.
- [nikitamamay/KompasAPI-01](https://github.com/nikitamamay/KompasAPI-01), MIT: Windows COM-обёртка со stubs и встроенной документацией. Полезны типы и иерархия для поиска понятий, но это не stubs нативного KsAPI и не источник его фактических сигнатур. Не возвращать LSP и COM-зависимости ради этой базы.

Код этих проектов в скилл не скопирован. Даже MIT-код перед переносом требует сохранения уведомлений о лицензии и проверки применимости к нативному API; документация SDK может иметь отдельные права.

#### Подготовка справки и стабов

- [dwnmf/kompas_3d_api](https://github.com/dwnmf/kompas_3d_api) — исходный конвертер WebHelp, из которого адаптировано преобразование справки. Наш корпус собирается из локального официального SDK; права на документацию принадлежат её правообладателям.
- [nikitamamay/KompasAPI-stubs-generator](https://github.com/nikitamamay/KompasAPI-stubs-generator) — источник исследования подхода к генерации стабов.

## Состав

- `skills/kompass-3d-skill/` — автономный переносимый скилл: `SKILL.md` со справочником и рецептами, `examples/`, `scripts/`.
- `skills/kompass-3d-skill/scripts/prepare/` — офлайн-подготовка справки и типизированных стабов.
- `macros/` — тестовые макросы разработки, не входят в устанавливаемый скилл.
- `examples.md` — документация разработки: запуск примеров, проверки и измерения.
- `skills/kompass-3d-skill/.cache/` — локальные справка и стабы, не включены в Git.
- `tests/` — тесты разработки репозитория, не входят в устанавливаемый скилл.
- `tools/` — инструменты разработки: регрессия галереи и генерация JPEG.
- `INSIGHTS.md` — существующие заметки исследования итеративной работы с КОМПАС.
- `PracticeProblems_ALL250_CSWA/` — 364 задания уровней 01–18 в Markdown, JPG-чертежах и локальных JPG-превью результата и 32 ZIP с исходными компонентами, хранятся в Git LFS и не входят в устанавливаемый скилл. Имя каталога сохранено. Markdown содержит ссылки на компоненты, связанные листы и предыдущие задания, а также примечания к известным ошибкам оригиналов. Отдельные PDF остаются локально и игнорируются Git; исходные ZIP могут содержать PDF условий.
- `tools/download_practice_previews.py` — загрузка официальных превью SOLIDWORKS в `*_preview.jpg` и вставка локального превью перед чертежом. Изображения хранятся в Git LFS; просмотр заданий не требует обращения к сайту. Запуск: `uv run --script tools/download_practice_previews.py`.
- `tools/import_practice_archive.py` — импорт внешнего корпуса, включая PDF из вложенных ZIP; `tools/extract_pdf.py` — преобразование в Markdown и JPG с сохранением ссылки на локальное превью. В архиве `PracticeProblems_ALL.zip` всего 365 условий; `11.8` защищено паролем и не преобразовано. Для воспроизводимой генерации уровня 11: `uv run --script tools/extract_pdf.py PracticeProblems_ALL250_CSWA/Level11_HoleWizard --overwrite --exclude PracticeProblems_11_8_ENG.pdf`.

Скилл не зависит от патчей или изменённых библиотек лицензирования. Эти файлы и их Git-история в репозиторий не включены.

Справка извлекается из установленной официальной WebHelp SDK. КОМПАС-3D и SDK принадлежат АСКОН; проект неофициальный.
