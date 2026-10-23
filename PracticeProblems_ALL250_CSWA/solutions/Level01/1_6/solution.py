# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Practice 1.6: standalone native KOMPAS model, no exports or dimension probes."""
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
LIMITATIONS = [
    "Профиль R14 принят концентричным наружной дуге Ø25: отдельный центр R14 на чертеже не указан.",
    "Нижняя образующая принята касательной к Ø25 и проходящей через нижний край передней поверхности пластины; отдельный угол не указан.",
    "Связи между разными эскизами не выражены общими формулами; совпадающие исходные параметры заданы одинаковыми значениями. Пробные изменения размеров не выполнялись.",
]
TREE = "Пластина 60×30×5 → 4×R8 → 2×Ø8 → проушина Ø25/Ø8, ширина 9, наклон 15° → усиление шириной 18, R14 и 2×R2"


def need(value, label):
    if not value:
        raise RuntimeError(label)
    return value


def stage(label):
    print(label, flush=True)


def link(obj, kind, partner=None, index=None, other=None, name=None, value=None):
    item = need(obj.NewConstraint(), "NewConstraint")
    item.SetConstraintType(kind)
    if partner is not None:
        item.SetPartners([partner])
    if index is not None:
        item.SetIndex(index)
    if other is not None:
        item.SetPartnerIndex(other)
    if name is not None:
        item.SetVariable(name)
    if value is not None:
        item.SetConstraintValue(value)
    need(item.Create(), f"Constraint {kind}: {name}")
    need(item.IsValid(), f"Invalid constraint {kind}: {name}")
    return item


def drive(dim, name, value):
    link(dim, c.ksCFixedDim)
    link(dim, c.ksCDimWithVariable, name=name, value=value)
    return dim


def line(drawing, start, end, style=1):
    item = need(drawing.GetLineSegments().Add(), "Line")
    item.SetX1(start[0]); item.SetY1(start[1])
    item.SetX2(end[0]); item.SetY2(end[1])
    item.SetStyle(style)
    need(item.Update(), "Line Update")
    return item


def circle(drawing, center, radius):
    item = need(drawing.GetCircles().Add(), "Circle")
    item.SetXc(center[0]); item.SetYc(center[1]); item.SetRadius(radius)
    need(item.Update(), "Circle Update")
    return item


def arc(drawing, center, radius, a1, a2, clockwise=False):
    item = need(drawing.GetArcs().Add(), "Arc")
    item.SetXc(center[0]); item.SetYc(center[1]); item.SetRadius(radius)
    item.SetAngle1(math.degrees(a1)); item.SetAngle2(math.degrees(a2))
    item.SetDirection(clockwise)
    need(item.Update(), "Arc Update")
    return item


def linear(symbols, p1, p2, direction, name, value, shelf):
    dim = need(symbols.GetLineDimensions().Add(), "Linear dimension")
    dim.SetX1(p1[0]); dim.SetY1(p1[1]); dim.SetX2(p2[0]); dim.SetY2(p2[1])
    dim.SetX3(shelf[0]); dim.SetY3(shelf[1]); dim.SetOrientation(direction)
    need(dim.Update(), "Linear Update")
    need(dim.Associate(), f"Dimension Associate {name}")
    return drive(dim, name, value)


def radial(symbols, obj, name, value):
    dim = need(symbols.GetRadialDimensions().Add(), "Radial dimension")
    dim.SetBaseObject(obj)
    dim.SetXc(obj.GetXc()); dim.SetYc(obj.GetYc()); dim.SetRadius(value); dim.SetAngle(35.)
    need(dim.Update(), "Radial Update")
    return drive(dim, name, value)


