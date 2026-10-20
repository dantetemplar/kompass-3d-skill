# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Generic 43 x 27 x 6 plate: minimally anchored native driving dimensions.

Live qualification edits dimension variables, never regenerates geometry. A failed
qualification raises rather than advertising a dimension-driven success. No mass
properties are calculated: all edit evidence comes from fresh native B-rep.

Qualified on native Linux v25: width 43 -> 51 -> 43, radius 3.5 -> 4 -> 3.5;
closure, H/V, perpendicular/parallel edges, hole offsets, one solid and an
error-free tree survived, with state 1 after EndEdit. Not qualified: persistence
after reopen, JPEG export, independent height/offset perturbations, arbitrary
networks, or symbolic dependencies. Associate may add coincident witness links;
their point indices and drawing IDs are explicitly checked (not guessed).
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import math
from pathlib import Path
import tempfile
import time

import ksapi
from constants import constants as c
from constants3d import constants as c3d

TOL = 1e-5


def require(value, message):
    if not value:
        raise RuntimeError(message)
    return value


def evidence(label, **values):
    print(json.dumps({"stage": label, **values}, ensure_ascii=False), flush=True)


@contextmanager
def edit(sketch):
    fragment = require(sketch.BeginEdit(False), "BeginEdit")
    try:
        fragment.SetParametricMode(True)
        require(fragment.IsParametricMode(), "Parametric mode")
        view = require(fragment.GetViewsAndLayersManager().GetViews().GetActiveView(), "Sketch view")
        yield fragment, view
    finally:
        require(sketch.EndEdit(), "EndEdit")
    state = sketch.GetConstraintsState()
    evidence("after-EndEdit", constraint_state=state)
    require(state == c.ksStateWellConstrained, f"Sketch not fully defined: {state}")


def constraint(obj, kind, *, partners=(), index=None, partner_index=None, name=None, value=None):
    item = require(obj.NewConstraint(), "NewConstraint")
    item.SetConstraintType(kind)
    if index is not None:
        item.SetIndex(index)
    if partner_index is not None:
        item.SetPartnerIndex(partner_index)
    if partners:
        item.SetPartners(list(partners))
    if name is not None:
        item.SetVariable(name)
    if value is not None:
        item.SetConstraintValue(value)
    result = item.Create()
    evidence("constraint", type=kind, variable=name, created=result)
    require(result and item.IsValid(), f"Constraint creation failed: type={kind}, name={name}")
    return item


def driving_dimension(dim, name, value):
    constraint(dim, c.ksCFixedDim)
    constraint(dim, c.ksCDimWithVariable, name=name, value=value)
    return dim


def linear_dimension(symbols, points, orientation, partners, name, value):
    dim = require(symbols.GetLineDimensions().Add(), "Linear dimension")
    (x1, y1), (x2, y2), (x3, y3) = points
    dim.SetX1(x1)
    dim.SetY1(y1)
    dim.SetX2(x2)
    dim.SetY2(y2)
    dim.SetX3(x3)
    dim.SetY3(y3)
    dim.SetOrientation(orientation)
    require(dim.Update(), "Linear dimension Update")
    # Associate produces native ksCMergePoints links for the witness points.
    require(dim.Associate(), f"Associate linear dimension: {name}")
    associations = dim.GetConstraints()
    for dimension_index, (partner, point_index) in enumerate(partners):
        require(any(item.IsValid() and item.GetConstraintType() == c.ksCMergePoints
                    and item.GetIndex() == dimension_index and item.GetPartnerIndex() == point_index
                    and any(obj.GetId() == partner.GetId() for obj in item.GetPartners())
                    for item in associations), f"Missing witness-point association: {name}/{dimension_index}")
    evidence("linear-associations", name=name, constraints=[{"type": x.GetConstraintType(), "valid": x.IsValid(), "index": x.GetIndex(), "partner_index": x.GetPartnerIndex()} for x in associations])
    return driving_dimension(dim, name, value)


