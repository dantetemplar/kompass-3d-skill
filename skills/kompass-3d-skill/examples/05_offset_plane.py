# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Extrude an R5 cylinder from an offset XOY plane: Z=15 through Z=20 mm.

Attach to an existing API session. Without --output, validate then discard.
"""
from __future__ import annotations

import argparse
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
import math
from pathlib import Path
from typing import TypeVar

import ksapi
from constants import constants as c
from constants3d import constants as c3d


EXPECTED = (-5.0, -5.0, 15.0, 5.0, 5.0, 20.0)


T = TypeVar("T")
Bounds = tuple[float, float, float, float, float, float]


def require(value: T | None, message: str) -> T:
    if not value:
        raise RuntimeError(message)
    return value


def new_part(
    app: ksapi.IApplication, owned: list[ksapi.IKompasDocument],
) -> tuple[ksapi.IKompasDocument, ksapi.IPart, ksapi.IModelContainer]:
    doc = require(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart, True), "New part")
    owned.append(doc)  # Register before accessing or modifying the document.
    part = require(ksapi.IKompasDocument3D(doc).GetTopPart(), "Top part")
    part.SetName("05: Offset-plane cylinder")
    return doc, part, require(part.GetModelContainer(), "Model container")


@contextmanager
def edit_sketch(
    model: ksapi.IModelContainer, plane: ksapi.IModelObject,
) -> Iterator[tuple[ksapi.ISketch, ksapi.IDrawingContainer]]:
    sketch = require(model.GetSketchs().Add(), "Sketch")
    sketch.SetPlane(plane)
    require(sketch.Update(), "Sketch plane")
    fragment = require(sketch.BeginEdit(False), "Begin sketch")
    try:
        view = require(fragment.GetViewsAndLayersManager().GetViews().GetActiveView(), "Sketch view")
        yield sketch, require(ksapi.IDrawingContainer(view), "Drawing container")
    finally:
        require(sketch.EndEdit(), "End sketch")


def build(part: ksapi.IPart, model: ksapi.IModelContainer) -> None:
    auxiliary = require(ksapi.IAuxiliaryGeomContainer(part), "Auxiliary geometry")
    plane = require(auxiliary.GetPlanes3D().Add(c3d.o3d_planeOffset), "Offset plane")
    offset = require(ksapi.IPlane3DByOffset(plane), "Offset-plane interface")
    offset.SetBasePlane(require(part.GetDefaultObject(c3d.o3d_planeXOY), "XOY plane"))
    offset.SetOffset(15.0)
    offset.SetDirection(True)
    require(offset.Update(), "Offset plane at Z=15")
    with edit_sketch(model, plane) as (profile, drawing):
        circle = require(drawing.GetCircles().Add(), "Circle")
        circle.SetXc(0.0)
        circle.SetYc(0.0)
        circle.SetRadius(5.0)
        require(circle.Update(), "Circle geometry")

    extrusion = require(model.GetExtrusions().Add(c3d.o3d_bossExtrusion), "Extrusion")
    extrusion.SetProfiles([profile])
    extrusion.SetDirection(c3d.dtNormal)
    require(extrusion.SetSideParameters(True, c3d.etBlind, 5.0, 0.0, False, None), "Depth")
    require(extrusion.Update(), "Build cylinder")


def validate(part: ksapi.IPart) -> Bounds:
    require(part.RebuildModel(True), "Rebuild part")
    root = require(ksapi.IFeature(part), "Part feature")
    errors, seen = [], set()

    def visit(feature: ksapi.IFeature, path: Sequence[str]) -> None:
        if feature.reference in seen:
            return
        seen.add(feature.reference)
        path = [*path, feature.GetName()]
        error = feature.GetObjectError()
        if error:
            errors.append((path, error))
        for child in feature.GetSubFeatures(c.ksOperTree, True, True):
            if child:
                visit(child, path)

    visit(root, [])
    require(not errors, f"Operation tree errors: {errors}")
    bodies = root.GetResultBodies()
    require(len(bodies) == 1, f"Expected one body, got {len(bodies)}")
    require(bodies[0].IsSolid(), "Result is not solid")
    result = bodies[0].GetGabarit(0, 0, 0, 0, 0, 0)
    require(result[0] and len(result) == 7, "Body bounds")
    bounds = tuple(result[1:])
    require(all(math.isfinite(a) and abs(a - b) <= 1e-5
                for a, b in zip(bounds, EXPECTED)), f"Unexpected bounds: {bounds}")
    return bounds


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Save a new .m3d file after validation")
    args = parser.parse_args(argv)
    output = args.output.expanduser().absolute() if args.output else None
    if output is not None and (output.exists() or output.is_symlink()):
        parser.error(f"Output already exists: {output}")

    app = require(ksapi.GetKompas(), "No existing KOMPAS API session")
    previous = app.GetActiveDocument()
    owned = []
    try:
        doc, part, model = new_part(app, owned)
        build(part, model)
        bounds = validate(part)
        if output is not None:
            if output.exists() or output.is_symlink():
                raise FileExistsError(output)
            output.parent.mkdir(parents=True, exist_ok=True)
            require(doc.SaveAs(str(output)), "Save part")
            require(output.is_file() and output.stat().st_size > 0, "Missing or empty output")
    finally:
        try:
            for doc in reversed(owned):
                require(doc.Close(c.kdDoNotSaveChanges), "Close owned part")
        finally:
            if previous:
                previous.SetActive()
    print(f"Success: 1 solid; bounds={bounds}; output={output or '(not saved)'}")


if __name__ == "__main__":
    main()
