# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow"]
# ///
"""Independently inspect a CLOSED worker artifact; never save it or run worker code."""
from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import traceback
from typing import Any, TypeVar

import ksapi
from constants import constants as c
from constants3d import constants as c3d
from run_examples import capture, require

T = TypeVar("T")
Report = dict[str, Any]
DIMENSION_KINDS = ("Line", "Radial", "Diametral", "Angle", "BreakLine", "Height", "Arc", "BreakRadial")


def checksum(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check(report: Report, name: str, passed: bool | None, actual: Any, expected: Any) -> None:
    report["checks"][name] = {"passed": passed, "actual": actual, "expected": expected}


class Session:
    """No retries; consume ownership before Close. Unknown API failures stop cleanup."""

    def __init__(self, report: Report) -> None:
        self.report = report
        self.healthy = True
        self.owned: list[ksapi.IKompasDocument] = []

    def attempt(self, stage: str, action: Callable[[], T]) -> T | None:
        if not self.healthy:
            return None
        try:
            return action()
        except Exception as error:
            text = str(error).lower()
            lost = isinstance(error, (ConnectionError, OSError, TimeoutError)) or any(
                word in text for word in ("connect", "transport", "socket", "broken pipe", "соединен", "соединён", "обрыв")
            )
            self.healthy = self.healthy and not lost and isinstance(error, RuntimeError)
            self.report["errors"].append({"stage": stage, "error": str(error),
                                          "traceback": traceback.format_exc(), "api_stopped": not self.healthy})
            return None

    def close_last(self) -> None:
        if self.healthy and self.owned:
            doc = self.owned.pop()
            closed = self.attempt("close_owned_document", lambda: doc.Close(c.kdDoNotSaveChanges))
            if not closed:
                self.healthy = False
                self.report["errors"].append({"stage": "close_owned_document", "error": "Close failed; no retry or further API calls", "api_stopped": True})
                check(self.report, "owned_document_closed", False, closed, True)


def raw_volume(part: ksapi.IPart) -> float:
    inertia = require(ksapi.IMassInertiaParam(part), "Mass/inertia interface missing")
    inertia.SetLengthUnits(c.ksLUnMM)
    require(inertia.GetLengthUnits() == c.ksLUnMM, "Length unit readback is not mm")
    require(inertia.Calculate() and inertia.IsActual(), "Volume calculation unavailable/stale")
    value = inertia.GetVolume()
    require(math.isfinite(value) and value > 0, f"Invalid raw volume: {value}")
    return value


def body_bounds(part: ksapi.IPart) -> tuple[list[ksapi.IBody], list[float] | None]:
    bodies = require(ksapi.IFeature(part), "Part feature missing").GetResultBodies()
    if len(bodies) != 1 or not bodies[0].IsSolid():
        return bodies, None
    result = bodies[0].GetGabarit(0., 0., 0., 0., 0., 0.)
    require(len(result) == 7 and result[0], "B-rep bounds unavailable")
    require(all(math.isfinite(value) for value in result[1:]), "Nonfinite B-rep bounds")
    return bodies, list(result[1:])


def calibrate(session: Session, app: ksapi.IApplication) -> float:
    """Qualify GetVolume using our own native 10 mm cube, never the worker target."""
    doc = require(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart, True), "Reference document")
    session.owned.append(doc)
    part = require(ksapi.IKompasDocument3D(doc).GetTopPart(), "Reference part")
    model = require(part.GetModelContainer(), "Reference model")
    sketch = require(model.GetSketchs().Add(), "Reference native sketch")
    sketch.SetPlane(require(part.GetDefaultObject(c3d.o3d_planeXOY), "Reference XOY"))
    require(sketch.Update(), "Reference sketch plane")
    fragment = require(sketch.BeginEdit(False), "Reference sketch edit")

    def draw() -> None:
        view = require(fragment.GetViewsAndLayersManager().GetViews().GetActiveView(), "Reference view")
        rectangle = require(ksapi.IDrawingContainer(view).GetRectangles().Add(), "Reference rectangle")
        rectangle.SetX(0.)
        rectangle.SetY(0.)
        rectangle.SetWidth(10.)
        rectangle.SetHeight(10.)
        require(rectangle.Update(), "Reference rectangle Update")

    error_count = len(session.report["errors"])
    session.attempt("reference_sketch_geometry", draw)
    require(session.healthy, "Reference API stopped; no cleanup calls permitted")
    require(sketch.EndEdit(), "Reference EndEdit")
    require(len(session.report["errors"]) == error_count, "Reference sketch construction failed")
    extrusion = require(model.GetExtrusions().Add(c3d.o3d_bossExtrusion), "Reference native extrusion")
    extrusion.SetProfiles([sketch])
    extrusion.SetDirection(c3d.dtNormal)
    require(extrusion.SetSideParameters(True, c3d.etBlind, 10., 0., False, None), "Reference depth")
    require(extrusion.Update() and part.RebuildModel(True), "Reference rebuild")
    _, bounds = body_bounds(part)
    require(bounds is not None and all(abs(bounds[i + 3] - bounds[i] - 10.) <= 1e-6
                                      for i in range(3)), "Reference is not one solid 10 mm cube")
    raw = raw_volume(part)
    scales = [scale for scale in (1, 1000) if math.isclose(raw * scale, 1000., rel_tol=1e-6)]
    calibration = {"reference_dimensions_mm": [10, 10, 10], "expected_mm3": 1000,
                   "raw_volume": raw, "length_units": "mm", "candidate_scales": [1, 1000],
                   "scale_to_mm3": scales[0] if len(scales) == 1 else None}
    session.report["unit_calibration"] = calibration
    check(session.report, "volume_unit_calibration", len(scales) == 1, calibration, "Own 1000 mm3 cube matches scale 1 or 1000")
    require(len(scales) == 1, f"Cannot qualify GetVolume unit: reference raw={raw}; neither scale 1 nor 1000 matches 1000 mm3")
    return scales[0]