def build(part, model):
    """Four independent segments, four coincidences, H/V, one anchored point."""
    sketch = require(model.GetSketchs().Add(), "Sketch")
    sketch.SetName("Native dimension network")
    sketch.SetPlane(require(part.GetDefaultObject(c3d.o3d_planeXOY), "XOY"))
    require(sketch.Update(), "Sketch plane")
    with edit(sketch) as (_, view):
        drawing = require(ksapi.IDrawingContainer(view), "Drawing container")
        symbols = require(ksapi.ISymbols2DContainer(view), "Symbols")
        vertices = [(0., 0.), (43., 0.), (43., 27.), (0., 27.)]
        lines = []
        for start, end in zip(vertices, vertices[1:] + vertices[:1]):
            line = require(drawing.GetLineSegments().Add(), "Segment")
            line.SetX1(start[0])
            line.SetY1(start[1])
            line.SetX2(end[0])
            line.SetY2(end[1])
            require(line.Update(), "Segment Update")
            lines.append(line)
        hole = require(drawing.GetCircles().Add(), "Circle")
        hole.SetXc(11.)
        hole.SetYc(9.)
        hole.SetRadius(3.5)
        require(hole.Update(), "Circle Update")
        for i, line in enumerate(lines):
            constraint(line, c.ksCMergePoints, partners=[lines[(i + 1) % 4]], index=1, partner_index=0)
            constraint(line, c.ksCHorizontal if i % 2 == 0 else c.ksCVertical)
        constraint(lines[0], c.ksCFixedPoint, index=0)
        dimensions = {
            "width": linear_dimension(symbols, [(0, 0), (43, 0), (20, -7)], c.ksLinDHorizontal, [(lines[0], 0), (lines[0], 1)], "plate_width", 43.),
            "height": linear_dimension(symbols, [(43, 0), (43, 27), (50, 14)], c.ksLinDVertical, [(lines[1], 0), (lines[1], 1)], "plate_height", 27.),
            "hole_x": linear_dimension(symbols, [(0, 0), (11, 9), (5, -12)], c.ksLinDHorizontal, [(lines[0], 0), (hole, 0)], "hole_x", 11.),
            "hole_y": linear_dimension(symbols, [(0, 0), (11, 9), (-7, 5)], c.ksLinDVertical, [(lines[0], 0), (hole, 0)], "hole_y", 9.),
        }
        radial = require(symbols.GetRadialDimensions().Add(), "Radial dimension")
        radial.SetBaseObject(hole)
        radial.SetXc(11.)
        radial.SetYc(9.)
        radial.SetRadius(3.5)
        radial.SetAngle(35.)
        require(radial.Update(), "Radial dimension Update")
        associations = [item for item in radial.GetConstraints() if item.GetConstraintType() == c.ksCAssociation]
        evidence("radial-associations", constraints=[{"type": item.GetConstraintType(), "valid": item.IsValid()} for item in radial.GetConstraints()])
        require(len(associations) == 1 and associations[0].IsValid(), "SetBaseObject radial association")
        dimensions["radius"] = driving_dimension(radial, "hole_radius", 3.5)
        line_ids = [line.GetId() for line in lines]
        hole_id = hole.GetId()
        dimension_ids = {name: dim.GetId() for name, dim in dimensions.items()}
    operation = require(model.GetExtrusions().Add(c3d.o3d_bossExtrusion), "Extrusion")
    operation.SetProfiles([sketch])
    operation.SetDirection(c3d.dtNormal)
    require(operation.SetSideParameters(True, c3d.etBlind, 6., 0., False, None), "Depth")
    require(operation.Update(), "Extrusion Update")
    return {"sketch": sketch, "line_ids": line_ids, "hole_id": hole_id, "dimension_ids": dimension_ids, "operation": operation}


def drawing_object(fragment, object_id, interface):
    # BeginEdit creates a fresh fragment; its old drawing references are invalid.
    obj = require(fragment.GetObjectById(object_id), f"Drawing object ID {object_id}")
    return require(interface(obj), f"Drawing interface ID {object_id}")


def close_values(actual, expected, message):
    require(len(actual) == len(expected) and all(math.isfinite(a) and abs(a - b) <= TOL for a, b in zip(actual, expected)), f"{message}: {actual}; expected {expected}")


