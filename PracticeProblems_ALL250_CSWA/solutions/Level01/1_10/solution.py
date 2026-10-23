# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Practice Problem 1.10: native dimensioned KOMPAS-3D bracket, millimetres."""
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
LIMITATIONS = [
    "Пробные изменения размеров не выполнялись.",
    "Две проушины построены отдельными операциями, их одинаковые размеры не связаны межэскизными выражениями.",
    "Положение нижней точки каждой проушины вычислено из размера 20 мм; связь с этим размером в другом эскизе не создана.",
]
TREE = "Эскиз основания R20/Ø25 → основание 10 → эскиз левой проушины Ø36/Ø22 → проушина 10 → эскиз правой проушины Ø36/Ø22 → проушина 10"


def require(value, message):
    if not value:
        raise RuntimeError(message)
    return value


def stage(message, **data):
    print(json.dumps({"stage": message, **data}, ensure_ascii=False), flush=True)


def link(obj, kind, other=None, index=None, partner_index=None, axis=None, name=None, value=None):
    item = require(obj.NewConstraint(), "NewConstraint")
    item.SetConstraintType(kind)
    if other is not None:
        item.SetPartners([other])
    if index is not None:
        item.SetIndex(index)
    if partner_index is not None:
        item.SetPartnerIndex(partner_index)
    if axis is not None:
        item.SetAxis(axis)
    if name is not None:
        item.SetVariable(name)
    if value is not None:
        item.SetConstraintValue(value)
    require(item.Create() and item.IsValid(), f"Constraint {kind}, {name}")
    return item


def drive(dim, name, value):
    link(dim, c.ksCFixedDim)
    link(dim, c.ksCDimWithVariable, name=name, value=value)
    return dim


def linear(symbols, a, b, name, value, orientation=c.ksLinDParallel):
    dim = require(symbols.GetLineDimensions().Add(), "Line dimension")
    dim.SetX1(a[0]); dim.SetY1(a[1])
    dim.SetX2(b[0]); dim.SetY2(b[1])
    dim.SetX3((a[0]+b[0])/2+8); dim.SetY3((a[1]+b[1])/2-8)
    dim.SetOrientation(orientation)
    require(dim.Update(), f"Dimension Update {name}")
    require(dim.Associate(), f"Dimension Associate {name}")
    return drive(dim, name, value)


def radial(symbols, obj, name, radius):
    dim = require(symbols.GetRadialDimensions().Add(), "Radial dimension")
    dim.SetBaseObject(obj)
    dim.SetXc(obj.GetXc()); dim.SetYc(obj.GetYc())
    dim.SetRadius(radius); dim.SetAngle(35.)
    require(dim.Update(), f"Radial dimension {name}")
    return drive(dim, name, radius)


def line(drawing, a, b, construction=False):
    obj = require(drawing.GetLineSegments().Add(), "Line")
    obj.SetX1(a[0]); obj.SetY1(a[1]); obj.SetX2(b[0]); obj.SetY2(b[1])
    if construction:
        obj.SetStyle(7)
    require(obj.Update(), "Line Update")
    return obj


def circle(drawing, center, radius):
    obj = require(drawing.GetCircles().Add(), "Circle")
    obj.SetXc(center[0]); obj.SetYc(center[1]); obj.SetRadius(radius)
    require(obj.Update(), "Circle Update")
    return obj


def arc(drawing, center, radius, a, b, clockwise):
    obj = require(drawing.GetArcs().Add(), "Arc")
    obj.SetXc(center[0]); obj.SetYc(center[1]); obj.SetRadius(radius)
    obj.SetAngle1(a); obj.SetAngle2(b); obj.SetDirection(clockwise)
    require(obj.Update(), "Arc Update")
    return obj


