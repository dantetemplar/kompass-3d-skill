# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Two external occurrences of one self-generated 20 x 10 x 5 mm block.

Attach to an existing API session only. Default: temporary files and owned docs.
--output-dir NEW_DIRECTORY keeps block.m3d AND assembly.a3d together; neither
an existing directory nor an existing file is overwritten. Do not move only the
assembly: its external source must remain available. No mates or Undo commands.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
import argparse
import math
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TypeVar

import ksapi
from constants import constants as c
from constants3d import constants as c3d


IDENTITY = (1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.)
TRANSLATED = (*IDENTITY[:12], 30., 0., 0., 1.)


T = TypeVar("T")
Bounds = tuple[float, float, float, float, float, float]


def require(value: T | None, message: str) -> T:
    if not value:
        raise RuntimeError(message)
    return value


def close_owned(owned: list[ksapi.IKompasDocument]) -> None:
    while owned:
        doc = owned[-1]
        require(doc.Close(c.kdDoNotSaveChanges), "Close owned document")
        owned.pop()


def save_new(doc: ksapi.IKompasDocument, path: Path) -> None:
    if path.exists():
        raise FileExistsError(path)
    require(doc.SaveAs(str(path)), f"Save {path.name}")
    require(path.is_file() and path.stat().st_size > 0, f"Missing/empty file: {path}")


def check_tree(part: ksapi.IPart) -> None:
    seen = set()

    def visit(feature: ksapi.IFeature) -> None:
        if feature.reference in seen:
            return
        seen.add(feature.reference)
        require(feature.GetObjectError() == 0, f"Tree error: {feature.GetName()}")
        for child in feature.GetSubFeatures(c.ksOperTree, True, True):
            if child:
                visit(child)

    visit(ksapi.IFeature(part))


def check_block(part: ksapi.IPart) -> Bounds:
    bodies = ksapi.IFeature(part).GetResultBodies()
    require(len(bodies) == 1 and bodies[0].IsSolid(), "Expected one solid block")
    bounds = bodies[0].GetGabarit(0., 0., 0., 0., 0., 0.)
    require(len(bounds) == 7 and bounds[0], "Block bounds unavailable")
    require(all(math.isfinite(v) for v in bounds[1:]), "Non-finite bounds")
    dimensions = tuple(bounds[i + 4] - bounds[i + 1] for i in range(3))
    require(all(abs(a - b) < 1e-6 for a, b in zip(dimensions, (20., 10., 5.))),
            f"Unexpected block dimensions: {dimensions}")
    check_tree(part)
    return tuple(bounds[1:])


def make_block(doc: ksapi.IKompasDocument) -> None:
    part = require(ksapi.IKompasDocument3D(doc).GetTopPart(), "Source top part")
    model = require(part.GetModelContainer(), "Source model")
    sketch = require(model.GetSketchs().Add(), "Sketch")
    sketch.SetPlane(require(part.GetDefaultObject(c3d.o3d_planeXOY), "XOY plane"))
    require(sketch.Update(), "Sketch plane")
    fragment = require(sketch.BeginEdit(False), "Begin sketch")
    try:
        view = require(fragment.GetViewsAndLayersManager().GetViews().GetActiveView(), "View")
        drawing = require(ksapi.IDrawingContainer(view), "Sketch geometry")
        rectangle = require(drawing.GetRectangles().Add(), "Rectangle")
        rectangle.SetX(0.)
        rectangle.SetY(0.)
        rectangle.SetWidth(20.)
        rectangle.SetHeight(10.)
        require(rectangle.Update(), "Rectangle update")
    finally:
        require(sketch.EndEdit(), "End sketch")
    extrusion = require(model.GetExtrusions().Add(c3d.o3d_bossExtrusion), "Extrusion")
    extrusion.SetProfiles([sketch])
    extrusion.SetDirection(c3d.dtNormal)
    require(extrusion.SetSideParameters(True, c3d.etBlind, 5., 0., False, None), "Depth")
    require(extrusion.Update(), "Extrude block")
    require(part.RebuildModel(True), "Rebuild block")
    bounds = check_block(part)
    require(all(abs(a - b) < 1e-6 for a, b in zip(bounds, (0., 0., 0., 20., 10., 5.))),
            f"Source bounds: {bounds}")


