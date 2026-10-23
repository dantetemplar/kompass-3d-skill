# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Practice 2.5: native, dimension-constrained bracket; attach only."""
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
T = math.radians(25)
L = 78 / math.cos(T)
H = 33 + 78 * math.tan(T)
CHECKS = []
STATES = []


def req(x, msg):
    if not x:
        raise RuntimeError(msg)
    return x


def con(obj, kind, partner=None, index=None, pi=None, name=None, value=None):
    q = req(obj.NewConstraint(), 'NewConstraint')
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
    req(q.Create() and q.IsValid(), f'Constraint {kind}, {name}')
    return q


def driving(d, name, value):
    con(d, c.ksCFixedDim)
    con(d, c.ksCDimWithVariable, name=name, value=value)
    return d


def dim(sym, a, ia, pa, b, ib, pb, vertical, name, value):
    q = req(sym.GetLineDimensions().Add(), 'Dimension')
    q.SetX1(pa[0]); q.SetY1(pa[1]); q.SetX2(pb[0]); q.SetY2(pb[1])
    q.SetX3((pa[0]+pb[0])/2 + (-8 if vertical else 0))
    q.SetY3((pa[1]+pb[1])/2 + (0 if vertical else -8))
    q.SetOrientation(c.ksLinDVertical if vertical else c.ksLinDHorizontal)
    req(q.Update(), 'Dimension Update')
    req(q.Associate(), 'Dimension Associate '+name)
    for i, obj, ix in [(0,a,ia),(1,b,ib)]:
        req(any(z.IsValid() and z.GetConstraintType()==c.ksCMergePoints and z.GetIndex()==i and z.GetPartnerIndex()==ix and any(p.GetId()==obj.GetId() for p in z.GetPartners()) for z in q.GetConstraints()), 'Dimension witnesses '+name)
    return driving(q,name,value)


def radial(sym, obj, center, r, name):
    q=req(sym.GetRadialDimensions().Add(),'Radial')
    q.SetBaseObject(obj); q.SetXc(center[0]); q.SetYc(center[1]); q.SetRadius(r); q.SetAngle(45)
    req(q.Update(),'Radial update')
    return driving(q,name,r)


def line(d,p,q,style=1):
    a=req(d.GetLineSegments().Add(),'Line')
    a.SetX1(p[0]);a.SetY1(p[1]);a.SetX2(q[0]);a.SetY2(q[1]);a.SetStyle(style)
    req(a.Update(),'Line update')
    return a


def circle(d,p,r,style=1):
    a=req(d.GetCircles().Add(),'Circle')
    a.SetXc(p[0]);a.SetYc(p[1]);a.SetRadius(r);a.SetStyle(style)
    req(a.Update(),'Circle update')
    return a


def axes(s):
    out=[s.GetPoint3D(u,v,0,0,0) for u,v in [(0,0),(1,0),(0,1)]]
    req(all(p[0] for p in out),'Sketch coordinate readback')
    o=out[0][1:];u=tuple(out[1][i+1]-o[i] for i in range(3));v=tuple(out[2][i+1]-o[i] for i in range(3))
    n=(u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0])
    print(json.dumps({'sketch':s.GetName(),'origin':o,'u':u,'v':v,'normal':n}),flush=True)
    return o,u,v,n


def project(s,p):
    q=s.GetPointProjectionToXY(*p,0,0)
    req(q[0],'Sketch inverse projection')
    return tuple(q[1:])


def sketch(model,plane,name,origin=None,u=None):
    s=req(model.GetSketchs().Add(),'Sketch')
    s.SetName(name);s.SetPlane(plane);req(s.Update(),'Sketch support')
    o,ux,vy,n=axes(s)
    if u is not None:
        a=sum(u[i]*ux[i] for i in range(3)); b=sum(u[i]*vy[i] for i in range(3))
        s.SetAngle(math.degrees(math.atan2(b,a)));req(s.Update(),'Orient sketch')
    if origin is not None:
        xy=project(s,origin);req(s.SetLocation(*xy),'Sketch location');req(s.Update(),'Locate sketch')
    axes(s)
    return s


@contextmanager
def edit(s):
    f=req(s.BeginEdit(False),'BeginEdit')
    try:
        f.SetParametricMode(True)
        v=req(f.GetViewsAndLayersManager().GetViews().GetActiveView(),'View')
        yield ksapi.IDrawingContainer(v),ksapi.ISymbols2DContainer(v)
    finally:
        req(s.EndEdit(),'EndEdit')
    state=s.GetConstraintsState();STATES.append((s.GetName(),state))
    print('STATE',s.GetName(),state,flush=True)
    req(state==c.ksStateWellConstrained,'Underdefined sketch '+s.GetName()+': '+str(state))