@contextmanager
def edit(sketch):
    fragment = require(sketch.BeginEdit(False), "BeginEdit")
    try:
        fragment.SetParametricMode(True)
        view = require(fragment.GetViewsAndLayersManager().GetViews().GetActiveView(), "View")
        yield ksapi.IDrawingContainer(view), ksapi.ISymbols2DContainer(view)
    finally:
        require(sketch.EndEdit(), "EndEdit")
    state = sketch.GetConstraintsState()
    stage("sketch", name=sketch.GetName(), constraints_state=state)
    CHECKS.append(f"Состояние связей эскиза «{sketch.GetName()}»: {state}.")
    if state != c.ksStateWellConstrained:
        LIMITATIONS.append(f"Эскиз «{sketch.GetName()}» не подтверждён как полностью определённый: состояние {state}.")


def sketch(model, plane, name):
    obj = require(model.GetSketchs().Add(), "Sketch")
    obj.SetName(name); obj.SetPlane(plane)
    require(obj.Update(), "Sketch plane")
    return obj


def extrusion(model, profile, name, normal=True):
    obj = require(model.GetExtrusions().Add(c3d.o3d_bossExtrusion), "Extrusion")
    obj.SetName(name); obj.SetProfiles([profile])
    obj.SetDirection(c3d.dtNormal if normal else c3d.dtReverse)
    require(obj.SetSideParameters(normal, c3d.etBlind, 10., 0., False, None), "Depth 10")
    require(obj.Update(), f"Extrusion {name}")
    stage("extrusion", name=name)
    return obj


def build_base(part, model):
    a = math.radians(17.5); co = math.cos(a); si = math.sin(a)
    q = 20 + 45*si
    jx = -co*q + si*10; jy = si*q + co*10
    pts = [(0.,0.), (-56*co,56*si), (-56*co+10*si,56*si+10*co),
           (jx,jy), (-20*co,45+20*si), (20*co,45+20*si),
           (-jx,jy), (56*co-10*si,56*si+10*co), (56*co,56*si)]
    sk = sketch(model, part.GetDefaultObject(c3d.o3d_planeXOY), "01 Основание: 35°, R20, Ø25")
    with edit(sk) as (d,s):
        l = [line(d,pts[i],pts[i+1]) for i in range(4)]
        top = arc(d,(0.,45.),20.,162.5,17.5,True)
        l += [line(d,pts[i],pts[(i+1)%9]) for i in range(5,9)]
        for i in range(3): link(l[i],c.ksCMergePoints,l[i+1],1,0)
        link(l[3],c.ksCMergePoints,top,1,1)
        link(top,c.ksCMergePoints,l[4],2,0)
        for i in range(4,7): link(l[i],c.ksCMergePoints,l[i+1],1,0)
        link(l[7],c.ksCMergePoints,l[0],1,0)
        link(l[0],c.ksCFixedPoint,index=0)
        # Minimal anchoring: origin and circle-centre x; no fixed contour vertices.
        link(top,c.ksCVAlignPoints,l[0],0,0)
        for obj in (l[0],l[7]):
            link(obj,c.ksCFixedAngle)
        link(l[6],c.ksCEqualLength,l[1])
        link(l[7],c.ksCEqualLength,l[0])
        link(l[1],c.ksCPerpendicular,l[0])
        link(l[2],c.ksCParallel,l[0])
        link(l[3],c.ksCPerpendicular,l[0])
        link(l[6],c.ksCPerpendicular,l[7])
        link(l[5],c.ksCParallel,l[7])
        link(l[4],c.ksCPerpendicular,l[7])
        link(l[3],c.ksCTangentTwoCurves,top)
        link(l[4],c.ksCTangentTwoCurves,top)
        linear(s,(0.,0.),(0.,45.),"base_center_height",45.,c.ksLinDVertical)
        linear(s,pts[0],pts[1],"base_outer_station",56.)
        linear(s,pts[1],pts[2],"base_strip_thickness",10.)
        radial(s,top,"base_crown_radius",20.)
        LIMITATIONS.append("Угол 35° задан направлениями двух нативных связей ksCFixedAngle (±17.5°), без именованной угловой переменной.")
        hole = circle(d,(0.,45.),12.5)
        link(hole,c.ksCConcentricity,top)
        radial(s,hole,"base_bore_radius",12.5)
    extrusion(model,sk,"02 Основание, 10 мм")
    return co,si


