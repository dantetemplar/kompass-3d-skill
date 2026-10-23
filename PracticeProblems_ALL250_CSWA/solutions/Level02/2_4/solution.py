# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Practice Problem 2.4, native KOMPAS Linux model; attach only."""
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
LIMITATIONS = []


def req(value, message):
    if not value:
        raise RuntimeError(message)
    return value


def log(message):
    print(message, flush=True)


def con(obj, kind, partner=None, index=None, other=None, name=None, value=None):
    if partner is not None and kind==c.ksCMergePoints:
        for old in obj.GetConstraints():
            if old.IsValid() and old.GetConstraintType()==kind and old.GetIndex()==index and old.GetPartnerIndex()==other and any(p.GetId()==partner.GetId() for p in old.GetPartners()):
                return old
    item = req(obj.NewConstraint(), 'NewConstraint')
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
    req(item.Create(), f'Constraint type={kind}, name={name}')
    req(item.IsValid(), f'Invalid constraint: kind={kind}, index={index}, partner_index={other}, name={name}')
    return item


def drive(dim, name, value):
    con(dim, c.ksCFixedDim)
    con(dim, c.ksCDimWithVariable, name=name, value=value)
    return dim


def radial(sym, obj, radius, name):
    dim = req(sym.GetRadialDimensions().Add(), 'Radial dimension')
    dim.SetBaseObject(obj)
    dim.SetXc(obj.GetXc())
    dim.SetYc(obj.GetYc())
    dim.SetRadius(radius)
    dim.SetAngle(35.)
    req(dim.Update(), 'Radial dimension Update')
    req(any(x.IsValid() and x.GetConstraintType() == c.ksCAssociation for x in dim.GetConstraints()), 'Radial association')
    return drive(dim, name, radius)


def linear(sym, a, ia, b, ib, p, q, horizontal, value, name):
    dim = req(sym.GetLineDimensions().Add(), 'Linear dimension')
    dim.SetX1(p[0]); dim.SetY1(p[1])
    dim.SetX2(q[0]); dim.SetY2(q[1])
    dim.SetX3((p[0]+q[0])/2+10); dim.SetY3((p[1]+q[1])/2+10)
    dim.SetOrientation(c.ksLinDHorizontal if horizontal else c.ksLinDVertical)
    req(dim.Update(), 'Linear dimension Update')
    req(dim.Associate(), 'Linear Associate')
    for i, obj, idx in [(0,a,ia),(1,b,ib)]:
        req(any(x.IsValid() and x.GetConstraintType()==c.ksCMergePoints and x.GetIndex()==i and x.GetPartnerIndex()==idx and any(z.GetId()==obj.GetId() for z in x.GetPartners()) for x in dim.GetConstraints()), f'Witness {name}/{i}')
    return drive(dim, name, value)


@contextmanager
def sketch(part, model, name, plane):
    sk = req(model.GetSketchs().Add(), 'Sketch Add')
    sk.SetName(name); sk.SetPlane(plane)
    req(sk.Update(), 'Sketch plane Update')
    frag = req(sk.BeginEdit(False), 'BeginEdit')
    try:
        frag.SetParametricMode(True)
        req(frag.IsParametricMode(), 'Parametric mode')
        view = req(frag.GetViewsAndLayersManager().GetViews().GetActiveView(), 'Sketch view')
        yield sk, req(ksapi.IDrawingContainer(view), 'Drawing container'), req(ksapi.ISymbols2DContainer(view), 'Symbols')
    finally:
        req(sk.EndEdit(), 'EndEdit')
    state = sk.GetConstraintsState()
    STATES.append((name,state))
    log(f'Sketch {name}: state={state}')
    CHECKS.append(f'Эскиз «{name}»: состояние связей {state}; fully defined={c.ksStateWellConstrained}.')


