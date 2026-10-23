# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Practice Problem 2.3, native KOMPAS-3D Linux; attach only, no exports."""
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
R, BORE, EAR, HOLE, PITCH = 52.5, 40.5, 23.665, 11.665, 87.5
CHECKS = []
STATES = []
FEATURES = []


def req(value, message):
    if not value:
        raise RuntimeError(message)
    return value


def relation(obj, kind, partner=None, index=None, partner_index=None, name=None, value=None):
    item = req(obj.NewConstraint(), 'NewConstraint')
    item.SetConstraintType(kind)
    if partner is not None:
        item.SetPartners([partner])
    if index is not None:
        item.SetIndex(index)
    if partner_index is not None:
        item.SetPartnerIndex(partner_index)
    if name is not None:
        item.SetVariable(name)
    if value is not None:
        item.SetConstraintValue(value)
    req(item.Create() and item.IsValid(), f'Constraint {kind}, {name}')
    return item


def drive(dim, name, value):
    relation(dim, c.ksCFixedDim)
    relation(dim, c.ksCDimWithVariable, name=name, value=value)


def radial(symbols, obj, value, name):
    dim = req(symbols.GetRadialDimensions().Add(), 'Radial dimension')
    dim.SetBaseObject(obj)
    dim.SetXc(obj.GetXc())
    dim.SetYc(obj.GetYc())
    dim.SetRadius(value)
    dim.SetAngle(35.)
    req(dim.Update(), 'Radial dimension Update')
    drive(dim, name, value)


def distance(symbols, p, q, horizontal, name):
    # p/q are (object, native point index, x, y).
    dim = req(symbols.GetLineDimensions().Add(), 'Linear dimension')
    dim.SetX1(p[2]); dim.SetY1(p[3])
    dim.SetX2(q[2]); dim.SetY2(q[3])
    dim.SetX3((p[2]+q[2])/2 + (0 if horizontal else 15))
    dim.SetY3((p[3]+q[3])/2 + (-15 if horizontal else 0))
    dim.SetOrientation(c.ksLinDHorizontal if horizontal else c.ksLinDVertical)
    req(dim.Update(), 'Linear dimension Update')
    req(dim.Associate(), 'Associate dimension')
    # Several pocket arcs share the minimally fixed datum centre (0,0).
    # Association to either coincident centre is geometrically equivalent.
    links=dim.GetConstraints()
    for i in (0,1):
        req(any(x.IsValid() and x.GetConstraintType()==c.ksCMergePoints
                and x.GetIndex()==i for x in links),f'Witness link {name}/{i}')
    drive(dim, name, abs(q[2]-p[2]) if horizontal else abs(q[3]-p[3]))


def circle(drawing, xy, radius, construction=False):
    obj=req(drawing.GetCircles().Add(), 'Circle')
    obj.SetXc(xy[0]); obj.SetYc(xy[1]); obj.SetRadius(radius)
    if construction:
        obj.SetStyle(0)
    req(obj.Update(), 'Circle Update')
    return obj


def arc(drawing, center, radius, start, end, clockwise=False):
    obj=req(drawing.GetArcs().Add(), 'Arc')
    obj.SetXc(center[0]); obj.SetYc(center[1]); obj.SetRadius(radius)
    obj.SetAngle1(math.degrees(math.atan2(start[1]-center[1],start[0]-center[0]))%360)
    obj.SetAngle2(math.degrees(math.atan2(end[1]-center[1],end[0]-center[0]))%360)
    obj.SetDirection(clockwise)
    req(obj.Update(), 'Arc Update')
    return obj


def line(drawing, p, q):
    obj=req(drawing.GetLineSegments().Add(), 'Line')
    obj.SetX1(p[0]); obj.SetY1(p[1]); obj.SetX2(q[0]); obj.SetY2(q[1])
    req(obj.Update(), 'Line Update')
    return obj


def merge(a, ai, b, bi):
    relation(a,c.ksCMergePoints,b,ai,bi)


def tangent(a,b):
    relation(a,c.ksCTangentTwoCurves,b)


def locate_ear(symbols, origin, ear, x, name):
    relation(ear,c.ksCHAlignPoints,origin,0,0)
    distance(symbols,(origin,0,0,0),(ear,0,x,0),True,name)