def polygon(d,sym,pts,name):
    ls=[line(d,a,b) for a,b in zip(pts,pts[1:]+pts[:1])]
    for i,a in enumerate(ls):
        con(a,c.ksCMergePoints,ls[(i+1)%len(ls)],1,0)
        p,q=pts[i],pts[(i+1)%len(pts)]
        if abs(p[0]-q[0])<1e-7:con(a,c.ksCVertical)
        elif abs(p[1]-q[1])<1e-7:con(a,c.ksCHorizontal)
    con(ls[0],c.ksCFixedPoint,index=0)
    return ls


def rectangle(d,sym,w,h,name):
    pts=[(0,0),(w,0),(w,h),(0,h)]
    ls=polygon(d,sym,pts,name)
    dim(sym,ls[0],0,pts[0],ls[0],1,pts[1],False,name+'_width',w)
    dim(sym,ls[1],0,pts[1],ls[1],1,pts[2],True,name+'_depth',h)
    return ls


def extrude(model,s,depth,name,reverse=False,cut=False):
    q=req(model.GetExtrusions().Add(c3d.o3d_cutExtrusion if cut else c3d.o3d_bossExtrusion),'Extrusion')
    q.SetName(name);q.SetProfiles([s]);q.SetDirection(c3d.dtReverse if reverse else c3d.dtNormal)
    req(q.SetSideParameters(not reverse,c3d.etBlind,depth,0.,False,None),'Extrusion parameters')
    req(q.Update(),'Extrusion update '+name)
    req(not ksapi.IFeature(q).GetObjectError(),'Operation error '+name)
    print('OPERATION',name,'OK',flush=True)
    return q


def face_at(part,point,normal):
    found=[]
    for o in ksapi.IFeature(part).GetModelObjects([c3d.o3d_face]):
        f=ksapi.IFace(o)
        if not f.IsPlanar():continue
        pl=f.GetMathSurface().GetPlacement()
        p=pl.GetOrigin(0,0,0);n=pl.GetVector(c3d.o3d_axisOZ,0,0,0)
        req(p[0] and n[0],'Face placement')
        if abs(abs(sum(n[i+1]*normal[i] for i in range(3)))-1)<1e-6 and abs(sum((point[i]-p[i+1])*n[i+1] for i in range(3)))<1e-5:
            found.append(o)
    req(len(found)==1,f'Unique support face: {len(found)}')
    return found[0]


