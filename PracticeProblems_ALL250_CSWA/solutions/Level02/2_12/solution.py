# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Practice Problem 2.12 — native dimension-driven KOMPAS-3D v25 part."""
from contextlib import contextmanager
import json
import math
from pathlib import Path
import tempfile

import ksapi
from constants import constants as c
from constants3d import constants as c3d

ROOT = Path(__file__).resolve().parent
REPORT = dict(task="2.12", status="failed", title="Пластина с фигурным окном и двумя отверстиями", script="solution.py", model=None, volume_mm3=None, reference_volume=26501, reference_units="mm3", volume_passed=False, checks=[], limitations=[], tree="Эскиз: контур, окно, 2×Ø21 → Выдавливание 5 мм")
LAST = "preflight"


def require(ok, message):
    if not ok:
        raise RuntimeError(message)
    return ok


def stage(message):
    global LAST
    LAST = message
    print(message, flush=True)


def con(obj, kind, partner=None, index=None, pi=None, name=None, value=None, expression=None):
    if kind == c.ksCMergePoints and partner is not None:
        for existing in obj.GetConstraints():
            if existing.IsValid() and existing.GetConstraintType()==kind and existing.GetIndex()==index and existing.GetPartnerIndex()==pi and any(p.GetId()==partner.GetId() for p in existing.GetPartners()):
                return existing
    q = require(obj.NewConstraint(), "NewConstraint")
    q.SetConstraintType(kind)
    if partner is not None:
        q.SetPartners([partner])
    if index is not None:
        q.SetIndex(index)
    if pi is not None:
        q.SetPartnerIndex(pi)
    if name is not None:
        q.SetVariable(name)
    if value is not None:
        q.SetConstraintValue(value)
    if expression is not None:
        q.SetExpression(expression)
    require(q.Create() and q.IsValid(), f"Constraint {kind}, {name}, last={LAST}")
    return q


def merge(a, ai, b, bi):
    return con(a, c.ksCMergePoints, b, ai, bi)


def drive(dim, name, value, expression=None):
    con(dim, c.ksCFixedDim)
    con(dim, c.ksCDimWithVariable, name=name, value=value, expression=expression)
    return dim


def radius(symbols, obj, center, value, name, expression=None, angle=30):
    d = require(symbols.GetRadialDimensions().Add(), "Radial dimension")
    d.SetBaseObject(obj)
    d.SetXc(center[0]); d.SetYc(center[1]); d.SetRadius(value); d.SetAngle(angle)
    require(d.Update(), "Radius Update")
    return drive(d, name, value, expression)


def linear(symbols, a, ai, pa, b, bi, pb, horizontal, name, value, expression=None):
    d = require(symbols.GetLineDimensions().Add(), "Line dimension")
    d.SetX1(pa[0]); d.SetY1(pa[1]); d.SetX2(pb[0]); d.SetY2(pb[1])
    d.SetX3((pa[0]+pb[0])/2 + (0 if horizontal else -80))
    d.SetY3(-40 if horizontal else (pa[1]+pb[1])/2)
    d.SetOrientation(c.ksLinDHorizontal if horizontal else c.ksLinDVertical)
    require(d.Update(), f"Dimension Update {name}")
    for automatic in d.GetConstraints():
        require(automatic.Delete(), f"Remove automatic dimension association {name}")
    for i, obj, ix in ((0, a, ai), (1, b, bi)):
        stage(f"Dimension {name}: witness {i} to point {ix}")
        merge(d, i, obj, ix)
        require(any(q.IsValid() and q.GetConstraintType() == c.ksCMergePoints and q.GetIndex() == i and q.GetPartnerIndex() == ix and any(p.GetId() == obj.GetId() for p in q.GetPartners()) for q in d.GetConstraints()), f"Witness {name}/{i}")
    return drive(d, name, value, expression)


def add(a, b):
    return tuple(x+y for x, y in zip(a, b))


def mul(a, k):
    return tuple(x*k for x in a)


def mirror(a):
    return (-a[0], a[1])


