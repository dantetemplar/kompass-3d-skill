# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Practice Problem 1.13, native KOMPAS Linux; no export or reopen."""
from pathlib import Path
import json
import math
import tempfile
import traceback
import ksapi
from constants import constants as c
from constants3d import constants as c3d

ROOT = Path(__file__).resolve().parent
CHECKS = []
LIMITATIONS = [
    "Углы направлений плеч заданы нативными связями фиксированного угла; угловые размеры отдельно не созданы.",
    "Геометрия прочитана как центры концевых R5 на Ø125 под ±16°, параллельные стороны под ±20°, верхний R5 с центром на Ø40 и нижняя дуга R20 с центром в начале.",
    "Изменение размеров, повторное открытие и визуальное превью не выполнялись согласно заданию.",
]


def require(v, msg):
    if not v:
        raise RuntimeError(msg)
    return v


def relation(obj, kind, partner=None, index=None, partner_index=None, name=None, value=None):
    q = require(obj.NewConstraint(), "NewConstraint")
    q.SetConstraintType(kind)
    if partner is not None:
        q.SetPartners([partner])
    if index is not None:
        q.SetIndex(index)
    if partner_index is not None:
        q.SetPartnerIndex(partner_index)
    if name is not None:
        q.SetVariable(name)
    if value is not None:
        q.SetConstraintValue(value)
    require(q.Create() and q.IsValid(), f"Constraint {kind}/{name}")
    return q


def driving(dim, name, value):
    relation(dim, c.ksCFixedDim)
    relation(dim, c.ksCDimWithVariable, name=name, value=value)


def linear(symbols, p, q, orient, name, value):
    d = require(symbols.GetLineDimensions().Add(), "Linear dimension")
    d.SetX1(p[0]); d.SetY1(p[1]); d.SetX2(q[0]); d.SetY2(q[1])
    d.SetX3((p[0]+q[0])/2-8); d.SetY3((p[1]+q[1])/2-8)
    d.SetOrientation(orient)
    require(d.Update(), "Dimension Update")
    require(d.Associate(), "Dimension Associate")
    driving(d, name, value)


def radial(symbols, obj, center, radius, name):
    d = require(symbols.GetRadialDimensions().Add(), "Radial dimension")
    d.SetBaseObject(obj); d.SetXc(center[0]); d.SetYc(center[1])
    d.SetRadius(radius); d.SetAngle(35.)
    require(d.Update(), "Radial Update")
    driving(d, name, radius)


def add(a,b): return (a[0]+b[0],a[1]+b[1])
def sub(a,b): return (a[0]-b[0],a[1]-b[1])
def mul(a,s): return (a[0]*s,a[1]*s)
def mirror(p): return (-p[0],p[1])
def dot(a,b): return a[0]*b[0]+a[1]*b[1]


def geometry():
    # Analytic tangent-circle construction from drawing dimensions only.
    a=math.radians(16); t=math.radians(20)
    cap=(-62.5*math.cos(a),-62.5*math.sin(a))
    n=(-math.sin(t), math.cos(t)); along=(math.cos(t),math.sin(t))
    def center_on_offset(base,radius,distance,offset):
        k=dot(cap,n)+offset
        # p = base + n*s + along*u, with |p-base|=distance.
        s=k-dot(base,n)
        u=-math.sqrt(distance*distance-s*s)
        return add(base,add(mul(n,s),mul(along,u)))
    top=(0.,20.); bottom=(0.,0.)
    upper=center_on_offset(top,75,80,80)
    lower=center_on_offset(bottom,25,45,-30)
    A=add(cap,mul(n,5)); B=sub(upper,mul(n,75))
    P=add(top,mul(sub(upper,top),5/80))
    E=sub(cap,mul(n,5)); F=add(lower,mul(n,25)); G=mul(lower,20/45)
    # Tuples: line or arc, start/end, center/radius/direction.
    return [
        ('line',A,B), ('arc',B,P,upper,75.,False),
        ('arc',P,mirror(P),top,5.,True),
        ('arc',mirror(P),mirror(B),mirror(upper),75.,False),
        ('line',mirror(B),mirror(A)),
        ('arc',mirror(A),mirror(E),mirror(cap),5.,True),
        ('line',mirror(E),mirror(F)),
        ('arc',mirror(F),mirror(G),mirror(lower),25.,False),
        ('arc',mirror(G),G,bottom,20.,True),
        ('arc',G,F,lower,25.,False), ('line',F,E),
        ('arc',E,A,cap,5.,True),
    ]


