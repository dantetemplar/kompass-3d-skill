#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Первый макрос: подключиться к КОМПАС и показать сообщение.

Запуск (API-сессия уже запущена пользователем):
  cd macros
  ./run.sh hello_box.py
"""

from __future__ import annotations

import sys
from pathlib import Path

BIN = Path("/opt/ascon/kompas3d-v25/Bin")
sys.path.insert(0, str(BIN))

import ksapi  # noqa: E402
from constants import constants as c  # noqa: E402


def connect():
    app = ksapi.GetKompas()
    if not app:
        command = (
            f'LD_LIBRARY_PATH="{BIN}${{LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}}" '
            'LC_ALL="${LC_ALL:-C.UTF-8}" '
            f'"{BIN}/kKompas" -APIServer=10500'
        )
        raise RuntimeError(
            f"API-сессия КОМПАС недоступна. Запустите в отдельном терминале:\n{command}"
        )
    return app


def main() -> int:
    app = connect()
    name = app.GetApplicationName(True)
    print(f"OK: {name}")

    app.ShowMessageBox(
        "Привет из Python-макроса (KsAPI)!",
        "hello_box",
        0,  # тип диалога
        1,  # OK
        True,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