@contextmanager
def sketch(part, model, title, z=0):
    plane=req(part.GetDefaultObject(c3d.o3d_planeXOY),'XOY')
    if z:
        geom=req(ksapi.IAuxiliaryGeomContainer(part),'Auxiliary geometry')
        plane=req(geom.GetPlanes3D().Add(c3d.o3d_planeOffset),'Offset plane')
        offset=ksapi.IPlane3DByOffset(plane)
        offset.SetBasePlane(part.GetDefaultObject(c3d.o3d_planeXOY))
        offset.SetOffset(z); offset.SetDirection(True)
        req(offset.Update(),'Offset plane Update')
    obj=req(model.GetSketchs().Add(),'Sketch')
    obj.SetName(title); obj.SetPlane(plane)
    req(obj.Update(),'Sketch Update')
    fragment=req(obj.BeginEdit(False),'BeginEdit')
    try:
        fragment.SetParametricMode(True)
        req(fragment.IsParametricMode(),'Parametric mode')
        view=req(fragment.GetViewsAndLayersManager().GetViews().GetActiveView(),'View')
        yield obj,ksapi.IDrawingContainer(view),ksapi.ISymbols2DContainer(view)
    finally:
        req(obj.EndEdit(),'EndEdit')
    state=obj.GetConstraintsState()
    STATES.append((title,state))
    print(json.dumps({'sketch':title,'state':state}),flush=True)


def extrude(model, profile, depth, title, cut=False):
    op=req(model.GetExtrusions().Add(c3d.o3d_cutExtrusion if cut else c3d.o3d_bossExtrusion),'Extrusion')
    op.SetName(title); op.SetProfiles([profile])
    op.SetDirection(c3d.dtReverse if cut else c3d.dtNormal)
    req(op.SetSideParameters(not cut,c3d.etBlind,depth,0.,False,None),'Extrusion depth')
    req(op.Update(),f'Extrusion Update: {title}')
    req(not ksapi.IFeature(op).GetObjectError(),f'Operation error: {title}')
    FEATURES.append(title)
    return op


def build_hull(part,model):
    n=((R-EAR)/PITCH, math.sqrt(1-((R-EAR)/PITCH)**2))
    def pt(x,r,sx,sy):
        return (x+sx*r*n[0],sy*r*n[1])
    with sketch(part,model,'01 Касательное основание: Ø105; шаг 175; стенки 12') as (s,d,sym):
        top=arc(d,(0,0),R,pt(0,R,1,1),pt(0,R,-1,1))
        left=arc(d,(-PITCH,0),EAR,pt(-PITCH,EAR,-1,1),pt(-PITCH,EAR,-1,-1))
        bottom=arc(d,(0,0),R,pt(0,R,-1,-1),pt(0,R,1,-1))
        right=arc(d,(PITCH,0),EAR,pt(PITCH,EAR,1,-1),pt(PITCH,EAR,1,1))
        arcs=[top,left,bottom,right]
        relation(top,c.ksCFixedPoint,index=0)
        radial(sym,top,R,'base_radius')
        relation(bottom,c.ksCConcentricity,top)
        relation(bottom,c.ksCEqualRadius,top)
        locate_ear(sym,top,left,-PITCH,'left_half_pitch')
        locate_ear(sym,top,right,PITCH,'right_half_pitch')
        radial(sym,left,EAR,'ear_outer_radius')
        relation(right,c.ksCEqualRadius,left)
        for i,a in enumerate(arcs):
            b=arcs[(i+1)%4]
            ln=line(d,(a.GetX2(),a.GetY2()),(b.GetX1(),b.GetY1()))
            merge(a,2,ln,0); merge(ln,1,b,1)
            tangent(ln,a); tangent(ln,b)
        hole=circle(d,(0,0),BORE)
        relation(hole,c.ksCConcentricity,top); radial(sym,hole,BORE,'base_bore_radius')
        for i,a in enumerate((left,right)):
            h=circle(d,(a.GetXc(),0),HOLE)
            relation(h,c.ksCConcentricity,a)
            if i==0:
                radial(sym,h,HOLE,'mounting_hole_radius'); first=h
            else:
                relation(h,c.ksCEqualRadius,first)
    extrude(model,s,12,'02 Основание, 9 + 3 мм')


