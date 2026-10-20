# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Self-contained scratch demo: edit ONE existing extrusion, grouped Undo/Redo.

Attaches with GetKompas only; creates and closes its own unsaved part.
No user document/file is modified. No export, ClearUndo or disabled history.
The same feature is edited, not regenerated. This does NOT qualify assembly Undo.
Run: bash scripts/run.sh examples/incremental_edit.py
"""
from contextlib import contextmanager
import math
from time import perf_counter

import ksapi
from constants import constants as c
from constants3d import constants as c3d


def require(value, message):
    if not value:
        raise RuntimeError(message)
    return value


@contextmanager
def undo_group(doc3d):
    """Group only; closing on exception is NOT rollback. Reject nested groups."""
    require(doc3d.IsEnableUndo(), "Undo отключён; не менять пользовательскую настройку")
    require(not doc3d.IsUndoContainer(), "Уже открыта чужая группа Undo")
    doc3d.SetUndoContainer(True)  # Setter returns None.
    try:
        require(doc3d.IsUndoContainer(), "Группа Undo не открылась")
        yield
    finally:
        doc3d.SetUndoContainer(False)
        require(not doc3d.IsUndoContainer(), "Группа Undo не закрылась")


def history_command(app, doc, command):
    """Caller must know which completed edit is at history top; no blind retry."""
    require(command in (c.ksCMEditUndo, c.ksCMEditRedo), "Только Undo/Redo")
    require(not ksapi.IKompasDocument3D(doc).IsUndoContainer(), "Сначала закрыть группу")
    doc.SetActive()
    frame = require(doc.GetDocumentFrame(), "Окно целевого документа")
    active = app.GetActiveDocument()
    require(active and active.reference == doc.reference and doc.IsActive() and frame.IsActive(),
            "Целевой документ не активен; команда не выполнена")
    require(frame.IsKompasCommandEnable(command), "Команда недоступна")
    require(frame.ExecuteKompasCommand(command, False), "Ошибка Undo/Redo; не повторять вслепую")


def make_extrusion(doc):
    """Only for the newly registered scratch document; all dimensions in mm."""
    part = require(ksapi.IKompasDocument3D(doc).GetTopPart(), "Верхний компонент")
    model = require(part.GetModelContainer(), "Контейнер")
    sketch = require(model.GetSketchs().Add(), "Эскиз")
    sketch.SetPlane(require(part.GetDefaultObject(c3d.o3d_planeXOY), "XOY"))
    require(sketch.Update(), "Плоскость эскиза")
    fragment = require(sketch.BeginEdit(False), "BeginEdit")
    try:
        view = require(fragment.GetViewsAndLayersManager().GetViews().GetActiveView(), "Вид")
        drawing = require(ksapi.IDrawingContainer(view), "Контур")
        rect = require(drawing.GetRectangles().Add(), "Прямоугольник")
        rect.SetX(0.0)
        rect.SetY(0.0)
        rect.SetWidth(20.0)
        rect.SetHeight(10.0)
        require(rect.Update(), "Прямоугольник Update")
    finally:
        require(sketch.EndEdit(), "EndEdit")
    op = require(model.GetExtrusions().Add(c3d.o3d_bossExtrusion), "Выдавливание")
    op.SetProfiles([sketch])
    op.SetDirection(c3d.dtNormal)
    require(op.SetSideParameters(True, c3d.etBlind, 10.0, 0.0, False, None), "Глубина")
    require(op.Update(), "Первое построение")
    require(part.RebuildModel(True), "Перестроение")


def current_extrusion(doc):
    """Re-resolve after rebuild/Undo. Index 0 valid ONLY for this one-feature fixture."""
    part = require(ksapi.IKompasDocument3D(doc).GetTopPart(), "Свежий компонент")
    extrusions = part.GetModelContainer().GetExtrusions()
    require(extrusions.GetCount() == 1, "Пример ожидает ровно одно выдавливание")
    return require(extrusions.GetExtrusion(0), "Свежая операция")


def change_depth(doc, depth):
    require(math.isfinite(depth) and depth > 0, "Нужна положительная конечная глубина")
    op = current_extrusion(doc)
    require(op.GetExtrusionType(True) == c3d.etBlind, "Не blind-операция")
    op.SetDepth(True, depth)  # Does not replace profile, direction, draft or mode.
    require(op.Update(), "Неизвестный/неудачный исход правки; автоматической отмены нет")
    require(math.isclose(op.GetDepth(True), depth, abs_tol=1e-6), "Глубина не применилась")


def snapshot(doc):
    """Actual body + full error tree, not just parameter readback."""
    part = require(ksapi.IKompasDocument3D(doc).GetTopPart(), "Компонент для проверки")
    bodies = ksapi.IFeature(part).GetResultBodies()
    require(len(bodies) == 1 and bodies[0].IsSolid(), "Ожидалось одно твёрдое тело")
    bounds = bodies[0].GetGabarit(0., 0., 0., 0., 0., 0.)
    require(bounds[0] and all(math.isfinite(v) for v in bounds[1:]), "Габариты")
    seen = set()

    def visit(feature):
        if feature.reference in seen:
            return
        seen.add(feature.reference)
        require(feature.GetObjectError() == 0, f"Ошибка дерева: {feature.GetName()}")
        for child in feature.GetSubFeatures(c.ksOperTree, True, True):
            if child:
                visit(child)

    visit(ksapi.IFeature(part))
    return tuple(bounds[1:])


def check_height(doc, height):
    bounds = snapshot(doc)
    expected = (0., 0., 0., 20., 10., height)
    require(all(abs(a - b) <= 1e-6 for a, b in zip(bounds, expected)), f"Геометрия: {bounds}")
    return bounds


def main():
    app = require(ksapi.GetKompas(), "Нет API-сессии; запуск пользователем по SKILL.md")
    previous = app.GetActiveDocument()
    doc = None
    try:
        doc = require(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart, True), "Scratch")
        # Owned handle registered before the first document query/mutation.
        make_extrusion(doc)
        baseline = check_height(doc, 10.)
        started = perf_counter()
        with undo_group(ksapi.IKompasDocument3D(doc)):
            change_depth(doc, 15.)
            change_depth(doc, 20.)
        changed = check_height(doc, 20.)
        require(changed != baseline, "Нет подтверждённой правки; Undo запрещён")
        print(f"edit+check: {perf_counter() - started:.3f} s")
        # No intervening writer/UI/history commands. Both Updates and geometry confirmed.
        history_command(app, doc, c.ksCMEditUndo)
        require(check_height(doc, 10.) == baseline, "Undo не восстановил исходную геометрию")
        history_command(app, doc, c.ksCMEditRedo)
        require(check_height(doc, 20.) == changed, "Redo не восстановил правку")
        # Empty group: even if Undo is enabled, it could target PREVIOUS history.
        with undo_group(ksapi.IKompasDocument3D(doc)):
            pass
        check_height(doc, 20.)  # Deliberately do NOT issue Undo for an empty group.
        print("PASS: одна операция изменена; Undo/Redo проверены геометрически; файлы не записаны")
    finally:
        if doc:
            require(doc.Close(c.kdDoNotSaveChanges), "Закрытие собственного scratch")
        if previous:
            previous.SetActive()


if __name__ == "__main__":
    main()