@contextmanager
def sketch(model, plane, name):
    sk = need(model.GetSketchs().Add(), "Sketch")
    sk.SetName(name); sk.SetPlane(plane)
    need(sk.Update(), "Sketch plane")
    fragment = need(sk.BeginEdit(False), "BeginEdit")
    try:
        fragment.SetParametricMode(True)
        view = fragment.GetViewsAndLayersManager().GetViews().GetActiveView()
        yield sk, need(ksapi.IDrawingContainer(view), "Drawing"), need(ksapi.ISymbols2DContainer(view), "Symbols")
    finally:
        need(sk.EndEdit(), "EndEdit")
    state = sk.GetConstraintsState()
    CHECKS.append(f"Эскиз «{name}»: GetConstraintsState={state}; WellConstrained={c.ksStateWellConstrained}.")
    stage(f"{name}: constraints={state}")
    if state != c.ksStateWellConstrained:
        LIMITATIONS.append(f"Эскиз «{name}» не полностью определён: состояние {state}.")


def extrusion(model, profile, depth, name, both=False, cut=False):
    op = need(model.GetExtrusions().Add(c3d.o3d_cutExtrusion if cut else c3d.o3d_bossExtrusion), "Extrusion")
    op.SetName(name); op.SetProfiles([profile])
    if both:
        op.SetDirection(c3d.dtBoth)
        need(op.SetSideParameters(True, c3d.etBlind, depth/2, 0., False, None), "Side +")
        need(op.SetSideParameters(False, c3d.etBlind, depth/2, 0., False, None), "Side -")
    else:
        op.SetDirection(c3d.dtReverse if cut else c3d.dtNormal)
        need(op.SetSideParameters(not cut, c3d.etBlind, depth, 0., False, None), "Depth")
    need(op.Update(), f"Extrusion Update: {name}")
    stage(name)
    return op


def plate(part, model):
    plane = part.GetDefaultObject(c3d.o3d_planeXOY)
    with sketch(model, plane, "01 Пластина 60 × 30") as (sk, d, s):
        pts = [(-30.,-15.),(30.,-15.),(30.,15.),(-30.,15.)]
        ls = [line(d, p, q) for p,q in zip(pts,pts[1:]+pts[:1])]
        for i,o in enumerate(ls):
            link(o,c.ksCMergePoints,ls[(i+1)%4],1,0)
            link(o,c.ksCHorizontal if i%2==0 else c.ksCVertical)
        link(ls[0],c.ksCFixedPoint,index=0)
        linear(s,pts[0],pts[1],c.ksLinDHorizontal,"plate_width",60.,(0,-23))
        linear(s,pts[1],pts[2],c.ksLinDVertical,"plate_height",30.,(38,0))
    base = extrusion(model,sk,5.,"02 Толщина пластины 5")
    edges = []
    for obj in ksapi.IFeature(base).GetModelObjects([c3d.o3d_edge]):
        edge = ksapi.IEdge(obj)
        bb = edge.GetMathCurve().GetGabarit(0,0,0,0,0,0)
        need(bb[0],"Edge bounds")
        _,x1,y1,z1,x2,y2,z2 = bb
        if abs(x2-x1)<1e-6 and abs(y2-y1)<1e-6 and abs(z2-z1-5)<1e-6:
            edges.append(edge)
    need(len(edges)==4,"Four corner edges")
    fillet = need(model.GetFillets().Add(),"Fillet")
    fillet.SetName("03 Четыре угла R8")
    fillet.SetBaseObjects(edges); fillet.SetBuildingType(c3d.ksFilletCircleArc)
    fillet.SetRadius1(8.); fillet.SetTangent(False)
    need(fillet.Update(),"Plate fillet")
    with sketch(model,plane,"04 Два крепёжных отверстия Ø8, шаг 40") as (holes,d,s):
        cs = [circle(d,(x,0.),4.) for x in (-20.,20.)]
        link(cs[0],c.ksCFixedPoint,index=0)
        link(cs[1],c.ksCHAlignPoints,cs[0],0,0)
        linear(s,(-20,0),(20,0),c.ksLinDHorizontal,"mount_spacing",40.,(0,-8))
        radial(s,cs[0],"mount_radius",4.)
        link(cs[1],c.ksCEqualRadius,cs[0])
    extrusion(model,holes,5.,"05 Сквозные крепёжные Ø8",cut=True)