def circle(d, p, r, construction=False):
    obj = req(d.GetCircles().Add(), 'Circle')
    obj.SetXc(p[0]); obj.SetYc(p[1]); obj.SetRadius(r)
    if construction:
        obj.SetStyle(c.ksCSConstruction)
    req(obj.Update(), 'Circle Update')
    return obj


def line(d, p, q):
    obj = req(d.GetLineSegments().Add(), 'Construction line')
    obj.SetX1(p[0]); obj.SetY1(p[1]); obj.SetX2(q[0]); obj.SetY2(q[1])
    obj.SetStyle(c.ksCSConstruction)
    req(obj.Update(), 'Line Update')
    return obj


def rotate(p, angle):
    co,si=math.cos(angle),math.sin(angle)
    return (p[0]*co-p[1]*si,p[0]*si+p[1]*co)


def profile_geometry(inset):
    # Inward offset preserves tangent centres; convex radii shrink, concave grow.
    R,r,f,D=43.,15.,7.,43.
    y=((R+f)**2+D*D-(r+f)**2)/(2*D)
    x=math.sqrt((R+f)**2-y*y)
    a=math.atan2(y,x); b=math.atan2(y-D,x)
    sector=[((x,y),f+inset,a+math.pi,b+math.pi,True),
            ((0,D),r-inset,b,math.pi-b,False),
            ((-x,y),f+inset,-b,-a,True),
            ((0,0),R-inset,math.pi-a,a+math.tau/3,False)]
    return [(rotate(p,k*math.tau/3),rad,t+k*math.tau/3,u+k*math.tau/3,cw)
            for k in range(3) for p,rad,t,u,cw in sector]


def contour(d,sym,inset,prefix):
    arcs=[]
    for p,r,t,u,cw in profile_geometry(inset):
        obj=req(d.GetArcs().Add(),'Arc')
        obj.SetXc(p[0]);obj.SetYc(p[1]);obj.SetRadius(r)
        obj.SetDirection(False)
        obj.SetAngle1(math.degrees(u if cw else t)%360)
        obj.SetAngle2(math.degrees(t if cw else u)%360)
        req(obj.Update(),'Arc Update')
        arcs.append(obj)
    # Anchor the actual origin before free-network constraints can translate it.
    con(arcs[3],c.ksCFixedPoint,index=0)
    for i,obj in enumerate(arcs):
        nxt=arcs[(i+1)%12]
        # All arcs are stored CCW; concave arcs are traversed backwards.
        end_index=1 if i%4 in (0,2) else 2
        start_index=2 if (i+1)%4 in (0,2) else 1
        con(obj,c.ksCMergePoints,nxt,end_index,start_index)
        con(obj,c.ksCTangentTwoCurves,nxt)
    mains=[arcs[i] for i in (3,7,11)]
    lobes=[arcs[i] for i in (1,5,9)]
    blends=[arcs[i] for i in (0,2,4,6,8,10)]
    for group in (mains,lobes,blends):
        for obj in group[1:]:
            con(obj,c.ksCEqualRadius,group[0])
    for obj in mains[1:]:
        con(obj,c.ksCConcentricity,mains[0])
    radial(sym,mains[0],43-inset,prefix+'_main_radius')
    radial(sym,lobes[0],15-inset,prefix+'_lobe_radius')
    radial(sym,blends[0],7+inset,prefix+'_blend_radius')
    pitch=circle(d,(0,0),43,True)
    con(pitch,c.ksCConcentricity,mains[0])
    radial(sym,pitch,43,prefix+'_pitch_radius')
    for obj in lobes:
        con(obj,c.ksCPointOnCurve,pitch,index=0)
    con(lobes[0],c.ksCVAlignPoints,mains[0],0,0)
    points=[rotate((0,43),k*math.tau/3) for k in range(3)]
    con(lobes[1],c.ksCHAlignPoints,lobes[2],0,0)
    linear(sym,lobes[1],0,lobes[2],0,points[1],points[2],True,43*math.sqrt(3),prefix+'_lower_pitch')


