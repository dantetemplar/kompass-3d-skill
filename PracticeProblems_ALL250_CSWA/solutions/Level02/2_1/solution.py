# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""SOLIDWORKS Practice Problem 2.1 — native constrained KOMPAS feature tree."""
from __future__ import annotations

import ast
from contextlib import contextmanager
import json
import math
from pathlib import Path
import tempfile
import traceback

import ksapi
from constants import constants as c
from constants3d import constants as c3d

ROOT = Path(__file__).resolve().parent
CHECKS = []
STATES = []


def require(value, message):
    if not value:
        raise RuntimeError(message)
    return value


def report(message):
    print(message, flush=True)


def con(obj, kind, partner=None, index=None, pindex=None, name=None, value=None):
    item = require(obj.NewConstraint(), "NewConstraint")
    item.SetConstraintType(kind)
    if partner is not None:
        item.SetPartners([partner])
    if index is not None:
        item.SetIndex(index)
    if pindex is not None:
        item.SetPartnerIndex(pindex)
    if name is not None:
        item.SetVariable(name)
    if value is not None:
        item.SetConstraintValue(value)
    require(item.Create() and item.IsValid(), f"Constraint {kind} {name}")
    return item


def drive(dim, name, value):
    report(f"Driving dimension {name}={value}")
    con(dim, c.ksCFixedDim)
    con(dim, c.ksCDimWithVariable, name=name, value=value)


def point_xy(obj, index):
    if isinstance(obj, ksapi.IArc):
        if index == 0:
            return obj.GetXc(), obj.GetYc()
        return (obj.GetX1(), obj.GetY1()) if index == 1 else (obj.GetX2(), obj.GetY2())
    if isinstance(obj, ksapi.ICircle):
        return obj.GetXc(), obj.GetYc()
    if isinstance(obj, ksapi.IPoint):
        return obj.GetX(), obj.GetY()
    return (obj.GetX1(), obj.GetY1()) if index == 0 else (obj.GetX2(), obj.GetY2())


def lin(symbols, a, ia, b, ib, orient, name, value):
    p, q = point_xy(a, ia), point_xy(b, ib)
    dim = require(symbols.GetLineDimensions().Add(), "Linear dimension")
    dim.SetX1(p[0]); dim.SetY1(p[1])
    dim.SetX2(q[0]); dim.SetY2(q[1])
    dim.SetX3((p[0]+q[0])/2 + (6 if orient == c.ksLinDVertical else 0))
    dim.SetY3((p[1]+q[1])/2 + (6 if orient == c.ksLinDHorizontal else 0))
    dim.SetOrientation(orient)
    require(dim.Update(), "Linear Update")
    require(dim.Associate(), f"Associate {name}")
    drive(dim, name, value)


def radial(symbols, obj, radius, name):
    dim = require(symbols.GetRadialDimensions().Add(), "Radial dimension")
    dim.SetBaseObject(obj)
    dim.SetXc(obj.GetXc()); dim.SetYc(obj.GetYc())
    dim.SetRadius(radius); dim.SetAngle(40)
    require(dim.Update(), "Radial Update")
    drive(dim, name, radius)


def segment(drawing, p, q):
    obj = require(drawing.GetLineSegments().Add(), "Line")
    obj.SetX1(p[0]); obj.SetY1(p[1])
    obj.SetX2(q[0]); obj.SetY2(q[1])
    require(obj.Update(), "Line Update")
    return obj


def arc(drawing, center, r, a, b, clockwise):
    obj = require(drawing.GetArcs().Add(), "Arc")
    obj.SetXc(center[0]); obj.SetYc(center[1]); obj.SetRadius(r)
    obj.SetAngle1(math.degrees(a) % 360); obj.SetAngle2(math.degrees(b) % 360)
    obj.SetDirection(clockwise)
    require(obj.Update(), "Arc Update")
    return obj


