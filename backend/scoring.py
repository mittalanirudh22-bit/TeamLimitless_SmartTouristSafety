"""Turns raw GPS fixes into the seven risk-engine inputs, then scores them."""
import math, time
from datetime import datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo
from functools import lru_cache
import joblib, numpy as np, pandas as pd, yaml
from shapely import STRtree
from shapely.geometry import Point, shape
from sqlalchemy import func
from sqlalchemy.orm import Session
from . import models as m
from .database import ROOT
from ml.fast_iforest import FastScorer
from ml.risk_engine import calculate_risk

R = 6371000.0
MODEL_PATH = ROOT / 'ml' / 'models' / 'mobility_isolation_forest.joblib'


def hav(a, b, c, d):
    a, b, c, d = map(math.radians, (a, b, c, d))
    x = math.sin((c - a) / 2) ** 2 + math.cos(a) * math.cos(c) * math.sin((d - b) / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x))


def bearing(a, b, c, d):
    a, c, dl = math.radians(a), math.radians(c), math.radians(d - b)
    y = math.sin(dl) * math.cos(c)
    x = math.cos(a) * math.sin(c) - math.sin(a) * math.cos(c) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


@lru_cache
def model_bundle():
    return joblib.load(MODEL_PATH) if MODEL_PATH.exists() else None


@lru_cache
def fast_scorer():
    b = model_bundle()
    return FastScorer.build(b['model'], len(b['features'])) if b else None  # None -> fall back to sklearn


@lru_cache
def location_cfg(slug):
    return yaml.safe_load((ROOT / 'locations' / slug / 'config.yaml').read_text())


_cache: dict = {}
GEOFENCE_TTL, CONTEXT_TTL = 60, 300  # seconds; both change rarely, and a stale minute is harmless


def _cached(key, ttl, build):
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < ttl:
        return hit[1]
    val = build()
    _cache[key] = (time.monotonic(), val)
    return val


def clear_caches():
    _cache.clear()


def geofence_index(db: Session, slug):
    """(rows, STRtree) built once per TTL instead of re-reading and re-parsing every polygon on every fix."""
    def build():
        rows = [(g.name, g.risk_level or 0.0, shape(g.geojson)) for g in db.query(m.Geofence).filter_by(location_slug=slug)]
        return rows, STRtree([r[2] for r in rows])
    return _cached(('geo', slug), GEOFENCE_TTL, build)


def historical_context(db: Session, slug):
    """Latest-year share of violent/personal-safety crime, scaled 0..1 -- a city-level prior, not a prediction."""
    def build():
        y = db.query(func.max(m.SafetyContext.year)).filter_by(location_slug=slug).scalar()
        if y is None:
            return 0.0
        rows = db.query(m.SafetyContext).filter_by(location_slug=slug, year=y).all()
        tot = sum(r.crime_count for r in rows) or 1
        personal = sum(r.crime_count for r in rows if r.crime_category in ('robbery', 'assault', 'harassment'))
        return round(min(1.0, (personal / tot) * 2), 4)
    return _cached(('ctx', slug), CONTEXT_TTL, build)


def as_utc(dt):
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _features(prev, lat, lon, ts):
    """Movement features from the previous fixes (newest first). Returns (feats, speed, accel, turn, inactivity)."""
    speed = accel = turn = None
    inactivity = 0.0
    feats = {}
    if prev:
        p = prev[0]
        dt = (ts - datetime.fromisoformat(p.ts)).total_seconds()
        if dt > 0:
            dist = hav(p.lat, p.lon, lat, lon)
            speed = dist / dt * 3.6
            if p.speed is not None:
                accel = abs(speed - p.speed) / dt
            if len(prev) > 1:
                q = prev[1]
                b1 = bearing(q.lat, q.lon, p.lat, p.lon)
                b2 = bearing(p.lat, p.lon, lat, lon)
                turn = abs((b2 - b1 + 180) % 360 - 180)
            if speed < 1:
                inactivity = (p.inactivity or 0) + dt
            feats = dict(speed_kmh=speed, acceleration_kmh_s=accel or 0.0, direction_change_deg=turn or 0.0,
                         inactivity_seconds=inactivity, distance_m=dist)
    return feats, speed, accel, turn, inactivity


def _anomaly_scores(feat_rows):
    """One model call for the whole batch (feat_rows: list of feature dicts) -> list of 0..1 scores."""
    bundle = model_bundle()
    if not bundle or not feat_rows:
        return [0.0] * len(feat_rows)
    X = np.array([[f[c] for c in bundle['features']] for f in feat_rows])
    fast = fast_scorer()
    raw = fast.decision_function(X) if fast is not None else bundle['model'].decision_function(pd.DataFrame(X, columns=bundle['features']))
    span = bundle['raw_max'] - bundle['raw_min'] + 1e-9
    return [float(v) for v in np.clip(1 - (raw - bundle['raw_min']) / span, 0, 1)]


def _route_deviation(t, lat, lon):
    if None in (t.start_lat, t.dest_lat):
        return 0.0
    # perpendicular distance from the straight start->destination line, saturating at 1.5 km
    k = math.cos(math.radians(lat))
    ax, ay, bx, by = t.start_lon * k, t.start_lat, t.dest_lon * k, t.dest_lat
    px, py = lon * k, lat
    L2 = (bx - ax) ** 2 + (by - ay) ** 2 or 1e-12
    u = max(0, min(1, ((px - ax) * (bx - ax) + (py - ay) * (by - ay)) / L2))
    return min(1.0, math.hypot(px - (ax + u * (bx - ax)), py - (ay + u * (by - ay))) * 111000 / 1500)