def inspect_tree(part: ksapi.IPart, report: Report) -> None:
    features: list[Report] = []
    seen: set[int] = set()

    def visit(feature: ksapi.IFeature, parents: list[str]) -> None:
        if feature.reference in seen:
            return
        seen.add(feature.reference)
        path = [*parents, feature.GetName()]
        features.append({"path": path, "error": feature.GetObjectError(), "type": feature.GetFeatureType()})
        for child in feature.GetSubFeatures(c.ksOperTree, True, True):
            if child:
                visit(child, path)

    visit(require(ksapi.IFeature(part), "Native feature tree"), [])
    report["features"] = features
    errors = [feature for feature in features if feature["error"] != 0]
    check(report, "feature_errors", not errors, {"count": len(errors), "features": errors}, {"count": 0})


def inspect_sketches(model: ksapi.IModelContainer, session: Session) -> None:
    collection = require(model.GetSketchs(), "Native sketch collection")
    sketches: list[Report] = []
    session.report["sketches"] = sketches
    for index in range(collection.GetCount()):
        sketch = require(collection.GetSketch(index), f"Saved sketch {index}")
        state = sketch.GetConstraintsState()
        record = {"index": index, "name": sketch.GetName(), "state": state, "fixed": sketch.IsFixed(),
                  "fully_defined": state == c.ksStateWellConstrained, "dimensions": None}
        sketches.append(record)
        fragment = require(sketch.BeginEdit(True), "Read-only saved sketch inspection")

        def dimensions() -> dict[str, int]:
            view = require(fragment.GetViewsAndLayersManager().GetViews().GetActiveView(), "Sketch view")
            symbols = require(ksapi.ISymbols2DContainer(view), "Sketch dimension collections")
            return {kind: require(getattr(symbols, f"Get{kind}Dimensions")(), kind).GetCount()
                    for kind in DIMENSION_KINDS}

        record["dimensions"] = session.attempt("read_sketch_dimensions", dimensions)
        if not session.healthy:
            return
        require(sketch.EndEdit(), "End read-only sketch inspection")
    count = len(sketches)
    session.report["sketch_count"] = count
    session.report["fully_defined_sketch_count"] = sum(s["fully_defined"] for s in sketches)
    extrusions = require(model.GetExtrusions(), "Native extrusion collection").GetCount()
    session.report["extrusion_count"] = extrusions
    session.report["dimensions"] = {"per_sketch": [s["dimensions"] for s in sketches],
                                  "total": sum(sum(s["dimensions"].values()) for s in sketches if s["dimensions"] is not None)}
    check(session.report, "native_sketches", count > 0, count, ">= 1")
    check(session.report, "native_extrusions", extrusions > 0, extrusions, ">= 1")
    fully_defined = count > 0 and all(s["fully_defined"] for s in sketches)
    session.report["sketches_fully_defined"] = fully_defined
    check(session.report, "sketch_constraints", fully_defined, [s["state"] for s in sketches], c.ksStateWellConstrained)


