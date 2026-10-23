# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Practice Problem 1.19: native dimension-driven KOMPAS model, mm."""
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
TITLE = "Practice Problem 1.19 — bracket with R25 rear wall"
TREE = "Основание 5 мм с двумя Ø8 → задняя стенка 5 мм, H35, R25 → боковая стенка 5 мм, H20/12, скос 21"


def require(value, label):
    if not value:
        raise RuntimeError(label)
    return value


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
    require(item.Create() and item.IsValid(), f"Constraint {kind}, {name}")
    return item


def driving(dim, name, value):
    constraint(dim, c.ksCFixedDim)
    constraint(dim, c.ksCDimWithVariable, name=name, value=value)
    return dim


def dimension(symbols, p, q, orientation, partners, name, value, offset=8):
    dim = require(symbols.GetLineDimensions().Add(), "Line dimension")
    dim.SetX1(p[0]); dim.SetY1(p[1])
    dim.SetX2(q[0]); dim.SetY2(q[1])
    dim.SetX3((p[0] + q[0]) / 2 + offset)
    dim.SetY3((p[1] + q[1]) / 2 + offset)
    dim.SetOrientation(orientation)
    require(dim.Update(), f"Dimension update {name}")
    # Associate supplies native witness-point links; verify the actual geometry.
    require(dim.Associate(), f"Dimension association {name}")
    associations = dim.GetConstraints()
    for i, (partner, index) in enumerate(partners):
        require(any(x.IsValid() and x.GetConstraintType() == c.ksCMergePoints
                    and x.GetIndex() == i and x.GetPartnerIndex() == index
                    and any(p.GetId() == partner.GetId() for p in x.GetPartners())
                    for x in associations), f"Dimension witness association {name}/{i}")
    return driving(dim, name, value)


def radial(symbols, obj, center, radius, name):
    dim = require(symbols.GetRadialDimensions().Add(), "Radial dimension")
    dim.SetBaseObject(obj)
    dim.SetXc(center[0]); dim.SetYc(center[1])
    dim.SetRadius(radius); dim.SetAngle(45.)
    require(dim.Update(), "Radial update")
    require(any(x.IsValid() and x.GetConstraintType() == c.ksCAssociation for x in dim.GetConstraints()), "Radial association")
    return driving(dim, name, radius)


def line(drawing, p, q):
    obj = require(drawing.GetLineSegments().Add(), "Line")
    obj.SetX1(p[0]); obj.SetY1(p[1]); obj.SetX2(q[0]); obj.SetY2(q[1])
    require(obj.Update(), "Line update")
    return obj


@contextmanager
def edit(sketch):
    fragment = require(sketch.BeginEdit(False), "BeginEdit")
    try:
        fragment.SetParametricMode(True)
        require(fragment.IsParametricMode(), "Parametric mode")
        view = require(fragment.GetViewsAndLayersManager().GetViews().GetActiveView(), "View")
        yield ksapi.IDrawingContainer(view), ksapi.ISymbols2DContainer(view)
    finally:
        require(sketch.EndEdit(), "EndEdit")
    state = sketch.GetConstraintsState()
    print(json.dumps({"sketch": sketch.GetName(), "constraint_state": state}), flush=True)
    require(state == c.ksStateWellConstrained, f"Sketch {sketch.GetName()} not fully defined: {state}")
    CHECKS.append(f"Эскиз «{sketch.GetName()}»: полностью определён, состояние {state}; геометрические связи и управляющие размеры, без фиксации контура")


def sketch(part, model, plane_type, name):
    obj = require(model.GetSketchs().Add(), "Sketch add")
    obj.SetName(name)
    obj.SetPlane(require(part.GetDefaultObject(plane_type), "Default plane"))
    require(obj.Update(), "Sketch plane update")
    pts = [obj.GetPoint3D(u, v, 0., 0., 0.) for u, v in [(0., 0.), (1., 0.), (0., 1.)]]
    require(all(p[0] for p in pts), "Sketch coordinate system")
    origin = pts[0][1:]
    u = tuple(pts[1][i + 1] - origin[i] for i in range(3))
    v = tuple(pts[2][i + 1] - origin[i] for i in range(3))
    normal = (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])
    print(json.dumps({"plane": name, "origin": origin, "u": u, "v": v, "normal": normal}), flush=True)
    return obj, (origin, u, v, normal)


def project(frame, p):
    origin, u, v, _ = frame
    d = [p[i] - origin[i] for i in range(3)]
    return (sum(d[i]*u[i] for i in range(3)), sum(d[i]*v[i] for i in range(3)))


def polygon(drawing, points):
    lines = [line(drawing, p, q) for p, q in zip(points, points[1:] + points[:1])]
    for i, obj in enumerate(lines):
        constraint(obj, c.ksCMergePoints, [lines[(i+1) % len(lines)]], 1, 0)
        p, q = points[i], points[(i+1) % len(points)]
        if abs(p[1]-q[1]) < 1e-8:
            constraint(obj, c.ksCHorizontal)
        elif abs(p[0]-q[0]) < 1e-8:
            constraint(obj, c.ksCVertical)
    constraint(lines[0], c.ksCFixedPoint, index=0)
    return lines