def face_bounds(face):
    bounds=[]
    for edge in face.GetLimitingEdges():
        b = edge.GetMathCurve().GetGabarit(0,0,0,0,0,0)
        require(b[0],"Edge bounds")
        bounds.append(b[1:])
    return tuple(min(b[i] for b in bounds) for i in range(3))+tuple(max(b[i+3] for b in bounds) for i in range(3))


def build_ear(part, model, co, si, sign, prefix):
    direction=(sign*co,si)
    expected=(min(0.,56*direction[0]),0.,0.,max(0.,56*direction[0]),56*si,10.)
    faces=[]
    for obj in ksapi.IFeature(part).GetModelObjects([c3d.o3d_face]):
        face=ksapi.IFace(obj)
        if face.IsPlanar() and all(abs(x-y)<1e-5 for x,y in zip(face_bounds(face),expected)):
            faces.append(obj)
    require(len(faces)==1,f"Unique outer supporting face {prefix}: {len(faces)}")
    sk=sketch(model,faces[0],f"{prefix} Проушина: Ø36, Ø22, центр 32")
    basis=[]
    for u,v in [(0,0),(1,0),(0,1)]:
        p=sk.GetPoint3D(u,v,0,0,0)
        require(p[0],"Sketch basis")
        basis.append(p[1:])
    ux=tuple(basis[1][i]-basis[0][i] for i in range(3))
    uy=tuple(basis[2][i]-basis[0][i] for i in range(3))
    normal=(ux[1]*uy[2]-ux[2]*uy[1], ux[2]*uy[0]-ux[0]*uy[2], ux[0]*uy[1]-ux[1]*uy[0])
    # Inward toward the R20 crown; no assumption about face local axes.
    inward=(-direction[1]*sign,direction[0]*sign,0.)
    forward=sum(x*y for x,y in zip(normal,inward))>0
    def P(station,height):
        p=sk.GetPointProjectionToXY(direction[0]*station,direction[1]*station,height,0,0)
        require(p[0],"Projection")
        return p[1:]
    p0,p1,p2,p3=P(20.,0.),P(56.,0.),P(56.,32.),P(20.,32.)
    center=P(38.,32.); mid=P(38.,50.)
    a1=math.degrees(math.atan2(p2[1]-center[1],p2[0]-center[0]))
    a2=math.degrees(math.atan2(p3[1]-center[1],p3[0]-center[0]))
    am=math.degrees(math.atan2(mid[1]-center[1],mid[0]-center[0]))
    clockwise=(am-a1)%360 > (a2-a1)%360
    with edit(sk) as (d,s):
        bottom=line(d,p0,p1); right=line(d,p1,p2)
        top=arc(d,center,18.,a1,a2,clockwise)
        left=line(d,p3,p0)
        link(bottom,c.ksCMergePoints,right,1,0)
        link(right,c.ksCMergePoints,top,1,1)
        link(top,c.ksCMergePoints,left,2,0)
        link(left,c.ksCMergePoints,bottom,1,0)
        link(bottom,c.ksCFixedPoint,index=0)
        link(bottom,c.ksCFixedAngle)
        link(right,c.ksCPerpendicular,bottom)
        link(left,c.ksCPerpendicular,bottom)
        link(left,c.ksCEqualLength,right)
        link(right,c.ksCTangentTwoCurves,top)
        link(left,c.ksCTangentTwoCurves,top)
        linear(s,p1,p2,f"{prefix}_center_height",32.)
        radial(s,top,f"{prefix}_outer_radius",18.)
        hole=circle(d,center,11.)
        link(hole,c.ksCConcentricity,top)
        radial(s,hole,f"{prefix}_bore_radius",11.)
    extrusion(model,sk,f"{prefix} Проушина, толщина 10 мм",forward)


