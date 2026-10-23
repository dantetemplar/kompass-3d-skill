# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Practice Problem 2.6: native dimension-driven sketch and 8 mm extrusion."""
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
POINTS = {}


def req(value, message):
    if not value:
        raise RuntimeError(message)
    return value


def log(message):
    print(message, flush=True)


def con(obj, kind, partner=None, index=None, pi=None, name=None, value=None, degrees=None):
    if partner is not None and kind == c.ksCMergePoints:
        for existing in obj.GetConstraints():
            if (existing.GetConstraintType() == kind
                    and existing.GetIndex() == index and existing.GetPartnerIndex() == pi
                    and any(p.GetId() == partner.GetId() for p in existing.GetPartners())):
                return existing
    item = req(obj.NewConstraint(), 'NewConstraint')
    item.SetConstraintType(kind)
    if partner is not None:
        item.SetPartners([partner])
    if index is not None:
        item.SetIndex(index)
    if pi is not None:
        item.SetPartnerIndex(pi)
    if name is not None:
        item.SetVariable(name)
    if value is not None:
        item.SetConstraintValue(value)
    if degrees is not None:
        item.SetDegrees(degrees)
        item.SetMinutes(0)
        item.SetSeconds(0)
    created = item.Create()
    if not created or not item.IsValid():
        if created and partner is not None:
            for existing in obj.GetConstraints():
                if (existing.IsValid() and existing.GetConstraintType() == kind
                        and (index is None or existing.GetIndex() == index)
                        and (pi is None or existing.GetPartnerIndex() == pi)
                        and any(p.GetId() == partner.GetId() for p in existing.GetPartners())):
                    log(f'Constraint {kind}: fresh readback valid after successful Create')
                    return existing
        log(json.dumps({'constraint_failure': kind, 'object': obj.GetId(), 'index': index, 'partner_index': pi, 'partner': partner.GetId() if partner else None, 'existing': [{'type': x.GetConstraintType(), 'index': x.GetIndex(), 'partner_index': x.GetPartnerIndex(), 'partners': [p.GetId() for p in x.GetPartners()]} for x in obj.GetConstraints()]}))
        raise RuntimeError(f'Constraint {kind}, {name}, {obj.GetId()}')
    return item


def merge(a, ai, b, bi):
    return con(a, c.ksCMergePoints, b, ai, bi)


def line(drawing, p, q, construction=False):
    obj = req(drawing.GetLineSegments().Add(), 'Line')
    obj.SetX1(p[0]); obj.SetY1(p[1]); obj.SetX2(q[0]); obj.SetY2(q[1])
    obj.SetStyle(3 if construction else 1)
    req(obj.Update(), 'Line Update')
    POINTS[obj.GetId()] = {0: p, 1: q}
    return obj


def arc(drawing, center, radius, a1, a2, clockwise=False):
    obj = req(drawing.GetArcs().Add(), 'Arc')
    obj.SetXc(center[0]); obj.SetYc(center[1]); obj.SetRadius(radius)
    obj.SetAngle1(math.degrees(a1) % 360); obj.SetAngle2(math.degrees(a2) % 360)
    obj.SetDirection(clockwise)
    req(obj.Update(), 'Arc Update')
    POINTS[obj.GetId()] = {0: center, 1: add(center, polar(radius, a1)), 2: add(center, polar(radius, a2))}
    return obj


def dim(symbols, a, ai, b, bi, name, value, orientation=c.ksLinDParallel):
    p, q = POINTS[a.GetId()][ai], POINTS[b.GetId()][bi]
    obj = req(symbols.GetLineDimensions().Add(), 'Line dimension')
    obj.SetX1(p[0]); obj.SetY1(p[1]); obj.SetX2(q[0]); obj.SetY2(q[1])
    obj.SetX3((p[0] + q[0]) / 2 - 10); obj.SetY3((p[1] + q[1]) / 2 - 12)
    obj.SetOrientation(orientation)
    req(obj.Update(), 'Dimension Update: ' + name)
    merge(obj, 0, a, ai)
    merge(obj, 1, b, bi)
    con(obj, c.ksCFixedDim)
    con(obj, c.ksCDimWithVariable, name=name, value=value)
    return obj


def radial(symbols, obj, radius, name):
    p = POINTS[obj.GetId()][0]
    r = req(symbols.GetRadialDimensions().Add(), 'Radius dimension')
    r.SetBaseObject(obj); r.SetXc(p[0]); r.SetYc(p[1]); r.SetRadius(radius); r.SetAngle(35)
    req(r.Update(), 'Radius dimension Update')
    con(r, c.ksCFixedDim)
    con(r, c.ksCDimWithVariable, name=name, value=radius)
    return r