def side_geometry():
    # Geometric derivation from 15 degrees, inner face at 5, eye axis at 40.
    a = math.radians(15.)
    center_y = 15. - 35.*math.tan(a) - 12.5/math.cos(a)
    lower_normal = math.atan2(-15.-center_y,35.) - math.acos(12.5/math.hypot(35.,-15.-center_y))
    beta = lower_normal + math.pi/2
    normals = [(-math.sin(a),math.cos(a)),(math.sin(beta),-math.cos(beta))]
    tangents = [(math.cos(a),math.sin(a)),(math.cos(beta),math.sin(beta))]
    centers = [(10.5*n[0]+math.sqrt(16**2-10.5**2)*t[0],10.5*n[1]+math.sqrt(16**2-10.5**2)*t[1]) for n,t in zip(normals,tangents)]
    return a, center_y, lower_normal, normals, centers


def profiles(part, model):
    plane = part.GetDefaultObject(c3d.o3d_planeYOZ)
    a, cy, low, normals, centers = side_geometry()
    # Sketch coordinates discovered from native transform, no plane-name assumption.
    with sketch(model,plane,"06 Центральная проушина, Ø25/Ø8 и 15°") as (sk,d,s):
        axes = [sk.GetPoint3D(u,v,0,0,0) for u,v in ((0,0),(1,0),(0,1))]
        need(all(p[0] for p in axes),"YOZ coordinate status")
        stage(f"YOZ coordinates: {axes}")
        def project(x,y):
            out = sk.GetPointProjectionToXY(0.,y,40.-x,0.,0.)
            need(out[0],"Projection status")
            return out[1],out[2]
        # The subsequent exact arcs use similarity mapping of mathematical side profile.
        origin = project(0,cy)
        ex = project(1,cy); ey = project(0,cy+1)
        vx=(ex[0]-origin[0],ex[1]-origin[1]); vy=(ey[0]-origin[0],ey[1]-origin[1])
        determinant=vx[0]*vy[1]-vx[1]*vy[0]
        need(abs(abs(determinant)-1)<1e-8,"Orthonormal side mapping")
        def P(x,y):
            return (origin[0]+vx[0]*x+vy[0]*y,origin[1]+vx[1]*x+vy[1]*y)
        def A(center,r,aa,bb,cw=False):
            def angle(t):
                return math.atan2(vx[1]*math.cos(t)+vy[1]*math.sin(t),vx[0]*math.cos(t)+vy[0]*math.sin(t))
            return arc(d,P(*center),r,angle(aa),angle(bb),cw if determinant>0 else not cw)
        upper=(12.5*normals[0][0],12.5*normals[0][1])
        lower=(12.5*normals[1][0],12.5*normals[1][1])
        backtop=(35.,15.-cy); backbottom=(35.,-15.-cy)
        top=line(d,P(*backtop),P(*upper))
        eye=A((0.,0.),12.5,a+math.pi/2,low)
        bottom=line(d,P(*lower),P(*backbottom))
        back=line(d,P(*backbottom),P(*backtop))
        link(top,c.ksCMergePoints,eye,1,1)
        link(eye,c.ksCMergePoints,bottom,2,0)
        link(bottom,c.ksCMergePoints,back,1,0)
        link(back,c.ksCMergePoints,top,1,0)
        link(top,c.ksCTangentTwoCurves,eye)
        link(bottom,c.ksCTangentTwoCurves,eye)
        link(back,c.ksCVertical if abs(vy[0])<1e-8 else c.ksCHorizontal)
        link(back,c.ksCFixedPoint,index=1)
        orientation=c.ksLinDVertical if abs(vy[0])<1e-8 else c.ksLinDHorizontal
        linear(s,P(*backbottom),P(*backtop),orientation,"rear_height",30.,P(43,0))
        radial(s,eye,"eye_outer_radius",12.5)
        # Center distance along reach, measured from the inner plate face.
        orientation_x=c.ksLinDHorizontal if abs(vx[1])<1e-8 else c.ksLinDVertical
        linear(s,P(0,0),P(*backtop),orientation_x,"eye_to_inner_face",35.,P(18,-30))
        # Native fixed-angle relation initialized from exact 15° geometry.
        # This is an angular relation, not point/curve fixation.
        link(top,c.ksCFixedAngle)
        LIMITATIONS.append("Наклон 15° центральной проушины задан нативной связью фиксированного угла, без именованной угловой переменной.")
        hole=circle(d,P(0,0),4.)
        link(hole,c.ksCConcentricity,eye)
        radial(s,hole,"pin_radius",4.)
    extrusion(model,sk,9.,"07 Проушина шириной 9",both=True)
    with sketch(model,plane,"08 Усиление R14 и два касательных R2") as (web,d,s):
        # P is a pure Python transform already determined on this same base plane.
        def A2(center,r,aa,bb,cw=False):
            def angle(t):
                return math.atan2(vx[1]*math.cos(t)+vy[1]*math.sin(t),vx[0]*math.cos(t)+vy[0]*math.sin(t))
            return arc(d,P(*center),r,angle(aa),angle(bb),cw if determinant>0 else not cw)
        contacts=[(f[0]+2*n[0],f[1]+2*n[1]) for f,n in zip(centers,normals)]
        join=[(f[0]*14/16,f[1]*14/16) for f in centers]
        top=line(d,P(*backtop),P(*contacts[0]))
        roundtop=A2(centers[0],2.,math.atan2(normals[0][1],normals[0][0]),math.atan2(-centers[0][1],-centers[0][0]))
        relief=A2((0.,0.),14.,math.atan2(join[0][1],join[0][0]),math.atan2(join[1][1],join[1][0]),True)
        roundbottom=A2(centers[1],2.,math.atan2(-centers[1][1],-centers[1][0]),math.atan2(normals[1][1],normals[1][0]))
        bottom=line(d,P(*contacts[1]),P(*backbottom))
        back=line(d,P(*backbottom),P(*backtop))
        objs=[top,roundtop,relief,roundbottom,bottom,back]
        indices=[(0,1),(1,2),(1,2),(1,2),(0,1),(0,1)]
        for i,o in enumerate(objs):
            link(o,c.ksCMergePoints,objs[(i+1)%6],indices[i][1],indices[(i+1)%6][0])
        for left,right in zip(objs[:4],objs[1:5]):
            link(left,c.ksCTangentTwoCurves,right)
        radial(s,relief,"relief_radius",14.)
        radial(s,roundtop,"transition_radius",2.)
        link(roundbottom,c.ksCEqualRadius,roundtop)
        link(relief,c.ksCFixedPoint,index=0)
        link(back,c.ksCFixedPoint,index=0)
        link(back,c.ksCVertical if abs(vy[0])<1e-8 else c.ksCHorizontal)
        linear(s,P(*backbottom),P(*backtop),orientation,"web_rear_height",30.,P(45,0))
        # 15-degree direction and lower tangency-derived direction are native angle constraints.
        for segment in (top,bottom):
            link(segment,c.ksCFixedAngle)
        LIMITATIONS.append("Усиление: направления прямых заданы нативными угловыми связями; нижний угол вычислен из касания основного профиля, а не связан с ним межэскизной формулой.")
    extrusion(model,web,18.,"09 Усиление шириной 18",both=True)