def make_arc(drawing, center, r, a, b, clockwise=False):
    obj = require(drawing.GetArcs().Add(), "Arc")
    obj.SetXc(center[0]); obj.SetYc(center[1]); obj.SetRadius(r)
    obj.SetAngle1(math.degrees(math.atan2(a[1]-center[1], a[0]-center[0])))
    obj.SetAngle2(math.degrees(math.atan2(b[1]-center[1], b[0]-center[0])))
    obj.SetDirection(clockwise)
    require(obj.Update(), "Arc Update")
    return dict(obj=obj, center=center, radius=r, a=a, b=b, start=1, end=2)


def make_line(drawing, a, b):
    obj = require(drawing.GetLineSegments().Add(), "Line")
    obj.SetX1(a[0]); obj.SetY1(a[1]); obj.SetX2(b[0]); obj.SetY2(b[1])
    require(obj.Update(), "Line Update")
    return dict(obj=obj, a=a, b=b, start=0, end=1)


def close_contour(items):
    for item, nxt in zip(items, items[1:]+items[:1]):
        merge(item["obj"], item["end"], nxt["obj"], nxt["start"])
        con(item["obj"], c.ksCTangentTwoCurves, nxt["obj"])


@contextmanager
def edit(sketch):
    fragment = require(sketch.BeginEdit(False), "BeginEdit")
    try:
        fragment.SetParametricMode(True)
        require(fragment.IsParametricMode(), "Parametric mode")
        view = require(fragment.GetViewsAndLayersManager().GetViews().GetActiveView(), "Active sketch view")
        yield require(ksapi.IDrawingContainer(view), "Drawing"), require(ksapi.ISymbols2DContainer(view), "Symbols")
    finally:
        stage("EndEdit own sketch")
        require(sketch.EndEdit(), "EndEdit")