def angle(symbols, a, b, center, a1, a2, name, degrees):
    obj = req(symbols.GetAngleDimensions().Add(c.ksDrADimension), 'Angle dimension')
    obj.SetDimensionType(c.ksADMinAngle if degrees < 90 else c.ksADMaxAngle)
    obj.SetBaseObject1(a); obj.SetBaseObject2(b)
    obj.SetXc(center[0]); obj.SetYc(center[1]); obj.SetRadius(24)
    obj.SetAngle1(a1); obj.SetAngle2(a2); obj.SetDirection(False)
    p, q = add(center, polar(20, math.radians(a1))), add(center, polar(20, math.radians(a2)))
    obj.SetX1(p[0]); obj.SetY1(p[1]); obj.SetX2(q[0]); obj.SetY2(q[1])
    obj.SetX3(center[0] + 25); obj.SetY3(center[1] + 20)
    req(obj.Update(), 'Angular dimension Update: ' + name)
    con(obj, c.ksCFixedDim)
    log(f'Angular fixed driving dimension {name}: {degrees} degrees')
    return obj


def add(a, b):
    return a[0] + b[0], a[1] + b[1]


def sub(a, b):
    return a[0] - b[0], a[1] - b[1]


def mul(a, k):
    return a[0] * k, a[1] * k


def polar(r, angle):
    return r * math.cos(angle), r * math.sin(angle)


def blend(p0, corner, p1, r):
    u = mul(sub(corner, p0), 1 / math.dist(corner, p0))
    v = mul(sub(p1, corner), 1 / math.dist(p1, corner))
    turn = math.atan2(u[0]*v[1] - u[1]*v[0], u[0]*v[0] + u[1]*v[1])
    t = r * math.tan(abs(turn) / 2)
    p, q = sub(corner, mul(u, t)), add(corner, mul(v, t))
    sign = 1 if turn > 0 else -1
    center = add(p, (-sign * r * u[1], sign * r * u[0]))
    return p, q, center, math.atan2(p[1]-center[1], p[0]-center[0]), math.atan2(q[1]-center[1], q[0]-center[0]), turn < 0


@contextmanager
def edit(sketch):
    fragment = req(sketch.BeginEdit(False), 'BeginEdit')
    try:
        fragment.SetParametricMode(True)
        req(fragment.IsParametricMode(), 'Parametric mode')
        view = req(fragment.GetViewsAndLayersManager().GetViews().GetActiveView(), 'Active view')
        yield req(ksapi.IDrawingContainer(view), 'Drawing'), req(ksapi.ISymbols2DContainer(view), 'Dimensions')
    finally:
        req(sketch.EndEdit(), 'EndEdit')
    state = sketch.GetConstraintsState()
    log(f'Constraint state: {state}')
    CHECKS.append(f'Эскиз: GetConstraintsState={state}, полностью определён={state == c.ksStateWellConstrained}.')
    CHECKS.append('Начало координат — нижний левый угол по красной метке; фиксирована только одна базовая точка, использованы нативные геометрические связи и управляющие размеры.')
    req(state == c.ksStateWellConstrained, f'Sketch is not fully constrained: {state}')