def validate(part, doc3d):
    need(doc3d.CompleteRebuildDocument(),"CompleteRebuildDocument")
    need(part.RebuildModel(True),"RebuildModel")
    feature=ksapi.IFeature(part)
    bodies=feature.GetResultBodies()
    need(len(bodies)==1 and bodies[0].IsSolid(),"One solid")
    CHECKS.append("После CompleteRebuildDocument/RebuildModel получено одно твёрдое тело.")
    errors=[]; visited=set()
    def visit(obj):
        if obj.reference in visited:
            return
        visited.add(obj.reference)
        error=obj.GetObjectError()
        if error:
            errors.append((obj.GetName(),error))
        for child in obj.GetSubFeatures(c.ksOperTree,True,True):
            if child:
                visit(child)
    visit(feature)
    CHECKS.append(f"Рекурсивный обход GetObjectError: {errors}.")
    need(not errors,f"Feature errors: {errors}")
    mass=need(ksapi.IMassInertiaParam(part),"Mass inertia")
    mass.SetLengthUnits(c.ksLUnMM)
    need(mass.GetLengthUnits()==c.ksLUnMM,"Millimetres readback before calculation")
    need(mass.Calculate(),"Mass Calculate")
    need(mass.IsActual(),"Mass actual")
    need(mass.GetLengthUnits()==c.ksLUnMM,"Millimetres readback after calculation")
    volume=mass.GetVolume()
    need(math.isfinite(volume) and volume>0,"Finite volume")
    passed=24031.5<=volume<24032.5
    CHECKS.append(f"IMassInertiaParam.Calculate/IsActual; GetLengthUnits=ksLUnMM до/после расчёта; CAD V={volume:.12g} мм³; интервал [24031.5,24032.5): {passed}.")
    return volume,passed