def validate(part):
    """Return fresh B-rep boundary and cylindrical hole; never use inertia caches."""
    require(part.RebuildModel(True), "RebuildModel")
    feature = require(ksapi.IFeature(part), "Part feature")
    bodies = feature.GetResultBodies()
    require(len(bodies) == 1 and bodies[0].IsSolid(), "One solid")
    bounds = bodies[0].GetGabarit(0, 0, 0, 0, 0, 0)
    require(bounds[0], "Solid boundary")
    cylinders = []
    for obj in feature.GetModelObjects([c3d.o3d_face]):
        face = require(ksapi.IFace(obj), "Face")
        if face.IsCylinder():
            rims = []
            for edge in face.GetLimitingEdges():
                if edge.IsCircle():
                    result = require(edge.GetMathCurve(), "Rim curve").GetGabarit(0, 0, 0, 0, 0, 0)
                    require(result[0], "Rim boundary")
                    rims.append(tuple(result[1:]))
            require(len(rims) == 2, "Two circular hole rims")
            radius = face.GetRadius()
            for rim in rims:
                close_values((rim[3] - rim[0], rim[4] - rim[1], rim[5] - rim[2]), (2 * radius, 2 * radius, 0), "Circular XY rim")
            centers = [((r[0] + r[3]) / 2, (r[1] + r[4]) / 2, r[2]) for r in rims]
            close_values(centers[0][:2], centers[1][:2], "Vertical hole axis")
            close_values(sorted(p[2] for p in centers), (0, 6), "Through hole")
            cylinders.append((*centers[0][:2], radius))
    require(len(cylinders) == 1, f"One cylindrical hole: {cylinders}")
    errors, seen = [], set()

    def visit(item):
        if item.reference in seen:
            return
        seen.add(item.reference)
        if item.GetObjectError():
            errors.append((item.GetName(), item.GetObjectError()))
        for child in item.GetSubFeatures(c.ksOperTree, True, True):
            if child:
                visit(child)

    visit(feature)
    require(not errors, f"Feature errors: {errors}")
    return {"bounds": tuple(bounds[1:]), "hole": cylinders[0], "feature_errors": errors}


def check_sketch(network, width, height, radius):
    sketch = network["sketch"]
    with edit(sketch) as (fragment, view):
        lines = [drawing_object(fragment, object_id, ksapi.ILineSegment) for object_id in network["line_ids"]]
        starts, ends, vectors = [], [], []
        for line in lines:
            start, end = (line.GetX1(), line.GetY1()), (line.GetX2(), line.GetY2())
            starts.append(start)
            ends.append(end)
            vectors.append((end[0] - start[0], end[1] - start[1]))
        for i in range(4):
            close_values(ends[i], starts[(i + 1) % 4], "Closure")
            a, b = vectors[i], vectors[(i + 1) % 4]
            close_values((a[0] * b[0] + a[1] * b[1],), (0,), "Perpendicularity")
            opposite = vectors[(i + 2) % 4]
            close_values((a[0] * opposite[1] - a[1] * opposite[0],), (0,), "Parallelism")
        close_values(starts[0], (0, 0), "Minimal anchor")
        close_values((math.dist(starts[0], ends[0]), math.dist(starts[1], ends[1])), (width, height), "Sketch dimensions")
        hole = drawing_object(fragment, network["hole_id"], ksapi.ICircle)
        close_values((hole.GetXc(), hole.GetYc(), hole.GetRadius()), (11, 9, radius), "Hole placement and radius")
        rows = []
        for name, object_id in network["dimension_ids"].items():
            dim = drawing_object(fragment, object_id, ksapi.IDrawingObject)
            variable = require(view.GetDimensionVariable(dim), f"Dimension variable: {name}")
            rows.append({"name": name, "variable": variable.GetName(), "value": variable.GetValue(), "constraints": [x.GetConstraintType() for x in dim.GetConstraints()]})
        evidence("sketch-geometry", vertices=starts, closure=True, perpendicularity=True, parallelism=True, minimal_anchor=True, hole_relation="11 mm from left, 9 mm from bottom", dimensions=rows)