def build(part,model):
    # World origin is the red lower-front-left base corner; X = 78 width,
    # Y = base depth 41, Z up. Wall front Y34, back Y41.
    s=sketch(model,part.GetDefaultObject(c3d.o3d_planeXOY),'01 Основание 78×41')
    with edit(s) as (d,sym):rectangle(d,sym,78,41,'base')
    extrude(model,s,7,'01 Основание t7')
    wallplane=face_at(part,(0,41,0),(0,1,0))
    s=sketch(model,wallplane,'02 Стенка 78;33;25°',(0,41,0),(1,0,0))
    pts=[project(s,p) for p in [(0,41,7),(78,41,7),(78,41,33),(0,41,H)]]
    with edit(s) as (d,sym):
        ls=polygon(d,sym,pts,'wall')
        dim(sym,ls[0],0,pts[0],ls[0],1,pts[1],False,'wall_width',78)
        dim(sym,ls[1],0,pts[1],ls[1],1,pts[2],True,'wall_above_base',26)
        # Native angular driving dimension between horizontal bottom and slope.
        a=req(sym.GetAngleDimensions().Add(c.ksDrADimension),'Angular dimension')
        a.SetBaseObject1(ls[0]);a.SetBaseObject2(ls[2]);a.SetXc((H-7)/math.tan(T))
        a.SetYc(-7);a.SetRadius(70);a.SetAngle1(180);a.SetAngle2(205);a.SetDimensionType(c.ksADMinAngle)
        req(a.Update(),'Angular update')
        con(a,c.ksCFixedDim)
        q=req(a.NewConstraint(),'Angle variable');q.SetConstraintType(c.ksCDimWithVariable);q.SetVariable('wall_slope');q.SetDegrees(25);q.SetMinutes(0);q.SetSeconds(0)
        req(q.Create() and q.IsValid(),'Angle variable create')
    n=axes(s)[3]
    extrude(model,s,7,'02 Наклонная стенка t7',reverse=n[1]>0)
    slope_n=(math.sin(T),0,math.cos(T))
    face=face_at(part,(39,37.5,33+39*math.tan(T)),slope_n)
    # Flange drawn on the existing angled face and extruded INTO the wall.
    origin=(10*math.cos(T),34,H-10*math.sin(T))
    s=sketch(model,face,'03 Полка на наклонной грани',origin,(math.cos(T),0,-math.sin(T)))
    v=axes(s)[2]
    sign=1 if v[1]>0 else -1
    with edit(s) as (d,sym):rectangle(d,sym,L-20,sign*45,'flange')
    n=axes(s)[3]
    extrude(model,s,7,'03 Полка t7 внутрь',reverse=sum(n[i]*slope_n[i] for i in range(3))>0)
    # Rib on left side, from base top Z7 to Z32 at the wall.
    face=face_at(part,(0,10,3.5),(1,0,0))
    s=sketch(model,face,'04 Ребро 34×25',(0,0,7),(0,1,0))
    pts=[project(s,p) for p in [(0,0,7),(0,34,7),(0,34,32)]]
    with edit(s) as (d,sym):
        ls=polygon(d,sym,pts,'rib')
        dim(sym,ls[0],0,pts[0],ls[0],1,pts[1],False,'rib_run',34)
        dim(sym,ls[1],0,pts[1],ls[1],1,pts[2],True,'rib_rise',25)
    n=axes(s)[3];extrude(model,s,7,'04 Ребро t7',reverse=n[0]<0)
    s=sketch(model,part.GetDefaultObject(c3d.o3d_planeXOY),'05 Крепёжные отверстия Ø10')
    with edit(s) as (d,sym):
        datum=circle(d,(0,0),1,3);con(datum,c.ksCFixedPoint,index=0);radial(sym,datum,(0,0),1,'datum_radius')
        holes=[]
        for i,x in enumerate([20,58]):
            a=circle(d,(x,12),5);holes.append(a)
            dim(sym,datum,0,(0,0),a,0,(x,12),False,f'hole_x_{i}',x)
            dim(sym,datum,0,(0,0),a,0,(x,12),True,f'hole_y_{i}',12)
        radial(sym,holes[0],(20,12),5,'mount_radius');con(holes[1],c.ksCEqualRadius,holes[0])
    extrude(model,s,7,'05 Два сквозных Ø10',reverse=True,cut=True)
    # Keyhole = small semicircle R4, two tangent lines, and large circle R9.
    # Two separate native cuts represent its exact union without intersecting contours.
    face=face_at(part,(39,60,H-39*math.tan(T)),slope_n)
    slot_origin=((L-60)*math.cos(T),59,H-(L-60)*math.sin(T))
    s=sketch(model,face,'06 Узкий паз 8; межцентровое30',slot_origin,(math.cos(T),0,-math.sin(T)))
    with edit(s) as (d,sym):
        # Four native entities form a stadium. Arc indices: center0,start1,end2.
        top=line(d,(0,4),(30,4));right=req(d.GetArcs().Add(),'Arc');right.SetXc(30);right.SetYc(0);right.SetRadius(4);right.SetAngle1(270);right.SetAngle2(90);right.SetDirection(False);req(right.Update(),'Arc update')
        bot=line(d,(30,-4),(0,-4));left=req(d.GetArcs().Add(),'Arc');left.SetXc(0);left.SetYc(0);left.SetRadius(4);left.SetAngle1(90);left.SetAngle2(270);left.SetDirection(False);req(left.Update(),'Arc update')
        con(top,c.ksCMergePoints,right,1,2);con(right,c.ksCMergePoints,bot,1,0);con(bot,c.ksCMergePoints,left,1,2);con(left,c.ksCMergePoints,top,1,0)
        con(top,c.ksCHorizontal);con(bot,c.ksCHorizontal)
        con(left,c.ksCTangentTwoCurves,top);con(left,c.ksCTangentTwoCurves,bot);con(right,c.ksCTangentTwoCurves,top);con(right,c.ksCTangentTwoCurves,bot)
        con(left,c.ksCFixedPoint,index=0)
        radial(sym,left,(0,0),4,'slot_radius')
        dim(sym,left,0,(0,0),right,0,(30,0),False,'slot_centres',30)
    n=axes(s)[3];rev=sum(n[i]*slope_n[i] for i in range(3))<0
    # Cut convention is opposite to a boss: use normal for material in -normal.
    extrude(model,s,7,'06 Сквозной паз ширина8',reverse=rev,cut=True)
    face=face_at(part,(39,65,H-39*math.tan(T)),slope_n)
    large=((L-30)*math.cos(T),59,H-(L-30)*math.sin(T))
    s=sketch(model,face,'07 Замочное отверстие Ø18',large,(math.cos(T),0,-math.sin(T)))
    with edit(s) as (d,sym):
        a=circle(d,(0,0),9);con(a,c.ksCFixedPoint,index=0);radial(sym,a,(0,0),9,'key_radius')
    n=axes(s)[3];extrude(model,s,7,'07 Сквозное Ø18',reverse=sum(n[i]*slope_n[i] for i in range(3))<0,cut=True)