@contextmanager
def sketch(part, model, name, z=0):
    plane = require(part.GetDefaultObject(c3d.o3d_planeXOY), "XOY")
    if z:
        plane = require(ksapi.IAuxiliaryGeomContainer(part).GetPlanes3D().Add(c3d.o3d_planeOffset), "Offset plane")
        plane.SetName(f"Plane Z={z:g}")
        offset = ksapi.IPlane3DByOffset(plane)
        offset.SetBasePlane(part.GetDefaultObject(c3d.o3d_planeXOY))
        offset.SetOffset(abs(z)); offset.SetDirection(z > 0)
        require(offset.Update(), "Offset plane Update")
    sk = require(model.GetSketchs().Add(), "Sketch")
    sk.SetName(name); sk.SetPlane(plane)
    require(sk.Update(), "Sketch Update")
    fragment = require(sk.BeginEdit(False), "BeginEdit")
    try:
        fragment.SetParametricMode(True)
        view = require(fragment.GetViewsAndLayersManager().GetViews().GetActiveView(), "View")
        drawing = ksapi.IDrawingContainer(view)
        symbols = ksapi.ISymbols2DContainer(view)
        datum = require(drawing.GetPoints().Add(), "Datum")
        datum.SetX(0); datum.SetY(0)
        require(datum.Update(), "Datum Update")
        con(datum, c.ksCFixedPoint, index=0)
        yield sk, drawing, symbols, datum
    finally:
        require(sk.EndEdit(), "EndEdit")
    state = sk.GetConstraintsState()
    STATES.append((name, state))
    CHECKS.append(f"Эскиз «{name}»: GetConstraintsState={state}; WellConstrained=1.")
    report(f"Sketch {name}: state={state}")


def contour(drawing, symbols, datum, prefix, inset=0):
    # R9 concave arcs are centered at the original bounding rectangle corners.
    # An inward parallel contour keeps these centers; R9 grows, R3.75 shrinks.
    L, H = 54.5, 15.5
    r, R = 3.75-inset, 9+inset
    d = math.sqrt((r+R)**2 - 3.75**2)
    a = math.atan2(3.75, d)
    corners = []
    for sx, sy in [(1,1), (1,-1), (-1,-1), (-1,1)]:
        centers = [(L-d,H-3.75),(L,H),(L-3.75,H-d)]
        angles = [(math.pi/2,a),(math.pi+a,1.5*math.pi-a),(math.pi/2-a,0)]
        objs = []
        reflect = sx*sy < 0
        order = range(3) if not reflect else reversed(range(3))
        for j in order:
            cc = (sx*centers[j][0], sy*centers[j][1])
            aa, bb = angles[j]
            p = (sx*math.cos(aa),sy*math.sin(aa))
            q = (sx*math.cos(bb),sy*math.sin(bb))
            if reflect:
                p,q=q,p
            objs.append(arc(drawing,cc,R if j==1 else r,math.atan2(p[1],p[0]),math.atan2(q[1],q[0]),j!=1))
        corners.append(objs)
    # Walk clockwise, with clockwise convex and counterclockwise concave arcs.
    chain = []
    for i, objs in enumerate(corners):
        chain.extend(objs)
        p=point_xy(objs[-1],2)
        q=point_xy(corners[(i+1)%4][0],1)
        chain.append(segment(drawing,p,q))
    for i, obj in enumerate(chain):
        nxt=chain[(i+1)%len(chain)]
        con(obj,c.ksCMergePoints,nxt,2 if isinstance(obj,ksapi.IArc) else 1,1 if isinstance(nxt,ksapi.IArc) else 0)
        con(obj,c.ksCTangentTwoCurves,nxt)
    lines=chain[3::4]
    for i,line in enumerate(lines):
        con(line,c.ksCVertical if i%2==0 else c.ksCHorizontal)
    concaves=[objs[1] for objs in corners]
    convex=[ob for objs in corners for ob in (objs[0],objs[2])]
    radial(symbols,concaves[0],R,prefix+"_concave_R")
    radial(symbols,convex[0],r,prefix+"_fillet_R")
    for obj in concaves[1:]:
        con(obj,c.ksCEqualRadius,concaves[0])
    for obj in convex[1:]:
        con(obj,c.ksCEqualRadius,convex[0])
    for i,obj in enumerate(concaves):
        lin(symbols,datum,0,obj,0,c.ksLinDHorizontal,f"{prefix}_cx{i}",L)
        lin(symbols,datum,0,obj,0,c.ksLinDVertical,f"{prefix}_cy{i}",H)
    # Outer/inner tangent line locations: retain the 1.5 mm parallel edge width.
    for i,line in enumerate(lines):
        value=(L if i%2==0 else H)-inset
        lin(symbols,datum,0,line,0,c.ksLinDHorizontal if i%2==0 else c.ksLinDVertical,f"{prefix}_edge{i}",value)


