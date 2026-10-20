# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Pattern four separate R2, height-5 cylinders on R10 about OZ (90 degrees).

Attach to an existing API session. Without --output, validate then discard.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import math
from pathlib import Path

import ksapi
from constants import constants as c
from constants3d import constants as c3d


EXPECTED = ((8.0, -2.0, 0.0, 12.0, 2.0, 5.0),
            (-2.0, 8.0, 0.0, 2.0, 12.0, 5.0),
            (-12.0, -2.0, 0.0, -8.0, 2.0, 5.0),
            (-2.0, -12.0, 0.0, 2.0, -8.0, 5.0))


def require(value, message):
    if not value:
        raise RuntimeError(message)
    return value


def new_part(app, owned):
    doc = require(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart, True), "New part")
    owned.append(doc)  # Register before accessing or modifying the document.
    part = require(ksapi.IKompasDocument3D(doc).GetTopPart(), "Top part")
    part.SetName("07: Circular body pattern")
    return doc, part, require(part.GetModelContainer(), "Model container")


@contextmanager
def edit_sketch(model, plane):
    sketch = require(model.GetSketchs().Add(), "Sketch")
    sketch.SetPlane(plane)
    require(sketch.Update(), "Sketch plane")
    fragment = require(sketch.BeginEdit(False), "Begin sketch")
    try:
        view = require(fragment.GetViewsAndLayersManager().GetViews().GetActiveView(), "Sketch view")
        yield sketch, require(ksapi.IDrawingContainer(view), "Drawing container")
    finally:
        require(sketch.EndEdit(), "End sketch")


def build(part, model):
    plane = require(part.GetDefaultObject(c3d.o3d_planeXOY), "XOY plane")
    with edit_sketch(model, plane) as (profile, drawing):
        circle = require(drawing.GetCircles().Add(), "Seed circle")
        circle.SetXc(10.0)
        circle.SetYc(0.0)
        circle.SetRadius(2.0)
        require(circle.Update(), "Circle geometry")
    seed = require(model.GetExtrusions().Add(c3d.o3d_bossExtrusion), "Seed cylinder")
    seed.SetProfiles([profile])
    seed.SetDirection(c3d.dtNormal)
    seed.SetOperationResult(c3d.ksOperationNewBody)
    require(seed.SetSideParameters(True, c3d.etBlind, 5.0, 0.0, False, None), "Depth")
    require(seed.Update(), "Build seed")
    bodies = ksapi.IFeature(seed).GetResultBodies()
    require(len(bodies) == 1 and bodies[0].IsSolid(), "One solid seed required")

    feature = require(model.GetFeaturePatterns().Add(c3d.o3d_BodiesCircularCopy), "Body pattern")
    pattern = require(ksapi.ICircularPattern(feature), "Circular pattern")
    pattern.SetInitialObjects([bodies[0]])
    pattern.SetAxis(require(part.GetDefaultObject(c3d.o3d_axisOZ), "OZ axis"))
    pattern.SetBuildingType(c3d.ksCPSaveAll)
    pattern.SetCount1(1)
    pattern.SetCount2(4)  # Includes the original body.
    pattern.SetStep2(90.0)
    pattern.SetBoundaryInstancesStepFactor2(False)
    pattern.SetSaveInitialOrientation(False)
    require(pattern.Update(), "Build body pattern")


def validate(part):
    require(part.RebuildModel(True), "Rebuild part")
    root = require(ksapi.IFeature(part), "Part feature")
    errors, seen = [], set()

    def visit(feature, path):
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
    bodies = root.GetResultBodies()  # Pattern alone returns only the three copies.
    require(len(bodies) == 4, f"Expected four bodies, got {len(bodies)}")
    remaining, bounds = list(EXPECTED), []
    for body in bodies:
        require(body.IsSolid(), "Result body is not solid")
        result = body.GetGabarit(0, 0, 0, 0, 0, 0)
        require(result[0] and len(result) == 7, "Body bounds")
        actual = tuple(result[1:])
        matches = [expected for expected in remaining
                   if all(math.isfinite(a) and abs(a - b) <= 1e-5
                          for a, b in zip(actual, expected))]
        require(len(matches) == 1, f"Unexpected or duplicate body bounds: {actual}")
        remaining.remove(matches[0])
        bounds.append(actual)
    require(not remaining, f"Missing bodies: {remaining}")
    return tuple(sorted(bounds))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Save a new .m3d file after validation")
    args = parser.parse_args(argv)
    output = args.output.expanduser().absolute() if args.output else None
    if output is not None and (output.exists() or output.is_symlink()):
        parser.error(f"Output already exists: {output}")
    app = require(ksapi.GetKompas(), "No existing KOMPAS API session")
    previous, owned = app.GetActiveDocument(), []
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
    print(f"Success: 4 solids; bounds={bounds}; output={output or '(not saved)'}")


if __name__ == "__main__":
    main()
