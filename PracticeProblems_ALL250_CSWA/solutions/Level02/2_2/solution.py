# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Practice Problem 2.2: native constrained profile and recessed constant rim."""
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
LIMITATIONS = []


def require(value, message):
    if not value:
        raise RuntimeError(message)
    return value


def stage(message, **data):
    print(json.dumps(dict(stage=message, **data), ensure_ascii=False), flush=True)


def con(obj, kind, partner=None, index=None, pi=None, name=None, value=None):
    link = require(obj.NewConstraint(), 'NewConstraint')
    link.SetConstraintType(kind)
    if partner is not None:
        link.SetPartners([partner])
    if index is not None:
        link.SetIndex(index)
    if pi is not None:
        link.SetPartnerIndex(pi)
    if name:
        link.SetVariable(name)
    if value is not None:
        link.SetConstraintValue(value)
    require(link.Create() and link.IsValid(), f'Constraint {kind}: {name}')
    return link


def driving(dim, name, value):
    con(dim, c.ksCFixedDim)
    con(dim, c.ksCDimWithVariable, name=name, value=value)


def linear(symbols, obj1, i1, p1, obj2, i2, p2, horizontal, name, value):
    dim = require(symbols.GetLineDimensions().Add(), 'Line dimension')
    dim.SetX1(p1[0]); dim.SetY1(p1[1])
    dim.SetX2(p2[0]); dim.SetY2(p2[1])
    dim.SetX3((p1[0] + p2[0])/2 + (0 if horizontal else 7))
    dim.SetY3((p1[1] + p2[1])/2 + (7 if horizontal else 0))
    dim.SetOrientation(c.ksLinDHorizontal if horizontal else c.ksLinDVertical)
    require(dim.Update(), 'Dimension Update')
    require(dim.Associate(), f'Associate {name}')
    driving(dim, name, value)


def radial(symbols, obj, center, radius, name):
    dim = require(symbols.GetRadialDimensions().Add(), 'Radial dimension')
    dim.SetBaseObject(obj)
    dim.SetXc(center[0]); dim.SetYc(center[1])
    dim.SetRadius(radius); dim.SetAngle(35)
    require(dim.Update(), 'Radial Update')
    driving(dim, name, radius)


@contextmanager
def edit(part, model, name):
    sketch = require(model.GetSketchs().Add(), 'Sketch')
    sketch.SetName(name)
    sketch.SetPlane(require(part.GetDefaultObject(c3d.o3d_planeXOY), 'XOY'))
    require(sketch.Update(), 'Sketch Update')
    fragment = require(sketch.BeginEdit(False), 'BeginEdit')
    try:
        fragment.SetParametricMode(True)
        view = require(fragment.GetViewsAndLayersManager().GetViews().GetActiveView(), 'View')
        yield sketch, ksapi.IDrawingContainer(view), ksapi.ISymbols2DContainer(view)
    finally:
        require(sketch.EndEdit(), 'EndEdit')
    state = sketch.GetConstraintsState()
    stage('sketch', name=name, state=state)
    if state != c.ksStateWellConstrained:
        LIMITATIONS.append(f'{name}: состояние связей {state}, не полностью определён.')
    else:
        CHECKS.append(f'Эскиз «{name}» полностью определён (state=1), без фиксации всей геометрии.')


def line(drawing, p, q):
    obj = require(drawing.GetLineSegments().Add(), 'Line')
    obj.SetX1(p[0]); obj.SetY1(p[1]); obj.SetX2(q[0]); obj.SetY2(q[1])
    require(obj.Update(), 'Line Update')
    return obj


def arc(drawing, center, radius, a1, a2, clockwise):
    obj = require(drawing.GetArcs().Add(), 'Arc')
    obj.SetXc(center[0]); obj.SetYc(center[1]); obj.SetRadius(radius)
    obj.SetAngle1(math.degrees(a1)%360); obj.SetAngle2(math.degrees(a2)%360)
    obj.SetDirection(clockwise)
    require(obj.Update(), 'Arc Update')
    return obj


