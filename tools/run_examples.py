# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow"]
# ///
"""Последовательно проверить примеры в КОМПАС и получить JPEG для каталога.

Из корня репозитория:
bash skills/kompass-3d-skill/scripts/run.sh tools/run_examples.py --output-dir /новый/каталог
Нужна существующая API-сессия. Чужие документы не редактируются и не закрываются.
Модели временные; на диске остаются только JPEG и verification.json.
"""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

import ksapi
from constants import constants as c
from constants3d import constants as c3d
from PIL import Image

EXAMPLES = Path(__file__).resolve().parents[1] / "skills" / "kompass-3d-skill" / "examples"
PARTS = ["01_plate", "02_ring", "03_holes", "04_revolve", "05_offset_plane",
         "06_loft", "07_body_pattern", "08_boolean", "09_reposition",
         "11_fillet_edit", "12_chamfer", "13_native_hole", "14_shell", "15_linear_pattern"]


def require(value, message):
    if not value:
        raise RuntimeError(message)
    return value


def load_example(name):
    spec = importlib.util.spec_from_file_location(name, EXAMPLES / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def document_ids(app):
    documents = app.GetDocuments()
    return [documents.GetItem(i).reference for i in range(1, documents.GetCount() + 1)]


def capture(doc, target):
    """Штатный JPEG в новый путь; существующие файлы и ссылки не заменяются."""
    target = Path(target).expanduser().absolute()
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"Не перезаписываем JPEG: {target}")
    target = target.resolve()
    doc.SetActive()
    doc3d = ksapi.IKompasDocument3D(doc)
    manager = doc3d.GetViewProjectionManager()
    projections = [manager.GetViewProjection(i) for i in range(manager.GetCount())]
    isometric = [v for v in projections if v and v.GetViewProjectonType() == c3d.ksVPIsometric]
    require(len(isometric) == 1, "Не найдена стандартная изометрия")
    isometric[0].SetCurrent(True)
    require(isometric[0].IsCurrent(), "Изометрия не стала текущей")
    frame = require(doc.GetDocumentFrame(), "Окно")
    for command in (c.ksCMShadedWireframeMode, c.ksCMZoomEntireDocument):
        require(frame.IsKompasCommandEnable(command), f"Недоступна команда вида {command}")
        require(frame.ExecuteKompasCommand(command, False), f"Вид {command}")
    parameters = ksapi.IRasterConvertParameters(doc.GetInterface(c.ksObjectRasterConvertParameters))
    require(parameters.Clear(), "Параметры JPEG")
    parameters.SetRasterFormat(c.ksRasterFormatJPG)
    parameters.SetColorBPP(24)
    scale = parameters.CalcRasterScale(doc, 640, 480)
    require(math.isfinite(scale) and scale > 0, "Масштаб JPEG")
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"Путь JPEG занят во время подготовки: {target}")
    require(doc.SaveAsToRasterFormat(str(target), parameters), "Экспорт JPEG из КОМПАС")
    require(target.is_file() and target.stat().st_size > 0, "Нет JPEG")
    with Image.open(target) as image:
        require(image.format == "JPEG", "Неверный формат изображения")
        size = image.size
        extrema = image.convert("RGB").getextrema()
        require(any(hi - lo > 20 for lo, hi in extrema), "Пустое изображение")
        image.verify()
    return {"file": target.name, "pixels": list(size), "source": "KOMPAS SaveAsToRasterFormat"}


def verified_volume(part):
    """Расчёт геометрического объёма в мм³, не масса/плотность и не число из параметров."""
    inertia = require(ksapi.IMassInertiaParam(part), "МЦХ детали")
    inertia.SetLengthUnits(c.ksLUnMM)
    require(inertia.GetLengthUnits() == c.ksLUnMM, "Фактические единицы МЦХ не мм")
    require(inertia.Calculate(), "Расчёт объёма")
    value = inertia.GetVolume()
    require(math.isfinite(value) and value > 0, "Недостоверный объём")
    return value