def build(part, model):
    O, B = (0., 0.), (142., 0.)
    ul, ur = polar(1, math.radians(58)), polar(1, math.radians(72))
    D, C = mul(ul, 150), add(B, mul(ur, 150))
    A, Q = mul(ul, 71), add(B, mul(ur, 82))
    u = mul(sub(Q, A), 1 / math.dist(A, Q)); v = (-u[1], u[0])
    P = add(A, mul(u, 41)); S = add(P, mul(u, 55))
    phi = math.atan2(u[1], u[0])
    sketch = req(model.GetSketchs().Add(), 'Sketch')
    sketch.SetName('01 Контур, R32, выемка R9 и замочная скважина R17/R7/R8')
    sketch.SetPlane(req(part.GetDefaultObject(c3d.o3d_planeXOY), 'XOY'))
    req(sketch.Update(), 'Sketch plane')
    with edit(sketch) as (drawing, symbols):
        # Untrimmed quadrilateral carries dimensions; only its lower-left point is anchored.
        bottom = line(drawing, O, B, True)
        right = line(drawing, B, C, True)
        top = line(drawing, C, D, True)
        left = line(drawing, D, O)
        quad = [bottom, right, top, left]
        for a, b in zip(quad, quad[1:] + quad[:1]):
            merge(a, 1, b, 0)
        con(bottom, c.ksCHorizontal)
        con(bottom, c.ksCFixedPoint, index=0)
        dim(symbols, bottom, 0, bottom, 1, 'base_width', 142)
        dim(symbols, left, 0, left, 1, 'left_length', 150)
        dim(symbols, right, 0, right, 1, 'right_length', 150)
        angle(symbols, bottom, left, O, 0, 58, 'left_angle', 58)
        angle(symbols, right, bottom, B, 72, 180, 'right_angle', 108)
        log('Quadrilateral dimensions created')
        # Lower relief: 52 mm flat and R9 quarter-arcs, not a tangent slot at the baseline.
        bl = line(drawing, O, (38., 0.))
        nl = arc(drawing, (47., 0.), 9, math.pi, math.pi/2, True)
        nt = line(drawing, (47., 9.), (99., 9.))
        nr = arc(drawing, (99., 0.), 9, math.pi/2, 0, True)
        br = line(drawing, (108., 0.), B)
        merge(bl, 0, bottom, 0); merge(br, 1, bottom, 1)
        merge(bl, 1, nl, 1); merge(nl, 2, nt, 0); merge(nt, 1, nr, 1); merge(nr, 2, br, 0)
        for obj in (bl, nt, br):
            con(obj, c.ksCHorizontal)
        con(nl, c.ksCTangentTwoCurves, nt); con(nr, c.ksCTangentTwoCurves, nt)
        con(nl, c.ksCPointOnCurve, bottom, index=0)
        radial(symbols, nl, 9, 'relief_radius'); con(nr, c.ksCEqualRadius, nl)
        dim(symbols, nt, 0, nt, 1, 'relief_flat', 52)
        dim(symbols, bottom, 0, nl, 0, 'relief_offset', 47, c.ksLinDHorizontal)
        # Top-right corner fillet is tangent to the original 150-mm-sided quadrilateral.
        tr, tt, fc, fa, fb, cw = blend(B, C, D, 32)
        er = line(drawing, B, tr)
        fillet = arc(drawing, fc, 32, fa, fb, cw)
        et = line(drawing, tt, D)
        merge(er, 0, bottom, 1); merge(et, 1, left, 0)
        merge(er, 1, fillet, 1); merge(fillet, 2, et, 0)
        con(er, c.ksCPointOnCurve, right, index=1)
        con(et, c.ksCPointOnCurve, top, index=0)
        con(fillet, c.ksCTangentTwoCurves, er); con(fillet, c.ksCTangentTwoCurves, et)
        radial(symbols, fillet, 32, 'outer_radius')
        log('Outer profile created')
        # Auxiliary axis joins the 71-mm station on the left to the 82-mm station on the right.
        station = line(drawing, O, A, True)
        axis = line(drawing, A, Q, True)
        centers = line(drawing, P, S, True)
        merge(station, 0, bottom, 0); con(station, c.ksCPointOnCurve, left, index=1)
        dim(symbols, station, 0, station, 1, 'left_station', 71)
        merge(axis, 0, station, 1); con(axis, c.ksCPointOnCurve, right, index=1)
        dim(symbols, bottom, 1, axis, 1, 'right_station', 82)
        con(centers, c.ksCPointOnCurve, axis, index=0)
        con(centers, c.ksCPointOnCurve, axis, index=1)
        dim(symbols, axis, 0, centers, 0, 'key_offset', 41)
        dim(symbols, centers, 0, centers, 1, 'key_pitch', 55)
        def local(x, y):
            return add(P, add(mul(u, x), mul(v, y)))
        theta = math.atan2(15, 20)
        big = arc(drawing, P, 17, phi+theta, phi-theta)
        low = arc(drawing, local(20, -15), 8, phi+math.pi-theta, phi+math.pi/2, True)
        lowline = line(drawing, local(20, -7), local(55, -7))
        small = arc(drawing, S, 7, phi-math.pi/2, phi+math.pi/2)
        upline = line(drawing, local(55, 7), local(20, 7))
        high = arc(drawing, local(20, 15), 8, phi-math.pi/2, phi+math.pi+theta, True)
        chain = [(big, 1, 2), (low, 1, 2), (lowline, 0, 1), (small, 1, 2), (upline, 0, 1), (high, 1, 2)]
        for i, (obj, start, end) in enumerate(chain):
            nxt, ns, _ = chain[(i+1) % len(chain)]
            merge(obj, end, nxt, ns)
            con(obj, c.ksCTangentTwoCurves, nxt)
        merge(big, 0, centers, 0); merge(small, 0, centers, 1)
        con(lowline, c.ksCParallel, axis)
        con(upline, c.ksCParallel, axis)
        radial(symbols, big, 17, 'key_circle_radius')
        radial(symbols, small, 7, 'key_end_radius')
        radial(symbols, low, 8, 'key_blend_radius')
        radial(symbols, high, 8, 'key_blend_upper_radius')
        log('Keyhole constraint network created')
    op = req(model.GetExtrusions().Add(c3d.o3d_bossExtrusion), 'Extrusion')
    op.SetName('02 Пластина толщиной 8 мм')
    op.SetProfiles([sketch]); op.SetDirection(c3d.dtNormal)
    req(op.SetSideParameters(True, c3d.etBlind, 8., 0., False, None), 'Extrusion depth')
    req(op.Update(), 'Extrusion Update')
    CHECKS.append('Нативное выдавливание на 8 мм построено успешно.')
    return sketch