def profile(drawing, symbols):
    angle = math.radians(12)
    bx = 87 - math.sqrt(100 - 2.5**2)
    by = -6.5
    ax, ay = bx - 22.5, by + 22.5*math.tan(angle)
    dx = ax - math.sqrt(7.5**2 - (ay + 6.5)**2)
    alpha = math.atan2(ay+6.5, ax-dx)
    beta = math.atan2(2.5, 87-bx)
    specs = [((dx,-6.5),2.5,-math.pi/2,alpha,False),
             ((ax,ay),5,alpha+math.pi,math.pi/2-angle,True),
             ((bx,by),5,math.pi/2-angle,beta,True),
             ((87,-4),5,beta+math.pi,0,False),
             ((88,5),4,0,math.pi/2,False),
             ((0,0),9,math.pi/2,3*math.pi/2,False)]
    def point(i, end):
        (cx,cy),r,u,v,_ = specs[i]
        a = v if end else u
        return cx+r*math.cos(a), cy+r*math.sin(a)
    arcs = [arc(drawing,*spec) for spec in specs]
    # Six arcs and four straight tangent runs form one outer contour.
    l0 = line(drawing,point(5,True),point(0,False))
    l1 = line(drawing,point(1,True),point(2,False))
    l2 = line(drawing,point(3,True),point(4,False))
    l3 = line(drawing,point(4,True),point(5,False))
    chain = [(l0,0,1),(arcs[0],1,2),(arcs[1],1,2),(l1,0,1),
             (arcs[2],1,2),(arcs[3],1,2),(l2,0,1),(arcs[4],1,2),
             (l3,0,1),(arcs[5],1,2)]
    for (obj,_,end),(nxt,start,_) in zip(chain,chain[1:]+chain[:1]):
        con(obj,c.ksCMergePoints,nxt,end,start)
        con(obj,c.ksCTangentTwoCurves,nxt)
    con(l0,c.ksCHorizontal); con(l2,c.ksCVertical); con(l3,c.ksCHorizontal)
    con(arcs[5],c.ksCFixedPoint,index=0)
    for i,((center,r,_,_,_),obj) in enumerate(zip(specs,arcs)):
        radial(symbols,obj,center,r,f'R_{i}')
    linear(symbols,arcs[5],0,(0,0),arcs[4],0,(88,5),True,'right_center_x',88)
    linear(symbols,arcs[3],0,(87,-4),arcs[5],0,(0,0),False,'bottom_center_y',4)
    linear(symbols,arcs[2],0,(bx,by),arcs[5],0,(0,0),False,'notch_center_y',6.5)
    linear(symbols,arcs[1],0,(ax,ay),arcs[2],0,(bx,by),True,'centers_spacing',22.5)
    dim = require(symbols.GetAngleDimensions().Add(c.ksDrADimension), 'Angle dimension')
    # Base objects retain native association with the horizontal and sloping runs.
    dim.SetBaseObject1(l0); dim.SetBaseObject2(l1)
    ix = ax + (ay+9)/math.tan(angle)
    dim.SetXc(ix); dim.SetYc(-9)
    dim.SetAngle1(180); dim.SetAngle2(168)
    dim.SetRadius(15); dim.SetDimensionType(c.ksADMinAngle)
    require(dim.Update(), 'Angle Update')
    # Keep the native 12-degree driving dimension; the variable-value setter
    # applies inconsistent angular conversion in this Linux binding.
    con(dim,c.ksCFixedDim)
    return [obj.GetId() for obj in arcs], [obj.GetId() for obj in (l0,l1,l2,l3)]


def inspect_profile(sketch, ids):
    fragment = require(sketch.BeginEdit(False), 'Inspect profile')
    try:
        arc_data=[]
        for oid in ids[0]:
            obj=ksapi.IArc(fragment.GetObjectById(oid))
            arc_data.append(dict(center=[obj.GetXc(),obj.GetYc()],radius=obj.GetRadius(),angles=[obj.GetAngle1(),obj.GetAngle2()]))
        line_data=[]
        for oid in ids[1]:
            obj=ksapi.ILineSegment(fragment.GetObjectById(oid))
            line_data.append([obj.GetX1(),obj.GetY1(),obj.GetX2(),obj.GetY2()])
        stage('actual profile',arcs=arc_data,lines=line_data)
    finally:
        require(sketch.EndEdit(),'Inspect EndEdit')


def extrusion(model, sketch, name, normal_depth, reverse_depth, thin=False):
    op = require(model.GetExtrusions().Add(c3d.o3d_bossExtrusion),'Extrusion')
    op.SetName(name); op.SetProfiles([sketch]); op.SetDirection(c3d.dtBoth)
    require(op.SetSideParameters(True,c3d.etBlind,normal_depth,0,False,None),'Normal depth')
    require(op.SetSideParameters(False,c3d.etBlind,reverse_depth,0,False,None),'Reverse depth')
    if thin:
        params = require(ksapi.IThinParameters(op),'IThinParameters')
        require(params.SetThinParameters(True,c3d.dtReverse,0,1),'Constant rim 1 mm')
    require(op.Update(), name)
    return op


def errors(part):
    bad, seen = [], set()
    def visit(f):
        if f.reference in seen:
            return
        seen.add(f.reference)
        if f.GetObjectError():
            bad.append((f.GetName(),f.GetObjectError()))
        for child in f.GetSubFeatures(c.ksOperTree,True,True):
            if child:
                visit(child)
    visit(ksapi.IFeature(part))
    require(not bad,f'Operation errors: {bad}')
    CHECKS.append('Нативное дерево проверено: ошибок операций нет.')