def build(part, model):
    s=require(model.GetSketchs().Add(), "Sketch")
    s.SetName("01 Контур: Ø125, Ø40, Ø23, R75, R25, R5")
    s.SetPlane(require(part.GetDefaultObject(c3d.o3d_planeXOY), "XOY"))
    require(s.Update(), "Sketch plane")
    fragment=require(s.BeginEdit(False), "BeginEdit")
    try:
        fragment.SetParametricMode(True)
        view=fragment.GetViewsAndLayersManager().GetViews().GetActiveView()
        draw=ksapi.IDrawingContainer(view); symbols=ksapi.ISymbols2DContainer(view)
        specs=geometry(); objects=[]
        for spec in specs:
            p,q=spec[1:3]
            if spec[0]=='line':
                obj=draw.GetLineSegments().Add()
                obj.SetX1(p[0]); obj.SetY1(p[1]); obj.SetX2(q[0]); obj.SetY2(q[1])
            else:
                center,r,cw=spec[3:]
                obj=draw.GetArcs().Add()
                obj.SetXc(center[0]); obj.SetYc(center[1]); obj.SetRadius(r)
                obj.SetAngle1(math.degrees(math.atan2(p[1]-center[1],p[0]-center[0])))
                obj.SetAngle2(math.degrees(math.atan2(q[1]-center[1],q[0]-center[0])))
                obj.SetDirection(cw)
            require(obj.Update(), "Geometry Update")
            objects.append(obj)
        hole=draw.GetCircles().Add(); hole.SetXc(0.); hole.SetYc(0.); hole.SetRadius(11.5)
        require(hole.Update(), "Hole circle")
        relation(hole,c.ksCFixedPoint,index=0)
        radial(symbols,hole,(0.,0.),11.5,'hole_radius')
        for i,obj in enumerate(objects):
            j=(i+1)%len(objects)
            relation(obj,c.ksCMergePoints,objects[j],1 if specs[i][0]=='line' else 2,0 if specs[j][0]=='line' else 1)
            relation(obj,c.ksCTangentTwoCurves,objects[j])
        for i,spec in enumerate(specs):
            if spec[0]=='arc':
                radial(symbols,objects[i],spec[3],spec[4],f'radius_{i}')
            else:
                relation(objects[i],c.ksCFixedAngle)
        # Four central coordinates and two cap center coordinates each.
        for i in (2,5,8,11):
            center=specs[i][3]
            if i==8:
                relation(objects[i],c.ksCConcentricity,hole)
            else:
                linear(symbols,(0.,0.),center,c.ksLinDHorizontal,f'center_{i}_x',abs(center[0])) if abs(center[0])>1e-9 else relation(objects[i],c.ksCVAlignPoints,hole,0,0)
                linear(symbols,(0.,0.),center,c.ksLinDVertical,f'center_{i}_y',abs(center[1]))
    finally:
        require(s.EndEdit(), "EndEdit")
    state=s.GetConstraintsState()
    CHECKS.append(f"Состояние связей эскиза после EndEdit: {state} (1 = полностью определён).")
    print(json.dumps({'stage':'sketch','state':state}),flush=True)
    if state!=c.ksStateWellConstrained:
        LIMITATIONS.append(f"Эскиз не полностью определён: GetConstraintsState={state}.")
    ex=require(model.GetExtrusions().Add(c3d.o3d_bossExtrusion), "Extrusion")
    ex.SetName("02 Толщина 5 мм")
    ex.SetProfiles([s]); ex.SetDirection(c3d.dtNormal)
    require(ex.SetSideParameters(True,c3d.etBlind,5.,0.,False,None), "Depth")
    require(ex.Update(), "Extrusion Update")
    return state