def build(part, model):
    C = (0., 40.); O = (0., 0.); H = (-32.5, 40.)
    # Outer side lobes are concentric with the Ø21 holes; R=60-65/2.
    R = 60.-65./2
    length = math.hypot(*H)
    e = mul(H, 1/length)
    a = (23.-R)/length
    b = math.sqrt(1-a*a)
    n = (a*e[0]-b*e[1], a*e[1]+b*e[0])
    t = (-n[1], n[0])
    A = add(H, mul(n, R)); B = mul(n, 23.)
    # R18 upper blends: internal tangency to R49 and external to R15.
    ux = (33.**2-31.**2-32.5**2)/65.
    U = (ux, 40.+math.sqrt(31.**2-ux**2))
    T = add(C, mul((U[0], U[1]-40.), 49./31.))
    W = add(H, mul((U[0]-H[0], U[1]-H[1]), 15./33.))
    # Lower R18 blends touch R15 and the inset straight sides.
    dot = lambda p, q: sum(x*y for x, y in zip(p, q))
    q = 12.-18.
    s = dot(H,t)+math.sqrt(33.**2-(q-dot(H,n))**2)
    L = add(mul(n,q),mul(t,s))
    K = add(H,mul((L[0]-H[0],L[1]-H[1]),15./33.))
    P = add(L,mul(n,18.)); Q = mul(n,12.)
    sketch = require(model.GetSketchs().Add(), "Sketch")
    sketch.SetName("01 Контуры — R60, R23, R18, R15, 11; 2×Ø21; 65×40")
    sketch.SetPlane(require(part.GetDefaultObject(c3d.o3d_planeXOY), "XOY"))
    require(sketch.Update(), "Sketch Update")
    with edit(sketch) as (d, sy):
        stage("Constrain construction datum first")
        axis=make_line(d,O,C)["obj"]
        axis.SetStyle(3); require(axis.Update(),"Datum axis")
        con(axis,c.ksCFixedPoint,index=0)
        con(axis,c.ksCVertical)
        linear(sy,axis,0,O,axis,1,C,False,"station_Y",40.)
        station=make_line(d,H,mirror(H))["obj"]
        station.SetStyle(3); require(station.Update(),"Hole station")
        con(station,c.ksCHorizontal)
        con(axis,c.ksCPointOnCurveMiddle,station,index=1)
        linear(sy,station,0,H,station,1,mirror(H),True,"hole_spacing",65.)
        stage("Draw outer contour")
        outer = [make_arc(d,C,60.,(60.,40.),(-60.,40.)), make_arc(d,H,R,(-60.,40.),A), make_line(d,A,B), make_arc(d,O,23.,B,mirror(B)), make_line(d,mirror(B),mirror(A)), make_arc(d,mirror(H),R,mirror(A),(60.,40.))]
        stage("Draw inner contour")
        inner = [make_arc(d,C,49.,mirror(T),T), make_arc(d,U,18.,T,W), make_arc(d,H,15.,W,K,True), make_arc(d,L,18.,K,P), make_line(d,P,Q), make_arc(d,O,12.,Q,mirror(Q)), make_line(d,mirror(Q),mirror(P)), make_arc(d,mirror(L),18.,mirror(P),mirror(K)), make_arc(d,mirror(H),15.,mirror(K),mirror(W),True), make_arc(d,mirror(U),18.,mirror(W),mirror(T))]
        holes=[]
        for center in (H,mirror(H)):
            circle=require(d.GetCircles().Add(), "Hole circle")
            circle.SetXc(center[0]); circle.SetYc(center[1]); circle.SetRadius(10.5)
            require(circle.Update(), "Circle Update")
            holes.append(circle)
        top=outer[0]["obj"]; bottom=outer[3]["obj"]
        stage("Constrain datum and hole stations")
        stage("Merge top center with datum")
        for target,base,index in ((top,axis,1),(bottom,axis,0),(holes[0],station,0),(holes[1],station,1)):
            con(target,c.ksCHAlignPoints,base,0,index)
            con(target,c.ksCVAlignPoints,base,0,index)
        radius(sy,holes[0],H,10.5,"hole_R")
        con(holes[1],c.ksCEqualRadius,holes[0])
        radius(sy,top,C,60.,"outer_R")
        radius(sy,bottom,O,23.,"bottom_R")
        con(outer[1]["obj"],c.ksCConcentricity,holes[0])
        con(outer[5]["obj"],c.ksCConcentricity,holes[1])
        stage("Constrain tangent outer contour")
        close_contour(outer)
        stage("Constrain concentric inset and R18 transitions")
        con(inner[0]["obj"],c.ksCConcentricity,top)
        radius(sy,inner[0]["obj"],C,49.,"inner_R","outer_R-11")
        con(inner[5]["obj"],c.ksCConcentricity,bottom)
        radius(sy,inner[5]["obj"],O,12.,"inner_bottom_R","bottom_R-11",250)
        for idx,hole in ((2,holes[0]),(8,holes[1])):
            con(inner[idx]["obj"],c.ksCConcentricity,hole)
        radius(sy,inner[2]["obj"],H,15.,"waist_R")
        con(inner[8]["obj"],c.ksCEqualRadius,inner[2]["obj"])
        radius(sy,inner[1]["obj"],U,18.,"blend_R")
        for idx in (3,7,9):
            con(inner[idx]["obj"],c.ksCEqualRadius,inner[1]["obj"])
        con(inner[4]["obj"],c.ksCParallel,outer[2]["obj"])
        con(inner[6]["obj"],c.ksCParallel,outer[4]["obj"])
        close_contour(inner)
    state=sketch.GetConstraintsState()
    REPORT["checks"].append(f"Состояние эскиза после EndEdit: {state}; fully-defined={state==c.ksStateWellConstrained}")
    REPORT["checks"].append("База: единственная фиксированная точка (0,0); центры отверстий (±32.5,40); нативные совпадения, касания, концентричность, равенство радиусов, параллельность и управляющие размеры")
    if state != c.ksStateWellConstrained:
        REPORT["limitations"].append(f"Эскиз не fully-defined: состояние {state}")
    stage("Extrude 5 mm")
    op=require(model.GetExtrusions().Add(c3d.o3d_bossExtrusion),"Extrusion")
    op.SetName("02 Толщина 5 мм")
    op.SetProfiles([sketch]); op.SetDirection(c3d.dtNormal)
    require(op.SetSideParameters(True,c3d.etBlind,5.,0.,False,None),"Depth 5")
    require(op.Update(),"Extrusion Update")
    return sketch,op