def main():
    attempt = Path(tempfile.mkdtemp(prefix='attempt-',dir=ROOT))
    output = attempt/'model.m3d'
    require(not output.exists() and not output.is_symlink(),'Output exists')
    result = dict(task='2.2',status='failed',title='Practice Problem 2.2 — constant edge bracket',
                  script='solution.py',model=None,volume_mm3=None,reference_volume=13031,
                  reference_units='mm3',volume_passed=False,checks=CHECKS,limitations=LIMITATIONS,
                  tree='Эскиз внешнего профиля → стенка 9 мм → край 1 мм, высота 11 мм → Ø9.5 сквозной')
    doc = None
    try:
        app = require(ksapi.GetKompas(),'Нет запущенной API-сессии КОМПАС; запуск запрещён.')
        doc = require(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart,True),'Own part')
        part = require(ksapi.IKompasDocument3D(doc).GetTopPart(),'Top part')
        part.SetName('Practice Problem 2.2')
        model = require(part.GetModelContainer(),'Model')
        with edit(part,model,'Наружный контур 101 × 18; R2.5 R5 R4; 12°') as (sketch,drawing,symbols):
            ids = profile(drawing,symbols)
        inspect_profile(sketch,ids)
        stage('base extrusion')
        extrusion(model,sketch,'Средняя стенка 9 мм',4.5,4.5)
        stage('constant rim')
        extrusion(model,sketch,'Постоянный край 1 мм, общая толщина 11 мм',5.5,5.5,True)
        with edit(part,model,'Отверстие Ø9.5 в начале координат') as (hole,drawing,symbols):
            circle = require(drawing.GetCircles().Add(),'Circle')
            circle.SetXc(0); circle.SetYc(0); circle.SetRadius(4.75)
            require(circle.Update(),'Circle Update')
            con(circle,c.ksCFixedPoint,index=0)
            radial(symbols,circle,(0,0),4.75,'hole_radius')
        cut = require(model.GetExtrusions().Add(c3d.o3d_cutExtrusion),'Hole cut')
        cut.SetName('Ø9.5 сквозное отверстие'); cut.SetProfiles([hole]); cut.SetDirection(c3d.dtBoth)
        require(cut.SetSideParameters(True,c3d.etBlind,5.5,0,False,None),'Hole normal')
        require(cut.SetSideParameters(False,c3d.etBlind,5.5,0,False,None),'Hole reverse')
        require(cut.Update(),'Hole Update')
        require(part.RebuildModel(True),'Rebuild')
        bodies = ksapi.IFeature(part).GetResultBodies()
        require(len(bodies)==1 and bodies[0].IsSolid(),'Single solid')
        CHECKS.append('Построено одно твёрдое тело; начало в центре отверстия и средней плоскости толщины.')
        errors(part)
        mass = require(ksapi.IMassInertiaParam(part),'Mass properties')
        mass.SetLengthUnits(c.ksLUnMM)
        require(mass.GetLengthUnits()==1,'Mass unit readback must be 1')
        require(mass.Calculate() and mass.IsActual(),'Actual mass properties')
        volume = mass.GetVolume()
        require(math.isfinite(volume) and volume>0,'Positive volume')
        result['volume_mm3'] = volume
        result['volume_passed'] = 13030.5 <= volume < 13031.5
        CHECKS.append(f'IMassInertiaParam: SetLengthUnits(ksLUnMM), GetLengthUnits=1; объём {volume:.9f} мм³.')
        CHECKS.append(f'Интервал [13030.5,13031.5): {result["volume_passed"]}.')
        require(not output.exists() and not output.is_symlink(),'SaveAs path exists')
        require(doc.SaveAs(str(output)),'SaveAs')
        require(output.is_file() and output.stat().st_size>0,'Saved nonempty model')
        result['model'] = str(output.relative_to(ROOT))
        CHECKS.append('SaveAs в отсутствующий путь выполнен; нативный model.m3d существует и непуст.')
        if not result['volume_passed']:
            LIMITATIONS.append('Объём не попал в интервал эталона; геометрия не подгонялась под объём.')
        result['status'] = 'passed' if result['volume_passed'] and not LIMITATIONS else 'partial'
    except Exception as exc:
        LIMITATIONS.append(f'{type(exc).__name__}: {exc}')
        stage('failure',error=traceback.format_exc())
    finally:
        if doc:
            try:
                require(doc.Close(c.kdDoNotSaveChanges),'Close own part')
                CHECKS.append('Собственный документ закрыт в finally; чужие документы не изменялись.')
            except Exception as exc:
                LIMITATIONS.append(f'Закрытие собственного документа: {exc}')
                result['status']='partial' if result['model'] else 'failed'
        (ROOT/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        stage('result',**result)


if __name__=='__main__':
    main()
