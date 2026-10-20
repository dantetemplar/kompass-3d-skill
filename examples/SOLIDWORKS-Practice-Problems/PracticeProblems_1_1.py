# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Practice Problem 1.1: native constrained sketches and boss extrusions.

The drawing origin is the rear lower-left corner. Local sketch X is width,
Y is height; extrusion is depth. The 20 mm deep stepped section shares its
rear surface with the 28 mm deep base. The projections do not show an overall
mirror-symmetric part: the front 8 mm ledge is not repeated at the rear.
No preview, dimension perturbation, or save/reopen qualification is performed.
"""
from contextlib import contextmanager
import argparse
import json
import math
from pathlib import Path

import ksapi
from constants import constants as c
from constants3d import constants as c3d


def require(value, message):
    if not value:
        raise RuntimeError(message)
    return value


def absent(path):
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"Refusing to overwrite: {path}")


@contextmanager
def edit(sketch):
    fragment = require(sketch.BeginEdit(False), "BeginEdit")
    try:
        fragment.SetParametricMode(True)
        require(fragment.IsParametricMode(), "Parametric mode")
        yield require(fragment.GetViewsAndLayersManager().GetViews().GetActiveView(), "Sketch view")
    finally:
        require(sketch.EndEdit(), "EndEdit")
    state = sketch.GetConstraintsState()
    require(state == c.ksStateWellConstrained, f"Sketch {sketch.GetName()} not fully defined: {state}")
    print(f"Fully defined: {sketch.GetName()}", flush=True)


def constraint(obj, kind, partners=(), index=None, partner_index=None, name=None, value=None):
    item = require(obj.NewConstraint(), "NewConstraint")
    item.SetConstraintType(kind)
    if partners:
        item.SetPartners(list(partners))
    if index is not None:
        item.SetIndex(index)
    if partner_index is not None:
        item.SetPartnerIndex(partner_index)
    if name is not None:
        item.SetVariable(name)
    if value is not None:
        item.SetConstraintValue(value)
    require(item.Create() and item.IsValid(), f"Constraint failed: {kind}, {name}")
    return item


def driving(dim, name, value):
    constraint(dim, c.ksCFixedDim)
    constraint(dim, c.ksCDimWithVariable, name=name, value=value)
    return dim


def linear(symbols, points, orientation, name, value):
    dim = require(symbols.GetLineDimensions().Add(), "Linear dimension")
    (x1, y1), (x2, y2), (x3, y3) = points
    dim.SetX1(x1)
    dim.SetY1(y1)
    dim.SetX2(x2)
    dim.SetY2(y2)
    dim.SetX3(x3)
    dim.SetY3(y3)
    dim.SetOrientation(orientation)
    require(dim.Update(), f"Dimension Update: {name}")
    require(dim.Associate(), f"Dimension Associate: {name}")
    return driving(dim, name, value)


def profile(part, model, name, vertices, dims, prefix):
    sketch = require(model.GetSketchs().Add(), "Add sketch")
    sketch.SetName(name)
    sketch.SetPlane(require(part.GetDefaultObject(c3d.o3d_planeXOY), "XOY plane"))
    require(sketch.Update(), "Sketch plane Update")
    with edit(sketch) as view:
        drawing = require(ksapi.IDrawingContainer(view), "Drawing container")
        symbols = require(ksapi.ISymbols2DContainer(view), "Symbols container")
        lines = []
        for p, q in zip(vertices, vertices[1:] + vertices[:1]):
            line = require(drawing.GetLineSegments().Add(), "Segment")
            line.SetX1(p[0])
            line.SetY1(p[1])
            line.SetX2(q[0])
            line.SetY2(q[1])
            require(line.Update(), "Segment Update")
            lines.append(line)
        for i, line in enumerate(lines):
            constraint(line, c.ksCMergePoints, [lines[(i + 1) % len(lines)]], 1, 0)
            p, q = vertices[i], vertices[(i + 1) % len(vertices)]
            constraint(line, c.ksCHorizontal if p[1] == q[1] else c.ksCVertical)
        # Only the origin is fixed. All other locations follow dimensions and H/V.
        constraint(lines[0], c.ksCFixedPoint, index=0)
        for label, p, q, place, horizontal, value in dims:
            linear(symbols, [p, q, place], c.ksLinDHorizontal if horizontal else c.ksLinDVertical, prefix + label, value)
        hole = require(drawing.GetCircles().Add(), "Hole circle")
        hole.SetXc(44.)
        hole.SetYc(16.)
        hole.SetRadius(6.)
        require(hole.Update(), "Circle Update")
        linear(symbols, [(44., 16.), (60., 0.), (52., -12.)], c.ksLinDHorizontal, prefix + "hole_right", 16.)
        linear(symbols, [(0., 0.), (44., 16.), (-12., 8.)], c.ksLinDVertical, prefix + "hole_bottom", 16.)
        radius = require(symbols.GetRadialDimensions().Add(), "Hole radius dimension")
        radius.SetBaseObject(hole)
        radius.SetXc(44.)
        radius.SetYc(16.)
        radius.SetRadius(6.)
        radius.SetAngle(35.)
        require(radius.Update(), "Radius Update")
        driving(radius, prefix + "hole_radius", 6.)
    return sketch


def boss(model, sketch, name, depth):
    operation = require(model.GetExtrusions().Add(c3d.o3d_bossExtrusion), "Boss extrusion")
    operation.SetName(name)
    operation.SetProfiles([sketch])
    operation.SetDirection(c3d.dtNormal)
    require(operation.SetSideParameters(True, c3d.etBlind, depth, 0., False, None), "Extrusion depth")
    require(operation.Update(), f"Extrusion Update: {name}")
    return operation


def variable(sketch, name):
    return require(ksapi.IFeature(sketch).GetVariableByName(False, True, name), f"Native variable: {name}")


def check(part):
    require(part.RebuildModel(True), "RebuildModel")
    root = require(ksapi.IFeature(part), "Part feature")
    bodies = root.GetResultBodies()
    require(len(bodies) == 1 and bodies[0].IsSolid(), "Expected one solid")
    errors, visited = [], set()

    def visit(feature):
        if feature.reference in visited:
            return
        visited.add(feature.reference)
        error = feature.GetObjectError()
        if error:
            errors.append((feature.GetName(), error))
        for child in feature.GetSubFeatures(c.ksOperTree, True, True):
            if child:
                visit(child)

    visit(root)
    require(not errors, f"Feature errors: {errors}")
    mass = require(ksapi.IMassInertiaParam(part), "Mass properties interface")
    mass.SetLengthUnits(c.ksLUnMM)
    require(mass.Calculate(), "Mass properties Calculate")
    require(mass.IsActual(), "Mass properties not actual")
    volume = mass.GetVolume()
    require(math.isfinite(volume) and volume > 0, f"Invalid volume: {volume}")
    # Reference 72593 is rounded to whole cubic millimetres, not a fit target.
    reference_matches = 72592.5 <= volume < 72593.5
    print(json.dumps({"volume_mm3": volume, "reference_mm3": 72593, "rounded_reference_matches": reference_matches, "one_solid": True, "feature_errors": errors}, ensure_ascii=False), flush=True)
    require(reference_matches, f"Volume {volume} is outside rounded reference interval [72592.5, 72593.5)")
    return volume


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).with_suffix(".m3d"))
    args = parser.parse_args()
    output = args.output.expanduser().absolute()
    require(output.suffix.lower() == ".m3d", "Output must be .m3d")
    absent(output)
    app = require(ksapi.GetKompas(), "No existing KOMPAS API session; application will not be launched")
    previous = app.GetActiveDocument()
    doc = None
    try:
        doc = require(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart, True), "Own new part")
        doc3d = require(ksapi.IKompasDocument3D(doc), "3D document")
        part = require(doc3d.GetTopPart(), "Top part")
        part.SetName("Practice Problem 1.1")
        model = require(part.GetModelContainer(), "Model container")
        h, v = True, False
        outline = [(0., 0.), (60., 0.), (60., 30.), (48., 30.), (48., 38.), (32., 38.), (32., 50.), (20., 50.), (20., 75.), (0., 75.)]
        dims = [
            ("width", (0., 0.), (60., 0.), (30., -7.), h, 60.),
            ("height", (0., 0.), (0., 75.), (-7., 37.), v, 75.),
            ("base_height", (60., 0.), (60., 30.), (68., 15.), v, 30.),
            ("right_inset", (48., 30.), (60., 30.), (54., 23.), h, 12.),
            ("top_width", (0., 75.), (20., 75.), (10., 83.), h, 20.),
            ("upper_tread", (20., 50.), (32., 50.), (26., 57.), h, 12.),
            ("stair_height", (48., 30.), (32., 50.), (76., 40.), v, 20.),
            ("middle_riser", (32., 38.), (32., 50.), (39., 44.), v, 12.),
        ]
        step = profile(part, model, "Stepped profile — 20 deep", outline, dims, "step_")
        boss(model, step, "Stepped section — depth 20", 20.)
        base_dims = [
            ("width", (0., 0.), (60., 0.), (30., -7.), h, 60.),
            ("height", (60., 0.), (60., 30.), (68., 15.), v, 30.),
        ]
        base = profile(part, model, "Base and coaxial through hole", [(0., 0.), (60., 0.), (60., 30.), (0., 30.)], base_dims, "base_")
        # Native expressions keep the second sketch's shared dimensions identical
        # to the source sketch. In particular both circles remain coaxial.
        for source, target in [("step_width", "base_width"), ("step_base_height", "base_height"), ("step_hole_right", "base_hole_right"), ("step_hole_bottom", "base_hole_bottom"), ("step_hole_radius", "base_hole_radius")]:
            variable(step, source).SetExternal(True)
            variable(base, target).SetExpression(source)
        require(doc3d.CompleteRebuildDocument(), "Rebuild shared sketch variables")
        require(base.GetConstraintsState() == c.ksStateWellConstrained, "Linked base sketch is not fully defined")
        boss(model, base, "Base — depth 28", 28.)
        volume = check(part)
        output.parent.mkdir(parents=True, exist_ok=True)
        absent(output)
        require(doc.SaveAs(str(output)), "SaveAs new owned path")
        require(output.is_file() and output.stat().st_size > 0, "Native file was not saved")
        print(json.dumps({"native": str(output), "volume_mm3": volume, "saved": True, "preview_created": False}, ensure_ascii=False), flush=True)
    finally:
        try:
            if doc is not None:
                require(doc.Close(c.kdDoNotSaveChanges), "Close own document")
        finally:
            if previous:
                previous.SetActive()


if __name__ == "__main__":
    main()