def build_bosses(part,model):
    with sketch(part,model,'03 Втулка Ø105, стенка 12') as (s,d,sym):
        outer=circle(d,(0,0),R); inner=circle(d,(0,0),BORE)
        relation(outer,c.ksCFixedPoint,index=0)
        relation(inner,c.ksCConcentricity,outer)
        radial(sym,outer,R,'hub_outer_radius'); radial(sym,inner,BORE,'hub_bore_radius')
    extrude(model,s,63,'04 Втулка, общая высота 25 + 38')
    with sketch(part,model,'05 Две проушины: 2 × Ø23.33, стенка 12') as (s,d,sym):
        origin=circle(d,(0,0),1,True)
        relation(origin,c.ksCFixedPoint,index=0); radial(sym,origin,1,'datum_radius')
        for i,x in enumerate((-PITCH,PITCH)):
            outer=circle(d,(x,0),EAR); inner=circle(d,(x,0),HOLE)
            locate_ear(sym,origin,outer,x,f'ear_pitch_{i}')
            relation(inner,c.ksCConcentricity,outer)
            if i==0:
                radial(sym,outer,EAR,'boss_radius'); radial(sym,inner,HOLE,'hole_radius')
                first_o,first_i=outer,inner
            else:
                relation(outer,c.ksCEqualRadius,first_o); relation(inner,c.ksCEqualRadius,first_i)
    extrude(model,s,25,'06 Крепёжные проушины, высота 25')


def pocket_contour(d,sym,side):
    # Pocket is inward 3 mm from the tangent outline and outward 3 mm
    # from both bosses. Four native tangent R3 corner arcs per pocket.
    n=((R-EAR)/PITCH,math.sqrt(1-((R-EAR)/PITCH)**2))
    t=(n[1],-n[0]); f=3.
    centers=[]
    for x,rad,sign in ((0,R+6,1),(PITCH,EAR+6,-1)):
        h=R-6-n[0]*x; q=math.sqrt(rad*rad-h*h)
        centers.append((x+h*n[0]+sign*q*t[0],h*n[1]+sign*q*t[1]))
    ca,cb=centers
    ta=(ca[0]+f*n[0],ca[1]+f*n[1])
    tb=(cb[0]+f*n[0],cb[1]+f*n[1])
    pa=(ca[0]*(R+3)/(R+6),ca[1]*(R+3)/(R+6))
    pb=(PITCH+(cb[0]-PITCH)*(EAR+3)/(EAR+6),cb[1]*(EAR+3)/(EAR+6))
    mirror=lambda p:(p[0],-p[1])
    transform=lambda p:(side*p[0],p[1])
    def ln(p,q): return line(d,transform(p),transform(q))
    def ar(center,r,p,q,cw): return arc(d,transform(center),r,transform(p),transform(q),cw if side==1 else not cw)
    segments=[ln(ta,tb),ar(cb,f,tb,pb,True),ar((PITCH,0),EAR+3,pb,mirror(pb),False),
              ar(mirror(cb),f,mirror(pb),mirror(tb),True),ln(mirror(tb),mirror(ta)),
              ar(mirror(ca),f,mirror(ta),mirror(pa),True),ar((0,0),R+3,mirror(pa),pa,False),ar(ca,f,pa,ta,True)]
    for i,obj in enumerate(segments):
        nxt=segments[(i+1)%8]
        merge(obj,1 if i in (0,4) else 2,nxt,0 if (i+1)%8 in (0,4) else 1)
        tangent(obj,nxt)
    large,small=segments[6],segments[2]
    tag='right' if side==1 else 'left'
    relation(large,c.ksCFixedPoint,index=0)
    locate_ear(sym,large,small,side*PITCH,f'pocket_pitch_{tag}')
    radial(sym,large,R+3,f'pocket_hub_offset_{tag}')
    radial(sym,small,EAR+3,f'pocket_ear_offset_{tag}')
    radial(sym,segments[1],f,f'corner_radius_{tag}')
    for i in (3,5,7): relation(segments[i],c.ksCEqualRadius,segments[1])
    # The inner tangent line is the common external tangent of these
    # construction circles, i.e. an exact parallel inward offset of 3.
    for base,r in ((large,R-3),(small,EAR-3)):
        aux=circle(d,(base.GetXc(),0),r,True)
        relation(aux,c.ksCConcentricity,base)
        radial(sym,aux,r,f'offset_tangent_{tag}_{int(r*1000)}')
        tangent(segments[0],aux); tangent(segments[4],aux)


def build_pockets(part,model):
    with sketch(part,model,'07 Карманы: стенки 3; 8 × R3',9) as (s,d,sym):
        pocket_contour(d,sym,1)
        pocket_contour(d,sym,-1)
    extrude(model,s,3,'08 Выемки глубиной 3, дно Z=9',True)