def circles(drawing,symbols,datum,r,prefix):
    previous=None
    for i,x in enumerate([-45.5,45.5]):
        obj=require(drawing.GetCircles().Add(),"Circle")
        obj.SetXc(x);obj.SetYc(0);obj.SetRadius(r)
        require(obj.Update(),"Circle Update")
        con(obj,c.ksCHAlignPoints,datum,0,0)
        lin(symbols,datum,0,obj,0,c.ksLinDHorizontal,f"{prefix}_offset{i}",45.5)
        if previous:
            con(obj,c.ksCEqualRadius,previous)
        else:
            radial(symbols,obj,r,prefix+"_radius")
        previous=obj


def extrude(model, sk, name, depth, cut=False):
    op=require(model.GetExtrusions().Add(c3d.o3d_cutExtrusion if cut else c3d.o3d_bossExtrusion),"Extrusion")
    op.SetName(name);op.SetProfiles([sk]);op.SetDirection(c3d.dtReverse if cut else c3d.dtNormal)
    require(op.SetSideParameters(not cut,c3d.etBlind,depth,0.,False,None),"Extrusion depth")
    require(op.Update(),name)
    report(name+": Update passed")


def errors(part):
    seen=set();bad=[]
    def visit(f):
        if f.reference in seen:return
        seen.add(f.reference)
        if f.GetObjectError():bad.append((f.GetName(),f.GetObjectError()))
        for child in f.GetSubFeatures(c.ksOperTree,True,True):
            if child:visit(child)
    visit(ksapi.IFeature(part))
    return bad