def main():
    doc=None
    output=Path(tempfile.mkdtemp(prefix="attempt-",dir=ROOT))/"model.m3d"
    require(not output.exists(),"New absent model path")
    app=None
    try:
        stage("Connect GetKompas")
        app=require(ksapi.GetKompas(),"Нет запущенной API-сессии КОМПАС; запуск не выполнялся")
        stage("Create owned part")
        doc=require(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart,True),"New part")
        d3=require(ksapi.IKompasDocument3D(doc),"3D document")
        part=require(d3.GetTopPart(),"Top part")
        part.SetName("Practice Problem 2.12")
        sketch,op=build(part,require(part.GetModelContainer(),"Model"))
        stage("Rebuild and verify")
        require(d3.CompleteRebuildDocument(),"CompleteRebuildDocument")
        require(part.RebuildModel(True),"RebuildModel")
        errors=[]; seen=set()
        def visit(feature):
            if feature.reference in seen:return
            seen.add(feature.reference)
            err=feature.GetObjectError()
            if err:errors.append(f"{feature.GetName()}: {err}")
            for child in feature.GetSubFeatures(c.ksOperTree,True,True):
                if child:visit(child)
        feature=require(ksapi.IFeature(part),"Part feature")
        visit(feature)
        require(not errors,f"Feature errors: {errors}")
        bodies=feature.GetResultBodies()
        require(len(bodies)==1 and bodies[0].IsSolid(),"Exactly one solid")
        REPORT["checks"].extend(["CompleteRebuildDocument и RebuildModel(True) успешны", "Ошибок операций дерева нет", "Одно твёрдое тело"])
        state=sketch.GetConstraintsState()
        REPORT["checks"].append(f"Состояние эскиза после перестроения: {state}")
        if state!=c.ksStateWellConstrained and not REPORT["limitations"]:
            REPORT["limitations"].append("Эскиз не полностью определён после перестроения")
        stage("Calculate mass properties in millimeters")
        mass=require(ksapi.IMassInertiaParam(part),"Mass properties")
        mass.SetLengthUnits(c.ksLUnMM)
        before=mass.GetLengthUnits(); require(before==1,"Length units before Calculate")
        require(mass.Calculate(),"Calculate")
        after=mass.GetLengthUnits();require(after==1,"Length units after Calculate")
        volume=mass.GetVolume(); require(math.isfinite(volume) and volume>0,"Valid volume")
        REPORT["volume_mm3"]=volume
        REPORT["volume_passed"]=26500.5<=volume<26501.5
        REPORT["checks"].append(f"МЦХ: GetLengthUnits()==1 до/после Calculate ({before}/{after}); объём {volume:.9f} мм³; интервал [26500.5,26501.5): {REPORT['volume_passed']}")
        if not REPORT["volume_passed"]:REPORT["limitations"].append("Объём вне интервала эталона")
        stage("SaveAs new absent path")
        require(not output.exists() and not output.is_symlink(),"Output must not exist")
        require(doc.SaveAs(str(output)),"SaveAs")
        require(output.is_file() and output.stat().st_size>0,"Saved native model exists")
        REPORT["model"]=str(output.relative_to(ROOT))
        REPORT["checks"].append("Нативная модель сохранена новым SaveAs; файл существует и непуст")
        REPORT["status"]="partial" if REPORT["limitations"] else "passed"
    except Exception as exc:
        REPORT["limitations"].append(f"Последняя операция: {LAST}. {type(exc).__name__}: {exc}")
        REPORT["status"]="partial" if REPORT["model"] else "failed"
        print(f"ERROR at {LAST}: {exc}",flush=True)
    finally:
        if doc is not None:
            stage("Close owned document without additional save")
            try:
                require(doc.Close(c.kdDoNotSaveChanges),"Close own document")
                REPORT["checks"].append("Собственный документ закрыт; чужие документы не изменялись")
            except Exception as exc:
                REPORT["status"]="blocked"
                REPORT["limitations"].append(f"Не подтверждено закрытие собственного документа: {exc}")
        REPORT_PATH=ROOT/"result.json"
        REPORT_PATH.write_text(json.dumps(REPORT,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print(json.dumps(REPORT,ensure_ascii=False),flush=True)


if __name__=="__main__":
    main()