def errors(part):
    found=[]; seen=set()
    def visit(f):
        if f.reference in seen: return
        seen.add(f.reference)
        if f.GetObjectError(): found.append((f.GetName(),f.GetObjectError()))
        for child in f.GetSubFeatures(c.ksOperTree,True,True):
            if child: visit(child)
    visit(ksapi.IFeature(part))
    return found


def main():
    ast.parse(Path(__file__).read_text())
    CHECKS.append('ast.parse самостоятельного solution.py: passed до подключения к CAD.')
    target=Path(tempfile.mkdtemp(prefix='attempt-',dir=ROOT))/'model.m3d'
    req(not target.exists() and not target.is_symlink(),'Output must not exist')
    report={'task':'2.3','status':'failed','title':'Фланцевая втулка с двумя проушинами и облегчённым основанием',
            'script':'solution.py','model':None,'volume_mm3':None,'reference_volume':325633,
            'reference_units':'mm3','volume_passed':False,'checks':CHECKS,'limitations':[],
            'tree':'Касательное основание 12 → втулка 63 → проушины 25 → два кармана 3, 8 × R3'}
    doc=None
    try:
        app=req(ksapi.GetKompas(),'Нет запущенной API-сессии; КОМПАС не запускался.')
        doc=req(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart,True),'New owned document')
        doc3d=req(ksapi.IKompasDocument3D(doc),'3D document')
        part=req(doc3d.GetTopPart(),'Part'); part.SetName('2.3 Фланцевая втулка')
        model=req(part.GetModelContainer(),'Model container')
        build_hull(part,model); build_bosses(part,model); build_pockets(part,model)
        req(doc3d.CompleteRebuildDocument(),'CompleteRebuildDocument')
        req(part.RebuildModel(True),'RebuildModel')
        errs=errors(part); req(not errs,f'Feature errors: {errs}')
        CHECKS.append('Полное перестроение; рекурсивный GetObjectError: ошибок нет.')
        bodies=ksapi.IFeature(part).GetResultBodies()
        req(len(bodies)==1 and bodies[0].IsSolid(),'One solid')
        CHECKS.append('Конечный результат: одно твёрдое тело.')
        for title,state in STATES:
            CHECKS.append(f'Эскиз «{title}»: GetConstraintsState={state}; WellConstrained=1.')
            if state!=c.ksStateWellConstrained:
                report['limitations'].append(f'Эскиз «{title}» не полностью определён: состояние {state}.')
        mass=req(ksapi.IMassInertiaParam(bodies[0]),'Mass inertia')
        mass.SetLengthUnits(c.ksLUnMM)
        req(mass.GetLengthUnits()==1,'Mass units readback must be 1')
        req(mass.Calculate(),'Calculate mass properties')
        req(mass.GetLengthUnits()==1,'Mass units after Calculate')
        volume=mass.GetVolume(); req(math.isfinite(volume) and volume>0,'Finite positive volume')
        report['volume_mm3']=volume
        report['volume_passed']=325632.5<=volume<325633.5
        CHECKS.append(f'IMassInertiaParam.SetLengthUnits(ksLUnMM); GetLengthUnits=1 до/после Calculate; V={volume:.9f} мм³.')
        CHECKS.append(f'Эталонный интервал [325632.5,325633.5): {report["volume_passed"]}. Геометрия под объём не подгонялась.')
        if not report['volume_passed']:
            report['limitations'].append('Объём не попал в интервал округления эталона; размеры не подгонялись.')
        req(not target.exists() and not target.is_symlink(),'SaveAs path must not exist')
        req(doc.SaveAs(str(target)),'SaveAs')
        req(target.is_file() and target.stat().st_size>0,'Saved nonempty model')
        req(Path(doc.GetFullPath()).resolve()==target,'Saved path readback')
        report['model']=str(target.relative_to(ROOT))
        CHECKS.append('SaveAs выполнен в отсутствующий attempt-*/model.m3d; непустой файл и GetFullPath подтверждены.')
        report['status']='passed' if report['volume_passed'] and not report['limitations'] else 'partial'
    except Exception as exc:
        report['limitations'].append(f'{type(exc).__name__}: {exc}')
        traceback.print_exc()
    finally:
        if doc is not None:
            try:
                req(doc.Close(c.kdDoNotSaveChanges),'Close owned document')
                CHECKS.append('Собственный документ закрыт в finally; чужие документы не изменялись и не закрывались.')
            except Exception as exc:
                report['limitations'].append(f'Закрытие собственного документа: {exc}')
                report['status']='partial' if report['model'] else 'failed'
        (ROOT/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