def verify_part(app, name, directory, output):
    example = load_example(name)
    path = directory / f"{name}.m3d"
    doc = None
    try:
        doc = require(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart, True), "Деталь")
        part = ksapi.IKompasDocument3D(doc).GetTopPart()
        example.build(part, part.GetModelContainer())
        before = example.validate(part)
        volume_before = verified_volume(part) if name.startswith(("11_", "12_", "13_", "14_", "15_")) else None
        require(doc.SaveAs(str(path)), "Сохранение")
        require(path.is_file() and path.stat().st_size > 0, "Нет сохранённой модели")
        require(doc.Close(c.kdDoNotSaveChanges), "Закрытие перед проверкой открытия")
        doc = None
        doc = require(app.GetDocuments().Open(str(path), True, False), "Повторное открытие")
        part = ksapi.IKompasDocument3D(doc).GetTopPart()
        after = example.validate(part)
        require(len(before) == len(after) and all(abs(a - b) <= 1e-5 for a, b in zip(before, after)),
                "Габариты изменились после открытия")
        result = {"example": f"examples/{name}.py", "status": "passed", "save_reopen": True,
                  "bounds": after}
        if volume_before is not None:
            volume_after = verified_volume(part)
            require(math.isclose(volume_before, volume_after, rel_tol=1e-9, abs_tol=1e-5),
                    "Объём изменился после открытия")
            result["volume_mm3"] = volume_after
        result["image"] = capture(doc, output / f"{name}.jpg")
        return result
    finally:
        if doc:
            require(doc.Close(c.kdDoNotSaveChanges), "Закрытие своего документа")


def assembly_state(doc):
    parts = ksapi.IKompasDocument3D(doc).GetTopPart().GetParts()
    return [{"source": parts.GetPart(i).GetFileName(), "fixed": parts.GetPart(i).IsFixed(),
             "matrix": list(parts.GetPart(i).GetPlacement().GetMatrix3D())}
            for i in range(parts.GetCount())]


def verify_assembly(app, directory, output):
    example = load_example("10_assembly")
    with example.assembly(app, directory) as doc:
        example.validate(doc)
        before = assembly_state(doc)
        path = directory / "assembly.a3d"
        require(doc.SaveAs(str(path)), "Сохранение сборки")
    doc = None
    try:
        doc = require(app.GetDocuments().Open(str(path), True, False), "Повторное открытие сборки")
        example.validate(doc)
        after = assembly_state(doc)
        require(before == after, "Размещения изменились после открытия")
        image = capture(doc, output / "10_assembly.jpg")
        return {"example": "examples/10_assembly.py", "status": "passed", "save_reopen": True,
                "state": after, "image": image}
    finally:
        if doc:
            require(doc.Close(c.kdDoNotSaveChanges), "Закрытие своей сборки")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--only", choices=PARTS + ["10_assembly"], nargs="+")
    args = parser.parse_args()
    output = args.output_dir.expanduser().resolve()
    require(not output.exists(), "Каталог результатов должен быть новым")
    app = require(ksapi.GetKompas(), "Нет API-сессии; КОМПАС не запускается автоматически")
    previous = app.GetActiveDocument()
    initial = document_ids(app)
    output.mkdir(parents=True)
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "platform": "Linux",
              "kompas_version": app.GetApplicationName(True), "examples": []}
    report_path = output / "verification.json"
    try:
        for name in args.only or PARTS + ["10_assembly"]:
            print(f"START {name}", flush=True)
            started = perf_counter()
            with TemporaryDirectory(prefix="kompas-example-") as temporary:
                directory = Path(temporary)
                result = (verify_assembly(app, directory, output) if name == "10_assembly"
                          else verify_part(app, name, directory, output))
            result["seconds"] = round(perf_counter() - started, 3)
            report["examples"].append(result)
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            print(f"PASS {name}: {result['seconds']} s", flush=True)
    finally:
        if previous:
            previous.SetActive()
        require(document_ids(app) == initial, "Изменился набор открытых документов")
    print(f"PASS: {len(report['examples'])} examples; {report_path}", flush=True)


if __name__ == "__main__":
    main()