def main():
    ast.parse(Path(__file__).read_text())
    CHECKS.append("Самостоятельный solution.py с PEP723 проверен ast.parse до CAD-построения.")
    output=Path(tempfile.mkdtemp(prefix="attempt-",dir=ROOT))/"model.m3d"
    require(not output.exists() and not output.is_symlink(),"New output path")
    result=dict(task="2.1",status="failed",title="SOLIDWORKS Practice Problem 2.1 — пластина с бортиком",script="solution.py",model=None,volume_mm3=None,reference_volume=5263,reference_units="mm3",volume_passed=False,checks=CHECKS,limitations=[],tree="Размерный контур 109×31 → заготовка 3 → карман 1.5 (бортик 1.5) → бобышки Ø8 до 3.75 → 2×Ø5 → нижние расточки Ø8×0.75")
    doc=None
    try:
        app=require(ksapi.GetKompas(),"Нет запущенной API-сессии; КОМПАС не запускался")
        doc=require(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart,True),"Own document")
        doc3d=ksapi.IKompasDocument3D(doc)
        part=require(doc3d.GetTopPart(),"Top part")
        part.SetName("2.1 Пластина с периферическим бортиком")
        model=require(part.GetModelContainer(),"Model")
        with sketch(part,model,"01 Основание 109×31, R9, R3.75",-1.5) as (sk,d,s,p):
            contour(d,s,p,"base")
        extrude(model,sk,"02 Заготовка высотой 3 мм",3.)
        with sketch(part,model,"03 Карман, бортик шириной 1.5 мм") as (sk,d,s,p):
            contour(d,s,p,"inner",1.5)
        extrude(model,sk,"04 Карман глубиной 1.5 мм",1.5,True)
        with sketch(part,model,"05 Две бобышки Ø8") as (sk,d,s,p):
            circles(d,s,p,4,"boss")
        extrude(model,sk,"06 Бобышки до высоты 3.75 мм",2.25)
        with sketch(part,model,"07 Два сквозных отверстия Ø5",-1.5) as (sk,d,s,p):
            circles(d,s,p,2.5,"hole")
        extrude(model,sk,"08 Сквозные отверстия Ø5",3.75,True)
        with sketch(part,model,"09 Нижние расточки Ø8",-1.5) as (sk,d,s,p):
            circles(d,s,p,4,"counterbore")
        extrude(model,sk,"10 Нижние расточки глубиной 0.75 мм",.75,True)
        require(doc3d.CompleteRebuildDocument(),"CompleteRebuildDocument")
        require(part.RebuildModel(True),"RebuildModel")
        bad=errors(part)
        require(not bad,f"Feature errors: {bad}")
        CHECKS.append("CompleteRebuildDocument/RebuildModel успешны; рекурсивный обход GetObjectError: ошибок операций нет.")
        bodies=ksapi.IFeature(part).GetResultBodies()
        require(len(bodies)==1 and bodies[0].IsSolid(),"One solid")
        CHECKS.append("Получено ровно одно твёрдое тело.")
        inertia=ksapi.IMassInertiaParam(part)
        inertia.SetLengthUnits(c.ksLUnMM)
        require(inertia.GetLengthUnits()==1,"Mass units readback")
        require(inertia.Calculate() and inertia.IsActual(),"Actual mass calculation")
        require(inertia.GetLengthUnits()==1,"Mass units readback after Calculate")
        v=inertia.GetVolume()
        require(math.isfinite(v) and v>0,"Positive finite volume")
        result["volume_mm3"]=v
        result["volume_passed"]=5262.5<=v<5263.5
        CHECKS.append(f"IMassInertiaParam.SetLengthUnits(ksLUnMM), GetLengthUnits=1 до/после Calculate; V={v:.12f} мм³; [5262.5,5263.5): {result['volume_passed']}.")
        require(not output.exists() and not output.is_symlink(),"SaveAs destination absent")
        require(doc.SaveAs(str(output)),"SaveAs")
        require(output.is_file() and output.stat().st_size>0,"Saved file")
        require(Path(doc.GetFullPath()).resolve()==output.resolve(),"Saved path")
        result["model"]=str(output.relative_to(ROOT))
        CHECKS.append("SaveAs успешен в новый отсутствовавший attempt-*/model.m3d; файл непустой, GetFullPath подтверждён.")
        not_defined=[name for name,state in STATES if state!=c.ksStateWellConstrained]
        if not_defined:result["limitations"].append("Не полностью определены эскизы: "+"; ".join(not_defined))
        if not result["volume_passed"]:result["limitations"].append("Объём вне интервала округления эталона; геометрия под объём не подгонялась.")
        result["status"]="passed" if not result["limitations"] else "partial"
    except Exception as exc:
        result["limitations"].append(f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
        if doc is None:result["status"]="blocked"
    finally:
        if doc is not None:
            try:
                require(doc.Close(c.kdDoNotSaveChanges),"Close own document")
                CHECKS.append("Собственный документ закрыт в finally; чужие документы не изменялись и не закрывались.")
            except Exception as exc:
                result["limitations"].append(f"Не подтверждено закрытие документа: {exc}")
                result["status"]="partial" if result["model"] else "failed"
        (ROOT/"result.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
        report(json.dumps(result,ensure_ascii=False))


if __name__=="__main__":
    main()