def assess_batch(db: Session, items):
    """Score many fixes with one state read, one model call and one set of writes.

    items: list of dict(tourist=Tourist, lat, lon, ts, sos=0.0, hour=None). Returns one result dict per item, in
    input order. Fixes are processed in timestamp order so each tourist's feature chain is correct; a fix older than
    the tourist's latest state is stored as history but never rewinds "latest"; an exact duplicate is skipped.
    """
    if not items:
        return []
    ids = {it['tourist'].tourist_id for it in items}
    states = {st.tourist_id: st for st in db.query(m.TouristState).filter(m.TouristState.tourist_id.in_(ids))}
    work, rows = {}, []
    for i in sorted(range(len(items)), key=lambda k: (as_utc(items[k]['ts']), k)):
        it = items[i]
        t, ts, lat, lon = it['tourist'], as_utc(it['ts']), it['lat'], it['lon']
        w = work.get(t.tourist_id)
        if w is None:
            st = states.get(t.tourist_id)
            w = work[t.tourist_id] = dict(
                recent=list(st.recent or []) if st else [], trail=list(st.trail or []) if st else [],
                updated=as_utc(st.updated_at) if st and st.updated_at else None,
                level=st.risk_level if st else None, bucket=int(as_utc(st.updated_at).timestamp() // 60) if st and st.updated_at else None)
        if w['updated'] is not None and ts == w['updated']:
            rows.append(dict(i=i, dup=True))
            continue
        feats, speed, accel, turn, inactivity = _features([SimpleNamespace(**r) for r in w['recent']][::-1], lat, lon, ts)
        rows.append(dict(i=i, t=t, lat=lat, lon=lon, ts=ts, feats=feats, speed=speed, accel=accel, turn=turn,
                         inactivity=inactivity, sos=float(it.get('sos', 0.0)), hour=it.get('hour')))
        if w['updated'] is None or ts >= w['updated']:  # only the newest fix advances "latest"
            w['recent'] = w['recent'][-2:] + [dict(ts=ts.isoformat(), lat=lat, lon=lon, speed=speed, inactivity=inactivity)]
            w['trail'] = w['trail'][-39:] + [[lat, lon]]
            w['updated'], w['last_i'] = ts, i

    live = [r for r in rows if not r.get('dup')]
    scores = iter(_anomaly_scores([r['feats'] for r in live if r['feats']]))
    results = [None] * len(items)
    for r in rows:
        if r.get('dup'):
            results[r['i']] = dict(duplicate=True)
            continue
        t, ts, lat, lon = r['t'], r['ts'], r['lat'], r['lon']
        anomaly = next(scores) if r['feats'] else 0.0
        geo_risk, geo_name = 0.0, None
        geo_rows, tree = geofence_index(db, t.location_slug)
        for gi in tree.query(Point(lon, lat), predicate='within'):
            name, risk, _ = geo_rows[int(gi)]
            if risk >= geo_risk:
                geo_risk, geo_name = risk, name
        hour = r['hour']
        if hour is None:
            try:
                hour = ts.astimezone(ZoneInfo(location_cfg(t.location_slug)['location'].get('timezone', 'UTC'))).hour
            except Exception:
                hour = ts.hour
        inputs = dict(movement_anomaly=round(anomaly, 4), geofence_risk=geo_risk,
                      route_deviation=round(_route_deviation(t, lat, lon), 4),
                      inactivity=round(min(1.0, r['inactivity'] / 900), 4),
                      historical_context=historical_context(db, t.location_slug),
                      night_flag=1.0 if (hour >= 22 or hour <= 5) else 0.0, sos=r['sos'])
        res = calculate_risk(**inputs, weights=location_cfg(t.location_slug)['risk']['weights'])
        db.add(m.TouristLocation(tourist_id=t.tourist_id, recorded_at=ts, latitude=lat, longitude=lon, speed_kmh=r['speed'],
                                 acceleration_kmh_s=r['accel'], direction_change_deg=r['turn'], inactivity_seconds=r['inactivity']))
        # Risk history is sampled (level change, SOS, or a new minute) -- the full-rate value lives in tourist_state.
        w, bucket = work[t.tourist_id], int(ts.timestamp() // 60)
        if res.level != w['level'] or r['sos'] or bucket != w['bucket']:
            db.add(m.RiskAssessment(tourist_id=t.tourist_id, assessed_at=ts, risk_score=res.score, risk_level=res.level, **inputs))
        w['level'], w['bucket'] = res.level, bucket
        results[r['i']] = dict(risk_score=res.score, risk_level=res.level, inputs=inputs, geofence=geo_name)
        if w.get('last_i') == r['i']:
            w['final'] = dict(lat=lat, lon=lon, speed=r['speed'], ts=ts, score=res.score, level=res.level, inputs=inputs)

    for tid, w in work.items():
        fin = w.get('final')
        if not fin:
            continue
        st = states.get(tid) or m.TouristState(tourist_id=tid)
        st.latitude, st.longitude, st.speed_kmh, st.updated_at = fin['lat'], fin['lon'], fin['speed'], fin['ts']
        st.risk_score, st.risk_level, st.factors = fin['score'], fin['level'], fin['inputs']
        st.trail, st.recent = w['trail'], w['recent']  # reassigned lists, so the JSON change is detected
        db.add(st)
    db.flush()  # make new state rows visible to the next call in the same session
    return results


def assess(db: Session, tourist: m.Tourist, lat, lon, ts, sos=0.0, hour=None):
    """Score one fix (synchronous paths: SOS, demo replay). Same code path as the batch pipeline."""
    return assess_batch(db, [dict(tourist=tourist, lat=lat, lon=lon, ts=ts, sos=sos, hour=hour)])[0]