def main():
    ast.parse(Path(__file__).read_text())
    CHECKS.append("ast.parse самостоятельного solution.py: passed до подключения API.")
    attempt=Path(tempfile.mkdtemp(prefix="attempt-",dir=ROOT))
    output=attempt/"model.m3d"
    need(not output.exists(),"New output")
    result={"task":"1.6","status":"failed","title":"Кронштейн с центральной проушиной","script":"solution.py","model":None,"volume_mm3":None,"reference_volume":24032,"reference_units":"mm3","volume_passed":None,"checks":CHECKS,"limitations":LIMITATIONS,"tree":TREE}
    doc=None; connected=False; safe=True; saved=False
    try:
        app=need(ksapi.GetKompas(),"No running API session")
        connected=True
        doc=need(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart,True),"Own document")
        doc3d=ksapi.IKompasDocument3D(doc)
        part=need(doc3d.GetTopPart(),"Top part")
        part.SetName("1.6 Кронштейн с проушиной")
        model=need(part.GetModelContainer(),"Model container")
        plate(part,model)
        profiles(part,model)
        volume,passed=validate(part,doc3d)
        result.update(volume_mm3=volume,volume_passed=passed)
        need(not output.exists(),"Save path absent")
        need(doc.SaveAs(str(output)),"SaveAs")
        need(output.is_file() and output.stat().st_size>0,"Saved nonempty model")
        need(Path(doc.GetFullPath()).resolve()==output.resolve(),"FullPath readback")
        saved=True
        result["model"]=str(output.relative_to(ROOT))
        CHECKS.append("SaveAs в новый attempt-* успешен; непустой model.m3d существует, GetFullPath подтверждён.")
        if not passed:
            LIMITATIONS.append("CAD-объём не попал в интервал эталона; модель сохранена без подгонки геометрии под объём.")
        result["status"]="passed" if passed and not any("не полностью" in x for x in LIMITATIONS) else "partial"
    except Exception as exc:
        # Native transport loss/unknown API outcomes must not trigger further writes.
        message=f"{type(exc).__name__}: {exc}"
        stage(message)
        traceback.print_exc()
        if not connected or not isinstance(exc,(RuntimeError,ValueError,AssertionError,FileExistsError)):
            safe=False
            result["status"]="blocked"
            LIMITATIONS.append("API/исход вызова неизвестен; новые записи и закрытие не выполнялись.")
        LIMITATIONS.append(message)
        if doc and safe and not saved:
            need(not output.exists(),"Partial output absent")
            if doc.SaveAs(str(output)) and output.exists():
                saved=True; result["model"]=str(output.relative_to(ROOT))
                CHECKS.append("Незавершённая собственная модель сохранена после ошибки построения.")
    finally:
        if doc and safe:
            need(doc.Close(c.kdDoNotSaveChanges),"Close own document")
            CHECKS.append("Собственный документ закрыт в finally; чужие документы не изменялись и не закрывались.")
        text=json.dumps(result,ensure_ascii=False,indent=2)+"\n"
        (attempt/"result.json").write_text(text)
        # The latest machine-readable report; prior native attempts remain untouched.
        (ROOT/"result.json").write_text(text)
        stage(text)
    return 0 if result["status"] in ("passed","partial") else 1


if __name__=="__main__":
    raise SystemExit(main())