def inspect_geometry(part: ksapi.IPart, report: Report) -> None:
    bodies, bounds = body_bounds(part)
    check(report, "one_solid_body", len(bodies) == 1 and bounds is not None, {"body_count": len(bodies), "solid": bounds is not None}, {"body_count": 1, "solid": True})
    report["bounds_mm"] = bounds
    extents = [bounds[i + 3] - bounds[i] for i in range(3)] if bounds is not None else None
    report["extents_mm"] = extents
    check(report, "extents_mm", None, extents,
          "World-axis bounding box is diagnostic only: arbitrary proper rotations are allowed; teacher checks dimensions")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="New verification directory")
    parser.add_argument("--task", choices=["1.1"], default="1.1")
    args = parser.parse_args(argv)
    model = args.model.expanduser().resolve(strict=True)
    require(model.is_file() and model.suffix.lower() == ".m3d", "Expected a saved .m3d file")
    output = args.output.expanduser().absolute()
    require(not output.exists() and not output.is_symlink(), "--output directory must be new")
    output.mkdir(parents=True, exist_ok=False)
    report: Report = {"task": args.task, "model": str(model), "checked_at": datetime.now(timezone.utc).isoformat(),
                      "status": "failed", "geometry_passed": False, "native_tree_passed": False,
                      "sketches_fully_defined": False, "checks": {}, "errors": [], "unit_calibration": None,
                      "sha256_before": checksum(model), "warnings": [
                          "Absolute origin and world-axis orientation are ignored by user policy; translations and proper rotations are allowed, reflections are not.",
                          "WellConstrained (including fixed geometry) and dimension counts do not prove dimensional intent; teacher must review worker code.",
                          "Volume plus bounds is not full CAD correctness; teacher must review shape, individual dimensions and actual JPEG.",
                          "Document permits in-memory rebuild; no Save/SaveAs is issued and unchanged disk SHA-256 is required.",
                          "Native counts do not prove all features are dimension-driven; no dimension perturbation or dependency portability test is performed."],
                      "full_cad_correctness_verified": False}
    report["placement_policy"] = "rigid_motion_allowed_no_reflection"
    check(report, "origin", None, "ignored by user policy", "Absolute origin is not an acceptance criterion")
    session = Session(report)
    previous = None
    try:
        def connect() -> ksapi.IApplication:
            return require(ksapi.GetKompas(), "No running API session; CAD will not be launched")
        app = session.attempt("connect", connect)
        if app:
            def verify() -> None:
                nonlocal previous
                previous = app.GetActiveDocument()
                documents = app.GetDocuments()
                already_open = bool(documents.GetItemByFilePath(str(model)))
                check(report, "worker_model_closed", not already_open, already_open, False)
                require(not already_open, "Worker model already open: stop; worker must save and close it. Dirty documents are never closed.")
                # Permit in-memory rebuild; never Save/SaveAs, close without saving.
                doc = require(documents.Open(str(model), True, False), "Open saved worker artifact")
                session.owned.append(doc)
                require(Path(doc.GetFullPath()).resolve() == model, "Opened document path differs from artifact")
                require(doc.GetDocumentType() == c.ksDocumentPart, "Saved artifact is not a part")
                check(report, "saved_artifact_opened", True, doc.GetFullPath(), str(model))
                doc3d = require(ksapi.IKompasDocument3D(doc), "3D document")
                rebuilt = doc3d.CompleteRebuildDocument()
                check(report, "rebuild", bool(rebuilt), rebuilt, True)
                part = require(doc3d.GetTopPart(), "Saved top part")
                for stage, action in (("geometry", lambda: inspect_geometry(part, report)),
                                      ("native_tree", lambda: inspect_tree(part, report)),
                                      ("sketches", lambda: inspect_sketches(require(part.GetModelContainer(), "Saved model"), session))):
                    session.attempt(stage, action)
                if not session.healthy:
                    return
                scale = session.attempt("unit_calibration", lambda: calibrate(session, app))
                if len(session.owned) > 1:
                    session.close_last()
                if scale is not None:
                    raw = session.attempt("target_volume", lambda: raw_volume(part))
                    if raw is not None:
                        volume = raw * scale
                        report["volume_mm3"] = volume
                        check(report, "volume_mm3", abs(volume - 72593.) <= .5,
                              {"raw": raw, "mm3": volume}, {"rounded_mm3": 72593, "tolerance_mm3": .5, "analytic_mm3": 72593.2746051815})
                # Task 1.1 uses Z-up; the document's saved Y-up scheme lays it on its side.
                # Change only the camera. Keep datum planes and the saved artifact untouched.
                report["image"] = session.attempt("capture_jpeg", lambda: capture(
                    doc, output / "model.jpg", view_scheme=c3d.ksVPSZ90AxonometricISO))
            session.attempt("verify_saved_artifact", verify)
    finally:
        while session.healthy and session.owned:
            session.close_last()
        if session.healthy and previous:
            session.attempt("restore_previous_document", previous.SetActive)
        try:
            report["sha256_after"] = checksum(model)
            check(report, "artifact_unchanged", report["sha256_before"] == report["sha256_after"], report["sha256_after"], report["sha256_before"])
        except OSError as error:
            check(report, "artifact_unchanged", False, str(error), report["sha256_before"])
        def passed(names: Sequence[str]) -> bool:
            return not report["errors"] and all(report["checks"].get(name, {}).get("passed") is True for name in names)
        report["geometry_passed"] = passed(("saved_artifact_opened", "rebuild", "one_solid_body", "volume_unit_calibration", "volume_mm3", "artifact_unchanged"))
        report["native_tree_passed"] = passed(("feature_errors", "native_sketches", "native_extrusions", "artifact_unchanged"))
        report["sketches_fully_defined"] = passed(("sketch_constraints", "artifact_unchanged"))
        automated = report["geometry_passed"] and report["native_tree_passed"] and report["sketches_fully_defined"]
        report["status"] = "passed" if automated and report.get("image") else "failed"
        report["status_scope"] = "Automated evidence only, not full CAD correctness; overall success also requires independent teacher review of dimensions, shape and dimensional intent up to translation and proper rotation, never reflection."
        (output / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"{report['status']}: {output / 'verification.json'}", flush=True)
    return 0 if report["status"] in ("passed", "partial") else 1


if __name__ == "__main__":
    raise SystemExit(main())