def edit_dimension(network, name, value):
    """Change the source sketch variable outside its temporary 2D edit fragment."""
    variable_name = {"width": "plate_width", "height": "plate_height", "radius": "hole_radius", "hole_x": "hole_x", "hole_y": "hole_y"}[name]
    feature = require(ksapi.IFeature(network["sketch"]), "Sketch feature")
    variable = require(feature.GetVariableByName(False, True, variable_name), f"Native dimension variable: {name}")
    old = variable.GetValue()
    require(not variable.IsInformation() and not variable.IsReadOnly(), "Dimension variable must be driving")
    variable.SetExpression(format(value, ".12g"))
    variable.SetValue(value)
    require(network["doc3d"].CompleteRebuildDocument(), "3D CompleteRebuildDocument")
    variable = require(feature.GetVariableByName(False, True, variable_name), f"Native dimension variable: {name}")
    evidence("native-dimension-edit", dimension=name, variable=variable.GetName(), old=old, requested=value, expression=variable.GetExpression(), readback=variable.GetValue())
    close_values((variable.GetValue(),), (value,), "Variable readback")


def qualify(part, network):
    cases = [(None, None, 43., 27., 3.5), ("width", 51., 51., 27., 3.5), ("width", 43., 43., 27., 3.5), ("radius", 4., 43., 27., 4.), ("radius", 3.5, 43., 27., 3.5)]
    for name, value, width, height, radius in cases:
        if name:
            edit_dimension(network, name, value)
            require(part.RebuildModel(True), "Rebuild edited solid")
        check_sketch(network, width, height, radius)
        result = validate(part)
        close_values(result["bounds"], (0, 0, 0, width, height, 6), "Actual B-rep boundary")
        close_values(result["hole"], (11, 9, radius), "Actual B-rep hole")
        evidence("B-rep-qualification", edit=name, requested=value, **result)
    return result


def absent(paths):
    for path in paths:
        if path.exists() or path.is_symlink():
            raise FileExistsError(f"Refusing existing output: {path}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="New .m3d path; absent means scratch qualification")
    args = parser.parse_args(argv)
    started = time.monotonic()
    scratch = Path(tempfile.mkdtemp(prefix="kompas-dimension-driven-"))
    output = args.output.expanduser().absolute() if args.output else scratch / "dimension_driven.m3d"
    require(output.suffix.lower() == ".m3d", "--output must be .m3d")
    jpg = output.with_suffix(".jpg")
    absent((output, jpg))
    evidence("preflight", scratch=str(scratch), native=str(output), jpg=str(jpg), both_absent=True)
    app = require(ksapi.GetKompas(), "No running KOMPAS API session; will not launch")
    previous = app.GetActiveDocument()
    doc = None
    try:
        doc = require(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart, True), "Own new part")
        part = require(ksapi.IKompasDocument3D(doc).GetTopPart(), "Top part")
        part.SetName("16 — Native dimension-driven generic plate")
        network = build(part, require(part.GetModelContainer(), "Model container"))
        network["doc3d"] = require(ksapi.IKompasDocument3D(doc), "3D document")
        result = qualify(part, network)
        output.parent.mkdir(parents=True, exist_ok=True)
        absent((output, jpg))
        require(doc.SaveAs(str(output)), "SaveAs new owned path")
        require(output.is_file() and output.stat().st_size > 0, "Native output")
        evidence("qualified", **result, native=str(output), native_bytes=output.stat().st_size, jpg_exported=False, qualified=["native linear edit and restore", "native radial edit and restore", "B-rep changes", "coincident closure", "horizontal/vertical", "parallelism/perpendicularity", "minimal point anchor", "hole offsets retained", "fully defined after EndEdit", "error-free feature tree"], not_qualified=["save/reopen persistence", "JPEG export", "independent height/offset perturbations", "arbitrary sketch networks", "symbolic inter-dimension expressions"], wall_seconds=time.monotonic() - started)
    finally:
        try:
            if doc is not None:
                require(doc.Close(c.kdDoNotSaveChanges), "Close own document")
        finally:
            if previous:
                previous.SetActive()
            evidence("cleanup", own_document_closed=doc is not None, previous_active_restored=bool(previous), wall_seconds=time.monotonic() - started)


if __name__ == "__main__":
    main()