def offset_plane(part,z):
    plane=req(ksapi.IAuxiliaryGeomContainer(part).GetPlanes3D().Add(c3d.o3d_planeOffset),'Offset plane')
    plane.SetName(f'Базовая плоскость Z={z:g}')
    p=req(ksapi.IPlane3DByOffset(plane),'IPlane3DByOffset')
    p.SetBasePlane(part.GetDefaultObject(c3d.o3d_planeXOY));p.SetOffset(z);p.SetDirection(True)
    req(p.Update(),'Offset plane Update')
    return plane


def extrude(model,sk,depth,name,cut=False):
    op=req(model.GetExtrusions().Add(c3d.o3d_cutExtrusion if cut else c3d.o3d_bossExtrusion),'Extrusion')
    op.SetName(name);op.SetProfiles([sk])
    op.SetDirection(c3d.dtReverse if cut else c3d.dtNormal)
    req(op.SetSideParameters(not cut,c3d.etBlind,depth,0.,False,None),'Extrusion depth')
    req(op.Update(),name+' Update')
    log(name+' created')
    return op


def three_circles(d,sym,r,prefix):
    # Native equilateral centre network on R43, oriented by upper centre on Y.
    datum=circle(d,(0,0),43,True)
    con(datum,c.ksCFixedPoint,index=0)
    radial(sym,datum,43,prefix+'_pitch_radius')
    points=[rotate((0,43),k*math.tau/3) for k in range(3)]
    circles=[circle(d,p,r) for p in points]
    con(circles[0],c.ksCVAlignPoints,datum,0,0)
    for obj in circles:
        con(obj,c.ksCPointOnCurve,datum,index=0)
    radial(sym,circles[0],r,prefix+'_radius')
    for obj in circles[1:]:
        con(obj,c.ksCEqualRadius,circles[0])
    con(circles[1],c.ksCHAlignPoints,circles[2],0,0)
    linear(sym,circles[1],0,circles[2],0,points[1],points[2],True,43*math.sqrt(3),prefix+'_lower_pitch')


def feature_errors(part):
    seen=set();errors=[]
    def visit(obj):
        if obj.reference in seen:
            return
        seen.add(obj.reference)
        if obj.GetObjectError():
            errors.append((obj.GetName(),obj.GetObjectError()))
        for child in obj.GetSubFeatures(c.ksOperTree,True,True):
            if child:
                visit(child)
    visit(ksapi.IFeature(part))
    return errors