def axis_orientation(p, q, world_axis, frame):
    # All selected standard planes have their axes along the world axes.
    _, u, v, _ = frame
    if abs(u[world_axis]) > .99:
        return c.ksLinDHorizontal
    require(abs(v[world_axis]) > .99, "Dimension axis")
    return c.ksLinDVertical


def boss(model, profile, frame, target, name):
    op = require(model.GetExtrusions().Add(c3d.o3d_bossExtrusion), "Extrusion add")
    op.SetName(name)
    op.SetProfiles([profile])
    normal_side = sum(a*b for a, b in zip(frame[3], target)) > 0
    op.SetDirection(c3d.dtNormal if normal_side else c3d.dtReverse)
    require(op.SetSideParameters(normal_side, c3d.etBlind, 5., 0., False, None), "Extrusion thickness 5")
    require(op.Update(), f"Extrusion update: {name}")
    require(not ksapi.IFeature(op).GetObjectError(), f"Extrusion error: {name}")
    CHECKS.append(f"Операция «{name}»: Update выполнен, ошибка отсутствует, толщина 5 мм")
    return op


def build(part, model):
    base, frame = sketch(part, model, c3d.o3d_planeXOY, "Основание 75×40, срез 15×15, два Ø8")
    with edit(base) as (drawing, symbols):
        pts = [project(frame, p) for p in [(0,0,0),(75,0,0),(75,25,0),(60,40,0),(0,40,0)]]
        lines = polygon(drawing, pts)
        for a,b,axis,name,value in [(0,1,0,"base_length",75.), (0,4,1,"base_width",40.), (0,3,0,"front_straight",60.), (0,2,1,"chamfer_start",25.)]:
            dimension(symbols, pts[a], pts[b], axis_orientation(pts[a],pts[b],axis,frame), [(lines[a],0),(lines[b],0)], name, value)
        holes=[]
        for i,x in enumerate([20.,55.]):
            p=project(frame,(x,25.,0.))
            hole=require(drawing.GetCircles().Add(), "Circle")
            hole.SetXc(p[0]); hole.SetYc(p[1]); hole.SetRadius(4.)
            require(hole.Update(), "Circle update")
            holes.append(hole)
            dimension(symbols,pts[0],p,axis_orientation(pts[0],p,0,frame),[(lines[0],0),(hole,0)],f"hole_{i+1}_x",x,offset=-10-5*i)
            dimension(symbols,pts[0],p,axis_orientation(pts[0],p,1,frame),[(lines[0],0),(hole,0)],f"hole_{i+1}_y",25.,offset=-10-5*i)
        radial(symbols,holes[0],project(frame,(20.,25.,0.)),4.,"hole_radius")
        constraint(holes[1],c.ksCEqualRadius,[holes[0]])
    boss(model,base,frame,(0,0,1),"Основание с отверстиями — 5 мм")

    rear,frame=sketch(part,model,c3d.o3d_planeXOZ,"Задняя стенка H35 R25")
    with edit(rear) as (drawing,symbols):
        points=[project(frame,p) for p in [(0,0,0),(75,0,0),(75,0,10),(50,0,35),(0,0,35)]]
        # Boundary order: bottom, right, circular quadrant, top, left.
        l0=line(drawing,points[0],points[1]); l1=line(drawing,points[1],points[2])
        arc=require(drawing.GetArcs().Add(),"Arc")
        center=project(frame,(50,0,10))
        arc.SetXc(center[0]); arc.SetYc(center[1]); arc.SetRadius(25.)
        a1=math.degrees(math.atan2(points[2][1]-center[1],points[2][0]-center[0]))%360
        a2=math.degrees(math.atan2(points[3][1]-center[1],points[3][0]-center[0]))%360
        arc.SetAngle1(a1); arc.SetAngle2(a2)
        arc.SetDirection(((a2-a1)%360)>180.)
        require(arc.Update(),"Arc update")
        l3=line(drawing,points[3],points[4]); l4=line(drawing,points[4],points[0])
        objs=[l0,l1,arc,l3,l4]
        for i,obj in enumerate(objs):
            nxt=objs[(i+1)%5]
            constraint(obj,c.ksCMergePoints,[nxt],2 if i==2 else 1,1 if i==1 else 0)
        for obj,p,q in [(l0,points[0],points[1]),(l1,points[1],points[2]),(l3,points[3],points[4]),(l4,points[4],points[0])]:
            constraint(obj,c.ksCHorizontal if abs(p[1]-q[1])<1e-8 else c.ksCVertical)
        constraint(l0,c.ksCFixedPoint,index=0)
        constraint(arc,c.ksCTangentTwoCurves,[l1])
        constraint(arc,c.ksCTangentTwoCurves,[l3])
        dimension(symbols,points[0],points[1],axis_orientation(points[0],points[1],0,frame),[(l0,0),(l0,1)],"rear_length",75.)
        dimension(symbols,points[0],points[4],axis_orientation(points[0],points[4],2,frame),[(l0,0),(l4,0)],"rear_height",35.)
        radial(symbols,arc,center,25.,"rear_radius")
    boss(model,rear,frame,(0,1,0),"Задняя стенка — 5 мм")

    side,frame=sketch(part,model,c3d.o3d_planeYOZ,"Боковая стенка H20/12, скос 21")
    with edit(side) as (drawing,symbols):
        pts=[project(frame,p) for p in [(0,0,0),(0,40,0),(0,40,12),(0,19,20),(0,0,20)]]
        lines=polygon(drawing,pts)
        for a,b,axis,name,value in [(0,1,1,"side_depth",40.),(0,4,2,"side_height",20.),(1,2,2,"front_height",12.),(2,3,1,"slope_run",21.)]:
            dimension(symbols,pts[a],pts[b],axis_orientation(pts[a],pts[b],axis,frame),[(lines[a],0),(lines[b],0)],name,value)
    boss(model,side,frame,(1,0,0),"Боковая стенка — 5 мм")