def validate(part):
    require(part.RebuildModel(True),"Final rebuild")
    feature=ksapi.IFeature(part)
    bodies=feature.GetResultBodies()
    require(len(bodies)==1 and bodies[0].IsSolid(),"One solid")
    CHECKS.append("После перестроения получено одно твёрдое тело.")
    errors=[]; seen=set()
    def visit(item):
        if item.reference in seen: return
        seen.add(item.reference)
        error=item.GetObjectError()
        if error: errors.append([item.GetName(),error])
        for child in item.GetSubFeatures(c.ksOperTree,True,True):
            if child: visit(child)
    visit(feature)
    require(not errors,f"Tree errors: {errors}")
    CHECKS.append("Дерево операций обойдено: GetObjectError не обнаружил ошибок.")
    mass=ksapi.IMassInertiaParam(part)
    mass.SetLengthUnits(c.ksLUnMM)
    require(mass.GetLengthUnits()==c.ksLUnMM,"Mass length units readback")
    require(mass.Calculate(),"Mass calculation")
    volume=mass.GetVolume()
    require(math.isfinite(volume) and volume>0,"Volume")
    CHECKS.append(f"IMassInertiaParam: GetLengthUnits == ksLUnMM, Calculate выполнен, объём {volume:.9f} мм³.")
    return volume


def main():
    attempt=Path(tempfile.mkdtemp(prefix="attempt-",dir=ROOT))
    output=attempt/"model.m3d"
    result={"task":"1.10","status":"failed","title":"Кронштейн с двумя проушинами","script":"solution.py","model":None,"volume_mm3":None,"reference_volume":46037,"reference_units":"mm3","volume_passed":None,"checks":CHECKS,"limitations":LIMITATIONS,"tree":TREE}
    doc=None; safe=True; model_saved=False; exit_code=1
    try:
        require(not output.exists(),"New output")
        app=require(ksapi.GetKompas(),"No existing KOMPAS API session")
        doc=require(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart,True),"Own document")
        part=require(ksapi.IKompasDocument3D(doc).GetTopPart(),"Top part")
        part.SetName("1.10 Кронштейн с двумя проушинами")
        model=require(part.GetModelContainer(),"Model container")
        stage("build-base")
        co,si=build_base(part,model)
        stage("build-left-ear")
        build_ear(part,model,co,si,-1,"left")
        stage("build-right-ear")
        build_ear(part,model,co,si,1,"right")
        volume=validate(part)
        result["volume_mm3"]=volume
        result["volume_passed"]=46036.5<=volume<46037.5
        CHECKS.append(f"Сравнение с интервалом [46036.5,46037.5): {result['volume_passed']}.")
        require(not output.exists(),"Save must not overwrite")
        require(doc.SaveAs(str(output)),"SaveAs")
        require(output.is_file() and output.stat().st_size>0,"Saved model file")
        model_saved=True; result["model"]=str(output.relative_to(ROOT))
        CHECKS.append("Нативная модель сохранена в новый attempt-каталог; файл непустой.")
        result["status"]="passed" if result["volume_passed"] else "partial"
        exit_code=0
    except Exception as exc:
        stage("exception",error=str(exc))
        traceback.print_exc()
        result["limitations"].append(f"Выполнение остановлено: {type(exc).__name__}: {exc}")
        # Native transport failures have an unknown write outcome: no further CAD calls.
        if not isinstance(exc,(RuntimeError,ValueError,AttributeError,TypeError,FileExistsError)):
            safe=False; result["status"]="blocked"
        if doc and safe and not model_saved:
            if not output.exists():
                saved=doc.SaveAs(str(output))
                if saved and output.is_file() and output.stat().st_size:
                    model_saved=True; result["model"]=str(output.relative_to(ROOT))
                    result["status"]="partial"
                    CHECKS.append("Незавершённая собственная модель сохранена без перезаписи.")
    finally:
        if doc and safe:
            require(doc.Close(c.kdDoNotSaveChanges),"Close own document")
            CHECKS.append("Собственный документ закрыт; чужие документы не изменялись и не закрывались.")
        (ROOT/"result.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        stage("result",**result)
    return exit_code


if __name__=="__main__":
    raise SystemExit(main())
