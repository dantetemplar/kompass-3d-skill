# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Native KOMPAS solution for Practice Problem 1.15, millimetres.

Front profile uses local XY; thickness is Z. Origin is the red lower-left
corner of the front view on the near face of the 20 mm web. Upper lug is
Z=-5..0 and lower lug Z=20..25, as specified by the top and side views.
"""
from contextlib import contextmanager
from pathlib import Path
import json
import math
import tempfile

import ksapi
from constants import constants as c
from constants3d import constants as c3d

ROOT = Path(__file__).resolve().parent
CHECKS = []
SKETCHES = []


def need(value, message):
    if not value:
        raise RuntimeError(message)
    return value


def log(message):
    print(message, flush=True)


def constraint(obj, kind, partners=(), index=None, partner_index=None, name=None, value=None, degrees=None, expression=None):
    q = need(obj.NewConstraint(), 'NewConstraint')
    q.SetConstraintType(kind)
    if partners:
        q.SetPartners(list(partners))
    if index is not None:
        q.SetIndex(index)
    if partner_index is not None:
        q.SetPartnerIndex(partner_index)
    if name is not None:
        q.SetVariable(name)
    if value is not None:
        q.SetConstraintValue(value)
    if degrees is not None:
        q.SetDegrees(degrees)
    if expression is not None:
        q.SetExpression(expression)
    need(q.Create() and q.IsValid(), f'Constraint type={kind}, variable={name}')
    return q


def drive(dim, name, value, expression=None, angular=False):
    constraint(dim, c.ksCFixedDim)
    constraint(dim, c.ksCDimWithVariable, name=name, value=value,
               degrees=int(value) if angular else None, expression=expression)
    return dim


def ld(symbols, p, q, orient, name, expression=None):
    # p/q are (object, point index, initial XY); association is native.
    dim = need(symbols.GetLineDimensions().Add(), 'Linear dimension')
    dim.SetX1(p[2][0]); dim.SetY1(p[2][1])
    dim.SetX2(q[2][0]); dim.SetY2(q[2][1])
    dim.SetX3((p[2][0]+q[2][0])/2-8)
    dim.SetY3((p[2][1]+q[2][1])/2-8)
    dim.SetOrientation(orient)
    need(dim.Update(), 'Linear dimension Update')
    need(dim.Associate(), 'Associate '+name)
    associations=dim.GetConstraints()
    for idx in (0,1):
        need(any(a.IsValid() and a.GetConstraintType()==c.ksCMergePoints and a.GetIndex()==idx
                 and a.GetPartners() for a in associations), 'Dimension witness '+name)
    value=abs(q[2][0]-p[2][0]) if orient==c.ksLinDHorizontal else abs(q[2][1]-p[2][1])
    return drive(dim,name,value,expression)


def rd(symbols,obj,center,r,name):
    dim=need(symbols.GetRadialDimensions().Add(),'Radial dimension')
    dim.SetBaseObject(obj); dim.SetXc(center[0]); dim.SetYc(center[1])
    dim.SetRadius(r); dim.SetAngle(35.)
    need(dim.Update(),'Radial Update')
    return drive(dim,name,r)


def ad(symbols,one,two,center,a1,a2,name,value):
    dim=need(symbols.GetAngleDimensions().Add(c.ksDrADimension),'Angle dimension')
    dim.SetBaseObject1(one); dim.SetBaseObject2(two)
    dim.SetXc(center[0]); dim.SetYc(center[1]); dim.SetRadius(18.)
    dim.SetAngle1(a1); dim.SetAngle2(a2); dim.SetDimensionType(c.ksADMinAngle)
    dim.SetX1(center[0]+20*math.cos(math.radians(a1)))
    dim.SetY1(center[1]+20*math.sin(math.radians(a1)))
    dim.SetX2(center[0]+20*math.cos(math.radians(a2)))
    dim.SetY2(center[1]+20*math.sin(math.radians(a2)))
    need(dim.Update(),'Angular Update '+name)
    return drive(dim,name,value,angular=True)


def line(d,p,q):
    x=need(d.GetLineSegments().Add(),'Line')
    x.SetX1(p[0]); x.SetY1(p[1]); x.SetX2(q[0]); x.SetY2(q[1])
    need(x.Update(),'Line Update')
    return x


def circle(d,center,r):
    x=need(d.GetCircles().Add(),'Circle')
    x.SetXc(center[0]); x.SetYc(center[1]); x.SetRadius(r)
    need(x.Update(),'Circle Update')
    return x


def arc(d,center,r,a1,a2,clockwise):
    x=need(d.GetArcs().Add(),'Arc')
    x.SetXc(center[0]); x.SetYc(center[1]); x.SetRadius(r)
    x.SetAngle1(a1); x.SetAngle2(a2); x.SetDirection(clockwise)
    need(x.Update(),'Arc Update')
    return x


def merge(a,ai,b,bi):
    constraint(a,c.ksCMergePoints,[b],ai,bi)


@contextmanager
def sketch(part,model,plane,name):
    sk=need(model.GetSketchs().Add(),'Sketch')
    sk.SetName(name); sk.SetPlane(plane); need(sk.Update(),'Sketch Update')
    for uv in ((0,0),(1,0),(0,1)):
        point=sk.GetPoint3D(*uv,0.,0.,0.)
        need(point[0],'Sketch frame')
        log(f'{name} frame {uv}: {point[1:]}')
    frag=need(sk.BeginEdit(False),'BeginEdit')
    try:
        frag.SetParametricMode(True)
        need(frag.IsParametricMode(),'Parametric mode')
        view=need(frag.GetViewsAndLayersManager().GetViews().GetActiveView(),'View')
        yield sk,ksapi.IDrawingContainer(view),ksapi.ISymbols2DContainer(view)
    finally:
        need(sk.EndEdit(),'EndEdit')
    state=sk.GetConstraintsState()
    log(f'{name} constraint state {state}')
    SKETCHES.append(sk)
    need(state==c.ksStateWellConstrained,f'{name}: not fully defined ({state})')
    CHECKS.append(f'{name}: native driving dimensions/geometric constraints, state=1 (fully defined), no total fixation.')


def extrude(model,sk,depth,name,reverse=False):
    op=need(model.GetExtrusions().Add(c3d.o3d_bossExtrusion),'Extrusion')
    op.SetName(name); op.SetProfiles([sk])
    op.SetDirection(c3d.dtReverse if reverse else c3d.dtNormal)
    need(op.SetSideParameters(not reverse,c3d.etBlind,depth,0.,False,None),'Depth')
    need(op.Update(),'Extrusion Update '+name)
    CHECKS.append(name+': native extrusion Update succeeded.')
    return op


def feature_errors(part):
    errors=[]; seen=set()
    def visit(x):
        if x.reference in seen:
            return
        seen.add(x.reference)
        if x.GetObjectError():
            errors.append((x.GetName(),x.GetObjectError()))
        for child in x.GetSubFeatures(c.ksOperTree,True,True):
            if child:
                visit(child)
    visit(ksapi.IFeature(part))
    return errors


def build(part,model):
    plane=need(part.GetDefaultObject(c3d.o3d_planeXOY),'XOY')
    a=10+(65-35)*math.tan(math.radians(30))
    pts=[(0.,0.),(40.,0.),(40.,65.),(a,65.),(10.,35.),(10.,14.),(0.,14.)]
    with sketch(part,model,plane,'01 Web — 40, 65, 35, 10, 30°') as (sk,d,s):
        ls=[line(d,p,q) for p,q in zip(pts,pts[1:]+pts[:1])]
        for i,x in enumerate(ls):
            merge(x,1,ls[(i+1)%len(ls)],0)
            if i!=3:
                constraint(x,c.ksCHorizontal if i in (0,2,5) else c.ksCVertical)
        constraint(ls[0],c.ksCFixedPoint,index=0)
        def pt(i,j): return (ls[i],j,pts[(i+j)%len(pts)])
        ld(s,pt(0,0),pt(0,1),c.ksLinDHorizontal,'web_width')
        ld(s,pt(1,0),pt(1,1),c.ksLinDVertical,'web_height')
        ld(s,pt(0,0),pt(4,0),c.ksLinDHorizontal,'web_step_x')
        ld(s,pt(0,0),pt(4,0),c.ksLinDVertical,'web_slope_start')
        ld(s,pt(0,0),pt(6,0),c.ksLinDVertical,'web_foot_height')
        ad(s,ls[3],ls[4],(10,35),60,90,'web_slope_angle',30.)
    extrude(model,sk,20.,'01 Web thickness 20 mm')
    # Upper lug: clockwise R7 cap from top horizontal to a lower edge
    # 65° from vertical (25° from horizontal), tangent at both transitions.
    cx=a+45; cy=65-7; angle=math.radians(25)
    end=(cx+7*math.sin(angle),cy-7*math.cos(angle))
    bottom=(a,cy-7/math.cos(angle)-45*math.tan(angle))
    with sketch(part,model,plane,'02 Upper lug — 45, R7, 65°, Ø6') as (sk,d,s):
        top=line(d,(a,65),(cx,65))
        cap=arc(d,(cx,cy),7.,90.,295.,True)
        slope=line(d,end,bottom)
        back=line(d,bottom,(a,65))
        merge(top,1,cap,1); merge(cap,2,slope,0); merge(slope,1,back,0); merge(back,1,top,0)
        constraint(top,c.ksCHorizontal); constraint(back,c.ksCVertical)
        constraint(top,c.ksCTangentTwoCurves,[cap]); constraint(slope,c.ksCTangentTwoCurves,[cap])
        rd(s,cap,(cx,cy),7.,'upper_outer_radius')
        origin=need(d.GetPoints().Add(),'Origin datum')
        origin.SetX(0.); origin.SetY(0.); need(origin.Update(),'Datum Update')
        constraint(origin,c.ksCFixedPoint,index=0)
        datum=(origin,0,(0.,0.)); left=(top,0,(a,65)); center=(cap,0,(cx,cy))
        ld(s,datum,left,c.ksLinDHorizontal,'upper_root_x')
        ld(s,datum,left,c.ksLinDVertical,'upper_top_height')
        ld(s,left,center,c.ksLinDHorizontal,'upper_reach')
        ad(s,back,slope,bottom,25,90,'upper_taper_angle',65.)
        hole=circle(d,(cx,cy),3.)
        constraint(hole,c.ksCConcentricity,[cap])
        rd(s,hole,(cx,cy),3.,'upper_hole_radius')
    extrude(model,sk,5.,'02 Upper lug thickness 5 mm',reverse=True)
    plane2=need(ksapi.IAuxiliaryGeomContainer(part).GetPlanes3D().Add(c3d.o3d_planeOffset),'Offset plane')
    plane2.SetName('Lower lug base Z=20')
    offset=ksapi.IPlane3DByOffset(plane2)
    offset.SetBasePlane(plane); offset.SetOffset(20.); offset.SetDirection(True)
    need(offset.Update(),'Offset plane Update')
    with sketch(part,model,plane2,'03 Lower lug — 40+15, R7, Ø7') as (sk,d,s):
        bottom=line(d,(10,0),(55,0))
        cap=arc(d,(55,7),7.,270.,90.,False)
        top=line(d,(55,14),(10,14)); back=line(d,(10,14),(10,0))
        merge(bottom,1,cap,1); merge(cap,2,top,0); merge(top,1,back,0); merge(back,1,bottom,0)
        constraint(bottom,c.ksCHorizontal); constraint(top,c.ksCHorizontal); constraint(back,c.ksCVertical)
        constraint(bottom,c.ksCTangentTwoCurves,[cap]); constraint(top,c.ksCTangentTwoCurves,[cap])
        origin=need(d.GetPoints().Add(),'Lower origin datum')
        origin.SetX(0.); origin.SetY(0.); need(origin.Update(),'Lower datum Update')
        constraint(origin,c.ksCFixedPoint,index=0)
        constraint(bottom,c.ksCHAlignPoints,[origin],index=0,partner_index=0)
        rd(s,cap,(55,7),7.,'lower_outer_radius')
        ld(s,(origin,0,(0,0)),(bottom,0,(10,0)),c.ksLinDHorizontal,'lower_root_x')
        ld(s,(origin,0,(0,0)),(cap,0,(55,7)),c.ksLinDHorizontal,'lower_center_x','40+15')
        hole=circle(d,(55,7),3.5)
        constraint(hole,c.ksCConcentricity,[cap]); rd(s,hole,(55,7),3.5,'lower_hole_radius')
    extrude(model,sk,5.,'03 Lower lug thickness 5 mm')


def main():
    result={'task':'1.15','status':'failed','title':'SOLIDWORKS Practice Problem 1.15 — Basic Sketch & Extrusion',
            'script':'solution.py','model':None,'volume_mm3':None,'reference_volume':45867,
            'reference_units':'mm3','volume_passed':False,'checks':CHECKS,'limitations':[],
            'tree':'Web sketch → extrusion 20; upper lug sketch with Ø6 → extrusion 5 reverse; offset plane 20; lower lug sketch with Ø7 → extrusion 5.'}
    doc=None
    out=Path(tempfile.mkdtemp(prefix='attempt-',dir=ROOT))/'model.m3d'
    need(not out.exists(),'Output already exists')
    try:
        app=need(ksapi.GetKompas(),'Existing KOMPAS API session unavailable; no launch')
        doc=need(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart,True),'Own part')
        part=need(ksapi.IKompasDocument3D(doc).GetTopPart(),'Top part')
        part.SetName('Practice Problem 1.15')
        build(part,need(part.GetModelContainer(),'Model container'))
        need(part.RebuildModel(True),'Rebuild')
        bodies=ksapi.IFeature(part).GetResultBodies()
        need(len(bodies)==1 and bodies[0].IsSolid(),'Expected one solid')
        CHECKS.append('Rebuild succeeded; one solid body.')
        errors=feature_errors(part); need(not errors,f'Feature errors: {errors}')
        CHECKS.append('No native feature-tree operation errors.')
        mass=need(ksapi.IMassInertiaParam(part),'Mass properties')
        mass.SetLengthUnits(c.ksLUnMM)
        need(mass.GetLengthUnits()==1,'Mass length units readback != 1')
        CHECKS.append('IMassInertiaParam.SetLengthUnits(c.ksLUnMM); GetLengthUnits()=1.')
        need(mass.Calculate() and mass.IsActual(),'Mass calculation')
        volume=mass.GetVolume(); need(math.isfinite(volume) and volume>0,'Invalid volume')
        result['volume_mm3']=volume
        result['volume_passed']=45866.5<=volume<45867.5
        CHECKS.append(f'Native volume {volume:.9f} mm3; reference interval [45866.5,45867.5): {result["volume_passed"]}.')
        need(not out.exists() and not out.is_symlink(),'SaveAs path exists')
        need(doc.SaveAs(str(out)),'SaveAs')
        need(out.is_file() and out.stat().st_size>0,'Missing model')
        result['model']=str(out.relative_to(ROOT))
        CHECKS.append('SaveAs succeeded to a previously absent attempt-*/model.m3d; file is nonempty.')
        result['status']='passed' if result['volume_passed'] else 'partial'
        if not result['volume_passed']:
            result['limitations'].append('Native volume does not match the reference rounding interval; no geometry was adjusted to fit it.')
        result['limitations'].append('The upper root X position and web foot height are native driving dimensions initialized from the drawing geometry (10+30*tan(30 degrees), 2*R7); they are not cross-sketch associative expressions.')
        result['limitations'].append('No dimension-change test, reopen, preview or export was performed, as requested.')
    except Exception as exc:
        result['limitations'].append(f'{type(exc).__name__}: {exc}')
        log(result['limitations'][-1])
    finally:
        if doc is not None:
            try:
                need(doc.Close(c.kdDoNotSaveChanges),'Close owned document')
                CHECKS.append('Own document closed in finally; no foreign document modified or closed.')
            except Exception as exc:
                result['status']='failed'
                result['limitations'].append('Closing owned document: '+str(exc))
        (ROOT/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        log(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    main()