def feature_errors(part):
    errors=[]; seen=set()
    def visit(feature):
        if feature.reference in seen:
            return
        seen.add(feature.reference)
        if feature.GetObjectError():
            errors.append((feature.GetName(),feature.GetObjectError()))
        for child in feature.GetSubFeatures(c.ksOperTree,True,True):
            if child:
                visit(child)
    visit(ksapi.IFeature(part))
    return errors


def main():
    attempt=Path(tempfile.mkdtemp(prefix="attempt-",dir=ROOT))
    output=attempt/"model.m3d"
    require(not output.exists() and not output.is_symlink(),"Output must not exist")
    result={"task":"1.19","status":"failed","title":TITLE,"script":"solution.py","model":None,"volume_mm3":None,"reference_volume":26719,"reference_units":"mm3","volume_passed":False,"checks":CHECKS,"limitations":[],"tree":TREE}
    doc=None
    try:
        app=require(ksapi.GetKompas(),"No existing KOMPAS API session; not launching")
        doc=require(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart,True),"New owned document")
        part=require(ksapi.IKompasDocument3D(doc).GetTopPart(),"Top part")
        part.SetName(TITLE)
        build(part,require(part.GetModelContainer(),"Model container"))
        require(part.RebuildModel(True),"Final rebuild")
        errors=feature_errors(part)
        require(not errors,f"Feature errors: {errors}")
        CHECKS.append("Полное нативное дерево проверено: ошибок операций/эскизов нет")
        bodies=ksapi.IFeature(part).GetResultBodies()
        require(len(bodies)==1 and bodies[0].IsSolid(),"One solid")
        CHECKS.append("Конечный результат — одно твёрдое тело")
        mass=require(ksapi.IMassInertiaParam(part),"Mass interface")
        mass.SetLengthUnits(c.ksLUnMM)
        require(mass.GetLengthUnits()==1,"Mass length units readback must be 1")
        require(mass.Calculate() and mass.IsActual(),"Mass Calculate actual")
        volume=mass.GetVolume()
        require(math.isfinite(volume) and volume>0,"Positive finite volume")
        result["volume_mm3"]=volume
        result["volume_passed"]=26718.5<=volume<26719.5
        CHECKS.append("IMassInertiaParam.SetLengthUnits(c.ksLUnMM); GetLengthUnits() = 1; Calculate выполнен, МЦХ актуальны")
        CHECKS.append(f"Объём {volume:.9f} мм³; сравнение с [26718.5,26719.5): {result['volume_passed']}")
        require(not output.exists() and not output.is_symlink(),"Pre-SaveAs output must not exist")
        require(doc.SaveAs(str(output)),"SaveAs")
        require(output.is_file() and output.stat().st_size>0,"Native file exists")
        result["model"]=str(output.relative_to(ROOT))
        CHECKS.append("SaveAs в новый несуществовавший attempt-*/model.m3d выполнен; файл существует и непуст")
        result["status"]="passed" if result["volume_passed"] else "partial"
        if not result["volume_passed"]:
            result["limitations"].append("Объём вне интервала округления эталона; геометрия под эталон не подгонялась")
    except Exception as exc:
        result["limitations"].append(f"{type(exc).__name__}: {exc}")
        if doc is None:
            result["status"]="blocked"
        traceback.print_exc()
    finally:
        if doc is not None:
            try:
                require(doc.Close(c.kdDoNotSaveChanges),"Close own document")
                CHECKS.append("Собственный документ закрыт в finally; чужие документы не изменялись")
            except Exception as exc:
                result["status"]="partial" if result["model"] else "failed"
                result["limitations"].append(f"Закрытие собственного документа: {exc}")
        result["limitations"].append("По заданию не выполнялись изменения размеров, повторное открытие, превью и экспорт")
        (ROOT/"result.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=="__main__":
    main()
