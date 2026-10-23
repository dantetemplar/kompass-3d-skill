# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Practice Problem 1.5: native, dimension-driven KOMPAS-3D part.

All source lengths are inches, converted to millimetres by 25.4.
No imports from skill examples, no preview, no dimension perturbations.
"""
from __future__ import annotations

from contextlib import contextmanager
import ast
import json
import math
from pathlib import Path
import tempfile
import traceback

import ksapi
from constants import constants as c
from constants3d import constants as c3d

ROOT = Path(__file__).resolve().parent
INCH = 25.4
CHECKS = []


def need(value, message):
    if not value:
        raise RuntimeError(message)
    return value


def link(obj, kind, partner=None, index=None, partner_index=None, axis=None,
         name=None, value=None):
    # Parametric drawing may already infer a requested relation at creation.
    for existing in obj.GetConstraints():
        if (existing.IsValid() and existing.GetConstraintType()==kind
                and (index is None or existing.GetIndex()==index)
                and (partner_index is None or existing.GetPartnerIndex()==partner_index)
                and (partner is None or any(p.GetId()==partner.GetId() for p in existing.GetPartners()))
                and (axis is None or (existing.GetAxis() and existing.GetAxis().GetId()==axis.GetId()))
                and (name is None or existing.GetVariable()==name)):
            return existing
    item = need(obj.NewConstraint(), "NewConstraint")
    item.SetConstraintType(kind)
    if partner is not None:
        item.SetPartners([partner])
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
    created=item.Create()
    if not created and item.IsValid():
        # Linux returns False for this redundant coincident relation, while
        # retaining a valid native relation: verify the exact returned constraint.
        need(item.GetConstraintType()==kind and
             (index is None or item.GetIndex()==index) and
             (partner_index is None or item.GetPartnerIndex()==partner_index) and
             (partner is None or any(p.GetId()==partner.GetId() for p in item.GetPartners())),
             "False Create without matching valid relation")
        return item
    if not created or not item.IsValid():
        # Coincident Create can materialize an already inferred relation; read
        # the actual list rather than treating its Boolean as geometric proof.
        for existing in obj.GetConstraints():
            if (existing.IsValid() and existing.GetConstraintType()==kind
                    and (index is None or existing.GetIndex()==index)
                    and (partner_index is None or existing.GetPartnerIndex()==partner_index)
                    and partner is not None and any(p.GetId()==partner.GetId() for p in existing.GetPartners())
                    and name is None and axis is None):
                return existing
        print(json.dumps({"constraint_failed":kind,"object_constraints":[{"type":x.GetConstraintType(),"valid":x.IsValid(),"index":x.GetIndex(),"partner_index":x.GetPartnerIndex(),"partners":[p.GetId() for p in x.GetPartners()]} for x in obj.GetConstraints()]},ensure_ascii=False),flush=True)
    need(created and item.IsValid(), f"Constraint {kind}, variable={name}, object={obj.GetId()}, index={index}, partner={partner.GetId() if partner else None}, partner_index={partner_index}")
    return item


def driver(dim, name, value):
    link(dim, c.ksCFixedDim)
    link(dim, c.ksCDimWithVariable, name=name, value=value)
    return dim


def linear(symbols, first, second, orientation, name, value, shelf):
    obj1, idx1, p = first
    obj2, idx2, q = second
    dim = need(symbols.GetLineDimensions().Add(), "Line dimension")
    dim.SetX1(p[0]); dim.SetY1(p[1])
    dim.SetX2(q[0]); dim.SetY2(q[1])
    dim.SetX3(shelf[0]); dim.SetY3(shelf[1])
    dim.SetOrientation(orientation)
    need(dim.Update(), "Dimension Update")
    # Explicit native witness links avoid automatic selection among coincident points.
    link(dim, c.ksCMergePoints, obj1, 0, idx1)
    link(dim, c.ksCMergePoints, obj2, 1, idx2)
    return driver(dim, name, value)


def radial(symbols, arc, name, radius):
    dim = need(symbols.GetRadialDimensions().Add(), "Radial dimension")
    dim.SetBaseObject(arc)
    dim.SetXc(arc.GetXc()); dim.SetYc(arc.GetYc())
    dim.SetRadius(radius)
    dim.SetAngle(80.0)  # I​​RadialDimension.SetAngle uses degrees.
    need(dim.Update(), "Radial Update")
    need(any(x.IsValid() and x.GetConstraintType() == c.ksCAssociation
             for x in dim.GetConstraints()), "Radial association")
    return driver(dim, name, radius)


@contextmanager
def sketch_edit(sketch):
    fragment = need(sketch.BeginEdit(False), "BeginEdit")
    try:
        fragment.SetParametricMode(True)
        need(fragment.IsParametricMode(), "Parametric mode")
        view = need(fragment.GetViewsAndLayersManager().GetViews().GetActiveView(), "View")
        yield ksapi.IDrawingContainer(view), ksapi.ISymbols2DContainer(view)
    finally:
        need(sketch.EndEdit(), "EndEdit")


def build(part, model):
    sketch = need(model.GetSketchs().Add(), "Sketch")
    sketch.SetName("01 Контур ключа и шестигранник — размеры в мм")
    sketch.SetPlane(need(part.GetDefaultObject(c3d.o3d_planeXOY), "XOY"))
    need(sketch.Update(), "Sketch plane")
    r = 0.4 * INCH
    cx = -0.15 * INCH
    half_bar = 0.2 * INCH
    half_jaw = 0.25 * INCH
    mouth = -0.4 * INCH
    q = math.sqrt(r*r-half_bar*half_bar)
    left_join = cx+q
    right_join = left_join+3.25*INCH
    rc = right_join+q
    tip_y = math.sqrt(r*r-(mouth-cx)**2)
    points = [(mouth,half_jaw), (mouth,tip_y), (left_join,half_bar),
              (right_join,half_bar), (right_join,-half_bar),
              (left_join,-half_bar), (mouth,-tip_y), (mouth,-half_jaw),
              (cx,-half_jaw), (0.0,0.0), (cx,half_jaw)]
    with sketch_edit(sketch) as (drawing, symbols):
        def segment(p, q, construction=False):
            obj = need(drawing.GetLineSegments().Add(), "Segment")
            obj.SetX1(p[0]); obj.SetY1(p[1])
            obj.SetX2(q[0]); obj.SetY2(q[1])
            if construction:
                obj.SetStyle(3)
            need(obj.Update(), "Segment Update")
            return obj

        def arc(center, start, end):
            obj = need(drawing.GetArcs().Add(), "Arc")
            obj.SetXc(center[0]); obj.SetYc(center[1]); obj.SetRadius(r)
            obj.SetAngle1(math.degrees(math.atan2(start[1]-center[1],start[0]-center[0]))%360)
            obj.SetAngle2(math.degrees(math.atan2(end[1]-center[1],end[0]-center[0]))%360)
            obj.SetDirection(True)
            need(obj.Update(), "Arc Update")
            return obj

        # Clockwise outer contour: three circular arcs and eight straight segments.
        arcs_at = {1:(cx,0.0), 3:(rc,0.0), 5:(cx,0.0)}
        edges = []
        for i,p in enumerate(points):
            end = points[(i+1)%len(points)]
            edges.append(arc(arcs_at[i],p,end) if i in arcs_at else segment(p,end))
        start_index = lambda i: 1 if i in arcs_at else 0
        end_index = lambda i: 2 if i in arcs_at else 1
        for i,obj in enumerate(edges):
            j=(i+1)%len(edges)
            link(obj,c.ksCMergePoints,edges[j],end_index(i),start_index(j))
        # Only the apex at the source origin is fixed, never the whole contour.
        link(edges[9],c.ksCFixedPoint,index=0)
        axis = segment((0.0,0.0),(rc,0.0),True)
        link(axis,c.ksCMergePoints,edges[9],0,0)
        link(axis,c.ksCHorizontal)
        link(edges[3],c.ksCMergePoints,axis,0,1)
        for i in (0,6):
            link(edges[i],c.ksCVertical)
        for i in (2,4,7,10):
            link(edges[i],c.ksCHorizontal)
        link(edges[1],c.ksCMergePoints,edges[5],0,0)
        link(edges[5],c.ksCEqualRadius,edges[1])
        link(edges[3],c.ksCEqualRadius,edges[1])
        link(edges[1],c.ksCHAlignPoints,edges[9],0,0)
        link(edges[1],c.ksCVAlignPoints,edges[10],0,0)
        link(edges[8],c.ksCSymmetryTwoPoints,edges[10],0,0,axis=axis)
        link(edges[0],c.ksCVAlignPoints,edges[7],0,0)
        link(edges[2],c.ksCSymmetryTwoPoints,edges[4],0,1,axis=axis)
        radial(symbols,edges[1],"head_radius",r)
        def witness(i,end=False):
            return edges[i],end_index(i) if end else start_index(i),points[(i+int(end))%len(points)]
        linear(symbols,witness(0),witness(9),c.ksLinDHorizontal,
               "jaw_total_depth",0.4*INCH,(-5.0,19.0))
        linear(symbols,witness(0),witness(10),c.ksLinDHorizontal,
               "jaw_flat_depth",0.25*INCH,(-6.0,15.0))
        linear(symbols,witness(8),witness(10),c.ksLinDVertical,
               "jaw_opening",0.5*INCH,(-20.0,0.0))
        linear(symbols,witness(4,True),witness(2),c.ksLinDVertical,
               "handle_width",0.4*INCH,(30.0,0.0))
        linear(symbols,witness(2),witness(2,True),c.ksLinDHorizontal,
               "handle_clear_length",3.25*INCH,(40.0,17.0))
        # Correct regular six-sided opening, flat-to-flat 0.5 inch.
        hex_r = 0.5*INCH/math.sqrt(3.0)
        guide = need(drawing.GetCircles().Add(), "Hexagon construction circle")
        guide.SetXc(rc); guide.SetYc(0.0); guide.SetRadius(hex_r); guide.SetStyle(3)
        need(guide.Update(), "Construction circle Update")
        link(guide,c.ksCMergePoints,edges[3],0,0)
        vertices=[(rc+hex_r*math.cos(i*math.pi/3),hex_r*math.sin(i*math.pi/3)) for i in range(6)]
        polygon=[segment(vertices[i],vertices[(i+1)%6]) for i in range(6)]
        for i,obj in enumerate(polygon):
            link(obj,c.ksCMergePoints,polygon[(i+1)%6],1,0)
            link(obj,c.ksCPointOnCurve,guide,0)
            if i:
                link(obj,c.ksCEqualLength,polygon[0])
        link(polygon[1],c.ksCHorizontal)
        linear(symbols,(polygon[4],0,vertices[4]),(polygon[1],0,vertices[1]),
               c.ksLinDVertical,"hexagon_across_flats",0.5*INCH,(rc+17.0,0.0))
    state=sketch.GetConstraintsState()
    CHECKS.append(f"Состояние связей эскиза после EndEdit: {state}; WellConstrained={c.ksStateWellConstrained}.")
    operation=need(model.GetExtrusions().Add(c3d.o3d_bossExtrusion),"Boss extrusion")
    operation.SetName("02 Выдавливание — толщина 0.3 in = 7.62 мм")
    operation.SetProfiles([sketch]); operation.SetDirection(c3d.dtNormal)
    need(operation.SetSideParameters(True,c3d.etBlind,0.3*INCH,0.0,False,None),"Thickness")
    need(operation.Update(),"Extrusion Update")
    return sketch,operation,state


def inspect_tree(part):
    errors=[]
    names=[]
    seen=set()
    def visit(feature):
        if feature.reference in seen:
            return
        seen.add(feature.reference)
        names.append(feature.GetName())
        error=feature.GetObjectError()
        if error:
            errors.append((feature.GetName(),error))
        for child in feature.GetSubFeatures(c.ksOperTree,True,True):
            if child:
                visit(child)
    visit(need(ksapi.IFeature(part),"Part feature"))
    return names,errors


def main():
    ast.parse(Path(__file__).read_text(encoding="utf-8"))
    CHECKS.append("ast.parse: синтаксис самостоятельного solution.py проверен перед CAD-вызовами.")
    attempt=Path(tempfile.mkdtemp(prefix="attempt-",dir=ROOT))
    output=attempt/"model.m3d"
    result={"task":"1.5","status":"failed","title":"Комбинированный гаечный ключ",
            "script":"solution.py","model":None,"volume_mm3":None,
            "reference_volume":0.5492,"reference_units":"in3","volume_passed":None,
            "checks":CHECKS,"limitations":[],
            "tree":"Размерный эскиз контура и правильного шестигранника → выдавливание 7.62 мм"}
    doc=None
    unknown=False
    code=1
    try:
        app=need(ksapi.GetKompas(),"Нет текущей API-сессии; запуск запрещён")
        need(not output.exists(),"New model path")
        doc=need(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart,True),"Own new document")
        doc3d=need(ksapi.IKompasDocument3D(doc),"3D document")
        part=need(doc3d.GetTopPart(),"Top part")
        part.SetName("1.5 Комбинированный гаечный ключ")
        sketch,operation,state=build(part,need(part.GetModelContainer(),"Model container"))
        need(part.RebuildModel(True),"RebuildModel")
        bodies=ksapi.IFeature(part).GetResultBodies()
        need(len(bodies)==1 and bodies[0].IsSolid(),"One solid")
        CHECKS.append("После перестроения получено одно твёрдое тело.")
        names,errors=inspect_tree(part)
        CHECKS.append(f"Рекурсивный обход дерева GetObjectError: {errors}.")
        need(not errors,"Feature errors")
        mass=need(ksapi.IMassInertiaParam(part),"Mass properties")
        mass.SetLengthUnits(c.ksLUnMM)
        need(mass.GetLengthUnits()==c.ksLUnMM,"Length units readback before calculation")
        need(mass.Calculate() and mass.IsActual(),"Actual CAD volume")
        units=mass.GetLengthUnits()
        need(units==c.ksLUnMM,"Length units readback after calculation")
        volume=mass.GetVolume()
        need(math.isfinite(volume) and volume>0,"Positive finite volume")
        volume_in3=volume/INCH**3
        passed=0.54915<=volume_in3<0.54925
        result["volume_mm3"]=volume
        result["volume_passed"]=passed
        CHECKS.append(f"IMassInertiaParam.Calculate/IsActual; GetLengthUnits={units}=ksLUnMM до/после расчёта; CAD {volume:.12g} мм³ = {volume_in3:.12g} in³; интервал [0.54915,0.54925): {passed}.")
        need(not output.exists() and not output.is_symlink(),"No overwrite")
        need(doc.SaveAs(str(output)),"SaveAs")
        need(output.is_file() and output.stat().st_size>0,"Nonempty native model")
        need(Path(doc.GetFullPath()).resolve()==output.resolve(),"Saved path readback")
        result["model"]=str(output.relative_to(ROOT))
        CHECKS.append("SaveAs в новый attempt-* успешен; непустой model.m3d существует; GetFullPath подтверждён.")
        if state!=c.ksStateWellConstrained:
            result["limitations"].append(f"Эскиз не полностью определён: состояние {state}; управляющие размеры и геометрические связи созданы, полной определённости не заявлено.")
        if not passed:
            result["limitations"].append("Объём не попал в интервал эталона; сохранена собственная модель без подгонки размеров. Контур прочитан как дуги R0.4, вертикальные торцы зева на x=-0.4, начало скосов x=-0.15, их вершина в начале координат; размер 3.25 — между пересечениями дуг с рукояткой. Причина расхождения с эталоном не установлена.")
        result["status"]="passed" if passed and state==c.ksStateWellConstrained else "partial"
        code=0
    except (ConnectionError,BrokenPipeError,EOFError) as exc:
        unknown=True
        result["status"]="blocked"
        result["limitations"].append(f"Потеря API, исход последнего вызова неизвестен; новые записи/закрытие не выполнялись: {exc}")
        traceback.print_exc()
    except Exception as exc:
        result["limitations"].append(f"Построение/проверка остановлена: {type(exc).__name__}: {exc}")
        result["limitations"].append(traceback.format_exc())
        traceback.print_exc()
    finally:
        if doc is not None and not unknown:
            try:
                need(doc.Close(c.kdDoNotSaveChanges),"Close own document")
                CHECKS.append("Собственный документ закрыт в finally; чужие документы не изменялись и не закрывались.")
            except Exception as exc:
                code=1
                result["status"]="blocked"
                result["limitations"].append(f"Закрытие собственного документа не подтверждено: {exc}")
        text=json.dumps(result,ensure_ascii=False,indent=2)+"\n"
        (attempt/"result.json").write_text(text,encoding="utf-8")
        (ROOT/"result.json").write_text(text,encoding="utf-8")
        print(text,flush=True)
    return code


if __name__=="__main__":
    raise SystemExit(main())
