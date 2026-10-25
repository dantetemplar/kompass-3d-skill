# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Export a closed native model for worker visual self-check; never save the model."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import ksapi
from constants import constants as c
from constants3d import constants as c3d


def require(value: object, message: str) -> None:
    if not value:
        raise RuntimeError(message)


def new_output(path: Path) -> Path:
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise FileExistsError(path)
    require(path.suffix.lower() in {".jpg", ".jpeg"}, "Preview must be JPEG")
    return path


def capture(doc: ksapi.IKompasDocument, target: Path) -> None:
    target = new_output(target)
    doc.SetActive()
    manager = ksapi.IKompasDocument3D(doc).GetViewProjectionManager()
    manager.SetViewProjectionScheme(c3d.ksVPSZ90AxonometricISO)
    require(manager.GetViewProjectionScheme() == c3d.ksVPSZ90AxonometricISO, "View scheme readback")
    views = [manager.GetViewProjection(i) for i in range(manager.GetCount())]
    iso = [view for view in views if view and view.GetViewProjectonType() == c3d.ksVPIsometric]
    require(len(iso) == 1, "Unique standard isometry required")
    iso[0].SetCurrent(True)
    require(iso[0].IsCurrent(), "Isometry not current")
    frame = doc.GetDocumentFrame()
    require(frame, "Document frame missing")
    for command in (c.ksCMShadedWireframeMode, c.ksCMZoomEntireDocument):
        require(frame.IsKompasCommandEnable(command), "View command unavailable")
        require(frame.ExecuteKompasCommand(command, False), "View command failed")
    parameters = ksapi.IRasterConvertParameters(doc.GetInterface(c.ksObjectRasterConvertParameters))
    require(parameters.Clear(), "Raster settings")
    parameters.SetRasterFormat(c.ksRasterFormatJPG)
    parameters.SetColorBPP(24)
    scale = parameters.CalcRasterScale(doc, 960, 720)
    require(math.isfinite(scale) and scale > 0, "Invalid raster scale")
    new_output(target)
    require(doc.SaveAsToRasterFormat(str(target), parameters), "Raster export failed")
    require(target.is_file() and target.stat().st_size > 3, "Raster missing")
    require(target.read_bytes()[:3] == b"\xff\xd8\xff", "Invalid JPEG signature")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    model = args.model.expanduser().resolve(strict=True)
    target = new_output(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(model.read_bytes()).hexdigest()
    app = ksapi.GetKompas()
    require(app, "Existing CAD session required")
    documents = app.GetDocuments()
    require(not documents.GetItemByFilePath(str(model)), "Close the worker model before preview")
    previous = app.GetActiveDocument()
    print(json.dumps({"stage": "open_for_preview", "model": str(model)}), flush=True)
    doc = documents.Open(str(model), True, False)
    require(doc, "Open saved model failed")
    # No cleanup/retry after any unknown native outcome. Close only on success,
    # once, and never persist the transient display settings to the model file.
    capture(doc, target)
    require(doc.Close(c.kdDoNotSaveChanges), "Close own preview document failed; do not retry")
    if previous:
        previous.SetActive()
    require(hashlib.sha256(model.read_bytes()).hexdigest() == digest, "Model changed during preview")
    print(json.dumps({"preview": str(target), "model_sha256": digest,
                      "image_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                      "model_unchanged": True, "view_scheme": "ksVPSZ90AxonometricISO"}), flush=True)


if __name__ == "__main__":
    main()