def main():
    result=dict(task='1.13',status='failed',title='Пластина с симметричными плечами и центральным отверстием',script='solution.py',model=None,volume_mm3=None,reference_volume=9534,reference_units='mm3',volume_passed=False,checks=CHECKS,limitations=LIMITATIONS,tree='Эскиз контура и Ø23 → выдавливание 5 мм')
    attempt=Path(tempfile.mkdtemp(prefix='attempt-',dir=ROOT)); output=attempt/'model.m3d'
    require(not output.exists() and not output.is_symlink(), "Output exists")
    doc=None
    try:
        app=require(ksapi.GetKompas(), "Нет запущенной API-сессии КОМПАС; запуск запрещён")
        doc=require(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart,True), "Own document")
        d3=ksapi.IKompasDocument3D(doc); part=d3.GetTopPart();part.SetName('Practice Problem 1.13')
        state=build(part,part.GetModelContainer())
        require(part.RebuildModel(True), "Rebuild")
        f=ksapi.IFeature(part);errors=[];seen=set()
        def visit(item):
            if item.reference in seen:return
            seen.add(item.reference)
            if item.GetObjectError():errors.append((item.GetName(),item.GetObjectError()))
            for child in item.GetSubFeatures(c.ksOperTree,True,True):
                if child:visit(child)
        visit(f); require(not errors,f'Feature errors {errors}')
        CHECKS.append('Дерево операций без ошибок GetObjectError; перестроение успешно.')
        bodies=f.GetResultBodies();require(len(bodies)==1 and bodies[0].IsSolid(),'One solid')
        CHECKS.append('Получено одно твёрдое тело.')
        mass=require(ksapi.IMassInertiaParam(part),'Mass interface');mass.SetLengthUnits(c.ksLUnMM)
        require(mass.GetLengthUnits()==1,'Mass length units readback')
        require(mass.Calculate() and mass.IsActual(),'Actual mass properties')
        volume=mass.GetVolume();require(math.isfinite(volume) and volume>0,'Positive volume')
        result['volume_mm3']=volume;result['volume_passed']=9533.5<=volume<9534.5
        CHECKS.append(f'IMassInertiaParam.SetLengthUnits(ksLUnMM); GetLengthUnits=1; объём {volume:.12f} мм³.')
        CHECKS.append(f"Сравнение с [9533.5,9534.5): {result['volume_passed']}.")
        require(not output.exists() and not output.is_symlink(),'SaveAs output already exists')
        require(doc.SaveAs(str(output)), 'SaveAs')
        require(output.is_file() and output.stat().st_size>0,'Saved native file')
        result['model']=str(output.relative_to(ROOT))
        CHECKS.append('SaveAs в новый attempt-каталог успешен; model.m3d существует и непустой.')
        result['status']='passed' if result['volume_passed'] and state==c.ksStateWellConstrained else 'partial'
        if not result['volume_passed']:LIMITATIONS.append('Объём не совпал с эталонным интервалом; геометрия не подгонялась, прочтение контура требует уточнения.')
    except Exception as exc:
        result['status']='blocked' if doc is None else 'failed'
        LIMITATIONS.append(f'{type(exc).__name__}: {exc}')
        traceback.print_exc()
    finally:
        if doc is not None:
            try:
                require(doc.Close(c.kdDoNotSaveChanges),'Close own document')
                CHECKS.append('Собственный документ закрыт finally; чужие документы не изменялись и не закрывались.')
            except Exception as exc:
                result['status']='failed';LIMITATIONS.append(f'Закрытие документа: {exc}')
        (ROOT/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