def validate(part):
    req(part.RebuildModel(True), 'RebuildModel')
    root = req(ksapi.IFeature(part), 'Root feature')
    bodies = root.GetResultBodies()
    req(len(bodies) == 1 and bodies[0].IsSolid(), 'One solid')
    CHECKS.append('После перестроения получено одно твёрдое тело.')
    seen, errors = set(), []
    def visit(feature):
        if feature.reference in seen:
            return
        seen.add(feature.reference)
        if feature.GetObjectError():
            errors.append((feature.GetName(), feature.GetObjectError()))
        for child in feature.GetSubFeatures(c.ksOperTree, True, True):
            if child:
                visit(child)
    visit(root)
    req(not errors, f'Feature errors: {errors}')
    CHECKS.append('Дерево операций проверено: GetObjectError=0 во всех ветвях.')
    mass = req(ksapi.IMassInertiaParam(part), 'Mass properties')
    mass.SetLengthUnits(c.ksLUnMM)
    req(mass.GetLengthUnits() == 1, 'Mass units readback must equal 1')
    req(mass.Calculate() and mass.IsActual(), 'Mass calculation')
    volume = mass.GetVolume()
    req(math.isfinite(volume) and volume > 0, 'Finite positive volume')
    CHECKS.append(f'МЦХ: SetLengthUnits(ksLUnMM), GetLengthUnits=1; Calculate и IsActual успешны; объём={volume:.12f} мм³.')
    return volume


def main():
    result = {'task': '2.6', 'status': 'failed', 'title': 'SOLIDWORKS Practice Problem 2.6 — пластина с замочной скважиной', 'script': 'solution.py', 'model': None, 'volume_mm3': None, 'reference_volume': 109681, 'reference_units': 'mm3', 'volume_passed': False, 'checks': CHECKS, 'limitations': [], 'tree': 'Эскиз: внешний контур R32, нижняя выемка R9, замочная скважина R17/R7/R8 и вспомогательные линии → выдавливание 8 мм'}
    result['limitations'] = [
        'Угловые размеры 58° и 108° управляют геометрией через ksCFixedDim, без именованных угловых переменных.',
        'Испытания изменения размеров, повторное открытие и превью не выполнялись согласно заданию.',
    ]
    output = Path(tempfile.mkdtemp(prefix='attempt-', dir=ROOT)) / 'model.m3d'
    req(not output.exists() and not output.is_symlink(), 'Output must not exist')
    doc = None
    try:
        app = req(ksapi.GetKompas(), 'Нет существующей API-сессии КОМПАС; приложение не запускается')
        doc = req(app.GetDocuments().AddWithDefaultSettings(c.ksDocumentPart, True), 'New owned part')
        part = req(ksapi.IKompasDocument3D(doc).GetTopPart(), 'Top part')
        part.SetName('Practice Problem 2.6')
        build(part, req(part.GetModelContainer(), 'Model container'))
        volume = validate(part)
        result['volume_mm3'] = volume
        result['volume_passed'] = 109680.5 <= volume < 109681.5
        CHECKS.append(f'Сравнение с интервалом [109680.5, 109681.5) мм³: {result["volume_passed"]}.')
        req(not output.exists() and not output.is_symlink(), 'SaveAs path must still not exist')
        req(doc.SaveAs(str(output)), 'SaveAs')
        req(output.is_file() and output.stat().st_size > 0, 'Nonempty saved m3d')
        req(Path(doc.GetFullPath()).resolve() == output.resolve(), 'Saved document path')
        result['model'] = str(output.relative_to(ROOT))
        CHECKS.append('SaveAs в новый attempt-каталог успешен; model.m3d существует и непустой.')
        result['status'] = 'passed' if result['volume_passed'] else 'partial'
        if not result['volume_passed']:
            result['limitations'].append('Объём не попал в интервал округления эталона; геометрия под объём не подгонялась.')
    except Exception as exc:
        result['limitations'].append(f'{type(exc).__name__}: {exc}')
        traceback.print_exc()
    finally:
        if doc is not None:
            try:
                req(doc.Close(c.kdDoNotSaveChanges), 'Close own document')
                CHECKS.append('Собственный документ закрыт в finally; чужие документы не изменялись и не закрывались.')
            except Exception as exc:
                result['status'] = 'partial'
                result['limitations'].append(f'Закрытие собственного документа: {exc}')
        (ROOT / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        log(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