def main():
    attempt=Path(tempfile.mkdtemp(prefix='attempt-',dir=ROOT))
    output=attempt/'model.m3d'
    req(not output.exists() and not output.is_symlink(),'Output already exists')
    result={'task':'2.4','status':'failed','title':'Трёхлепестковая ступенчатая крышка с бобышками',
            'script':'solution.py','model':None,'volume_mm3':None,'reference_volume':42236,
            'reference_units':'mm3','volume_passed':False,'checks':CHECKS,'limitations':LIMITATIONS,
            'tree':'Контур R43/3×R15/6×R7 → основание 3 → внутренний контур (отступ 3) → уступ 3 → 3×Ø16, высота 12 → 3×Ø11, глубина 12 → 3×Ø6, насквозь 18'}
    doc=None
    try:
        app=req(ksapi.GetKompas(),'Нет работающей API-сессии КОМПАС; запуск запрещён')
        doc=req(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart,True),'Own document')
        part=req(ksapi.IKompasDocument3D(doc).GetTopPart(),'Top part')
        part.SetName('Practice Problem 2.4 — трёхлепестковая крышка')
        model=req(part.GetModelContainer(),'Model')
        base=req(part.GetDefaultObject(c3d.o3d_planeXOY),'XOY')
        with sketch(part,model,'01 Наружный касательный контур: R43, R15, R7',base) as (sk,d,sym):
            contour(d,sym,0,'outer')
        extrude(model,sk,3,'02 Основание 3 мм')
        z3=offset_plane(part,3)
        with sketch(part,model,'03 Контур уступа: отступ 3 мм',z3) as (sk,d,sym):
            contour(d,sym,3,'inset')
        extrude(model,sk,3,'04 Уступ 3 мм')
        z6=offset_plane(part,6)
        with sketch(part,model,'05 Бобышки 3×Ø16 на R43 через 120°',z6) as (sk,d,sym):
            three_circles(d,sym,8,'boss')
        extrude(model,sk,12,'06 Бобышки до общей высоты 18 мм')
        with sketch(part,model,'07 Расточки 3×Ø11, глубина 12',base) as (sk,d,sym):
            three_circles(d,sym,5.5,'counterbore')
        extrude(model,sk,12,'08 Расточки снизу 12 мм',True)
        with sketch(part,model,'09 Отверстия 3×Ø6',base) as (sk,d,sym):
            three_circles(d,sym,3,'hole')
        extrude(model,sk,18,'10 Сквозные отверстия Ø6',True)
        req(part.RebuildModel(True),'RebuildModel')
        bodies=ksapi.IFeature(part).GetResultBodies()
        req(len(bodies)==1 and bodies[0].IsSolid(),'One solid')
        CHECKS.append('После перестроения получено одно твёрдое тело.')
        errors=feature_errors(part)
        req(not errors,f'Feature errors: {errors}')
        CHECKS.append('Рекурсивный обход нативного дерева: ошибок операций нет.')
        mass=req(ksapi.IMassInertiaParam(part),'Mass inertia')
        mass.SetLengthUnits(c.ksLUnMM)
        req(mass.GetLengthUnits()==1,'Mass units readback !=1')
        req(mass.Calculate(),'Mass Calculate')
        volume=mass.GetVolume()
        req(math.isfinite(volume) and volume>0,'Invalid volume')
        result['volume_mm3']=volume
        result['volume_passed']=42235.5<=volume<42236.5
        CHECKS.append(f'IMassInertiaParam.SetLengthUnits(ksLUnMM); GetLengthUnits=1; объём {volume:.12f} мм³.')
        CHECKS.append(f'Интервал эталона [42235.5,42236.5) мм³: {result["volume_passed"]}.')
        CHECKS.append('Начало XOY совпадает с красной меткой — центром дуг R43; базовая поверхность Z=0.')
        req(not output.exists() and not output.is_symlink(),'Output exists before SaveAs')
        req(doc.SaveAs(str(output)),'SaveAs')
        req(Path(doc.GetFullPath()).resolve()==output.resolve(),'Saved path')
        req(output.is_file() and output.stat().st_size>0,'Native file missing')
        result['model']=str(output.relative_to(ROOT))
        CHECKS.append('SaveAs в новый attempt-*/model.m3d; путь отсутствовал, сохранённый файл непустой; GetFullPath совпал.')
        under=[f'{name}: {state}' for name,state in STATES if state!=c.ksStateWellConstrained]
        if under:
            LIMITATIONS.append('Не полностью определены эскизы: '+'; '.join(under))
        result['status']='passed' if result['volume_passed'] and not under else 'partial'
        LIMITATIONS.append('Повторное открытие и испытания изменения размеров не выполнялись по условию.')
    except Exception as exc:
        LIMITATIONS.append(f'{type(exc).__name__}: {exc}')
        traceback.print_exc()
    finally:
        if doc is not None:
            try:
                req(doc.Close(c.kdDoNotSaveChanges),'Close owned document')
                CHECKS.append('Собственный документ закрыт в finally; чужие документы не изменялись и не закрывались.')
            except Exception as exc:
                result['status']='partial' if result['model'] else 'failed'
                LIMITATIONS.append(f'Закрытие собственного документа: {exc}')
        (ROOT/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    log(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    main()