def validate(doc: ksapi.IKompasDocument, source_path: str | Path | None = None) -> None:
    """Read fresh occurrences; optionally require their exact expected source path."""
    top = require(ksapi.IKompasDocument3D(doc).GetTopPart(), "Assembly top part")
    require(top.RebuildModel(True), "Rebuild assembly before verification")
    parts = top.GetParts()
    require(parts.GetCount() == 2, "Expected exactly two occurrences")
    expected_source = Path(source_path).resolve(strict=True) if source_path else None
    for index, expected in enumerate((IDENTITY, TRANSLATED)):
        component = require(parts.GetPart(index), f"Occurrence {index}")
        source = Path(require(component.GetFileName(), "External source path")).resolve(strict=True)
        require(source.is_file() and source.suffix.lower() == ".m3d", "Source is not a part")
        if expected_source is None:
            expected_source = source
        require(source == expected_source, "Occurrences must refer to the same source block")
        require(component.IsFixed() == (index == 0), f"Grounding readback: {index}")
        matrix = tuple(component.GetPlacement().GetMatrix3D())
        require(len(matrix) == 16 and all(math.isfinite(v) for v in matrix), "Placement matrix")
        require(all(abs(a - b) < 1e-6 for a, b in zip(matrix, expected)),
                f"All 16 placement entries must match: {index}: {matrix}")
        # Bounds verify solid size; the complete matrix verifies its world placement.
        check_block(component)
    check_tree(top)


@contextmanager
def assembly(app: ksapi.IApplication, directory: str | Path) -> Iterator[ksapi.IKompasDocument]:
    """Yield an owned assembly; caller keeps directory alive until after this exits.

    directory must exist. Source closes BEFORE insertion; assembly closes BEFORE
    the caller can remove its files. No user document is registered or closed.
    """
    directory = Path(directory).expanduser().resolve(strict=True)
    require(directory.is_dir(), "Expected an existing scratch/output directory")
    source_path = directory / "block.m3d"
    if source_path.exists() or (directory / "assembly.a3d").exists():
        raise FileExistsError("Refusing to overwrite block.m3d or assembly.a3d")
    owned = []
    try:
        source = require(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart, True),
                         "New source part")
        owned.append(source)  # Register immediately, before any document query/mutation.
        make_block(source)
        save_new(source, source_path)
        check_block(ksapi.IKompasDocument3D(source).GetTopPart())
        close_owned(owned)  # External source is saved and closed before assembly creation.
        doc = require(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentAssembly, True),
                      "New assembly")
        owned.append(doc)
        top = require(ksapi.IKompasDocument3D(doc).GetTopPart(), "Assembly top part")
        parts = require(top.GetParts(), "Occurrences")
        fixed = require(parts.AddFromFile(str(source_path), True, True), "First occurrence")
        fixed.SetFixed(True)  # Setter returns None; validate reads IsFixed().
        free = require(parts.AddFromFile(str(source_path), True, True), "Second occurrence")
        free.SetFixed(False)
        require(free.GetPlacement().SetOrigin(30., 0., 0.), "Translate free occurrence")
        free.UpdatePlacement(True)  # May return False despite a successful placement.
        require(top.RebuildModel(True), "Rebuild after placement")
        validate(doc, source_path)
        yield doc
    finally:
        close_owned(owned)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, help="New directory for BOTH native files")
    args = parser.parse_args()
    app = require(ksapi.GetKompas(), "No running KOMPAS API session; start it yourself")
    previous = app.GetActiveDocument()
    try:
        if args.output_dir is not None:
            directory = args.output_dir.expanduser().resolve()
            directory.mkdir(parents=True, exist_ok=False)
            files = nullcontext(directory)
        else:
            files = TemporaryDirectory(prefix="kompas-assembly-")
        with files as directory:
            with assembly(app, directory) as doc:
                validate(doc)
                if args.output_dir is not None:
                    save_new(doc, Path(directory) / "assembly.a3d")
                print("PASS: two source-linked solids; fixed origin and free X=30; zero tree errors")
    finally:
        if previous:
            previous.SetActive()


if __name__ == "__main__":
    main()