def errors(part):
    seen=set();out=[]
    def walk(f):
        if f.reference in seen:return
        seen.add(f.reference)
        if f.GetObjectError():out.append((f.GetName(),f.GetObjectError()))
        for child in f.GetSubFeatures(c.ksOperTree,True,True):
            if child:walk(child)
    walk(ksapi.IFeature(part));return out


def main():
    attempt=Path(tempfile.mkdtemp(prefix='attempt-',dir=ROOT));output=attempt/'model.m3d'
    req(not output.exists(),'Fresh output')
    result={'task':'2.5','status':'failed','title':'SOLIDWORKS Practice Problem 2.5 — кронштейн','script':'solution.py','model':None,'volume_mm3':None,'reference_volume':62810,'reference_units':'mm3','volume_passed':False,'checks':CHECKS,'limitations':['Проверки изменения размеров и повторного открытия не выполнялись по условию.'],'tree':'Основание → наклонная стенка → полка на наклонной грани → ребро → 2×Ø10 → паз8 → Ø18'}
    doc=None
    try:
        app=req(ksapi.GetKompas(),'Existing API session unavailable; not launching KOMPAS')
        doc=req(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart,True),'Own part')
        part=req(ksapi.IKompasDocument3D(doc).GetTopPart(),'Part');part.SetName('Practice Problem 2.5')
        build(part,req(part.GetModelContainer(),'Model'))
        req(part.RebuildModel(True),'Final rebuild')
        err=errors(part);req(not err,'Feature errors '+str(err));CHECKS.append('Все операции перестроены; ошибок в нативном дереве нет.')
        CHECKS.append('Все 7 эскизов полностью определены нативными геометрическими связями и управляющими размерами; тотальная фиксация не использована.')
        bodies=ksapi.IFeature(part).GetResultBodies();req(len(bodies)==1 and bodies[0].IsSolid(),'One solid');CHECKS.append('Одно твёрдое тело.')
        mass=req(ksapi.IMassInertiaParam(part),'Mass parameters');mass.SetLengthUnits(c.ksLUnMM);req(mass.GetLengthUnits()==1,'Length units readback');req(mass.Calculate(),'Mass calculation')
        volume=mass.GetVolume();req(math.isfinite(volume) and volume>0,'Positive volume')
        result['volume_mm3']=volume;result['volume_passed']=62809.5<=volume<62810.5
        CHECKS.append('IMassInertiaParam.SetLengthUnits(ksLUnMM); GetLengthUnits=1; объём рассчитан в мм³.')
        CHECKS.append(f'Объём {volume:.9f} мм³; интервал [62809.5,62810.5): {result["volume_passed"]}.')
        req(not output.exists() and not output.is_symlink(),'Output still absent');req(doc.SaveAs(str(output)),'SaveAs')
        req(output.is_file() and output.stat().st_size>0,'Saved file');req(Path(doc.GetFullPath()).resolve()==output,'Saved path')
        result['model']=str(output.relative_to(ROOT));CHECKS.append('Нативный model.m3d сохранён в новый отсутствовавший путь; файл непустой.')
        result['status']='passed' if result['volume_passed'] else 'partial'
    except Exception as exc:
        result['limitations'].append(str(exc));print(traceback.format_exc(),flush=True)
        if doc is None:result['status']='blocked'
    finally:
        if doc is not None:
            try:
                req(doc.Close(c.kdDoNotSaveChanges),'Close own document');CHECKS.append('Собственный документ закрыт finally; чужие документы не изменены.')
            except Exception as exc:
                result['limitations'].append('Закрытие: '+str(exc));result['status']='partial' if result['model'] else 'failed'
        (ROOT/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
