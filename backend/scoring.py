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


def assess(db: Session, tourist: m.Tourist, lat, lon, ts, sos=0.0, hour=None):
    """Persist a fix, compute features, anomaly score, risk. Returns (risk dict, features dict, geofence name)."""
    ts = as_utc(ts)
    state = db.get(m.TouristState, tourist.tourist_id)
    prev = [SimpleNamespace(**r) for r in (state.recent if state and state.recent else [])][::-1]  # newest first
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
    anomaly = 0.0
    if speed is not None:
        bundle = model_bundle()
        if bundle:
            x = [feats[f] for f in bundle['features']]
            fast = fast_scorer()
            if fast is not None:
                raw = float(fast.decision_function(np.array([x]))[0])
            else:
                raw = float(bundle['model'].decision_function(pd.DataFrame([x], columns=bundle['features']))[0])
            span = bundle['raw_max'] - bundle['raw_min'] + 1e-9
            anomaly = float(np.clip(1 - (raw - bundle['raw_min']) / span, 0, 1))

    pt = Point(lon, lat)
    geo_risk, geo_name = 0.0, None
    rows, tree = geofence_index(db, tourist.location_slug)
    for i in tree.query(pt, predicate='within'):
        name, risk, _ = rows[int(i)]
        if risk >= geo_risk:
            geo_risk, geo_name = risk, name

    route_dev = 0.0
    if None not in (tourist.start_lat, tourist.dest_lat):
        # perpendicular distance from the straight start->destination line, saturating at 1.5 km
        k = math.cos(math.radians(lat))
        ax, ay, bx, by = tourist.start_lon * k, tourist.start_lat, tourist.dest_lon * k, tourist.dest_lat
        px, py = lon * k, lat
        L2 = (bx - ax) ** 2 + (by - ay) ** 2 or 1e-12
        t = max(0, min(1, ((px - ax) * (bx - ax) + (py - ay) * (by - ay)) / L2))
        d = math.hypot(px - (ax + t * (bx - ax)), py - (ay + t * (by - ay))) * 111000
        route_dev = min(1.0, d / 1500)

    if hour is None:
        try:
            hour = ts.astimezone(ZoneInfo(location_cfg(tourist.location_slug)['location'].get('timezone', 'UTC'))).hour
        except Exception:
            hour = ts.hour
    h = hour
    inputs = dict(movement_anomaly=round(anomaly, 4), geofence_risk=geo_risk, route_deviation=round(route_dev, 4),
                  inactivity=round(min(1.0, inactivity / 900), 4), historical_context=historical_context(db, tourist.location_slug),
                  night_flag=1.0 if (h >= 22 or h <= 5) else 0.0, sos=float(sos))
    weights = location_cfg(tourist.location_slug)['risk']['weights']
    r = calculate_risk(**inputs, weights=weights)

    db.add(m.TouristLocation(tourist_id=tourist.tourist_id, recorded_at=ts, latitude=lat, longitude=lon,
                             speed_kmh=speed, acceleration_kmh_s=accel, direction_change_deg=turn,
                             inactivity_seconds=inactivity))
    db.add(m.RiskAssessment(tourist_id=tourist.tourist_id, assessed_at=ts, risk_score=r.score, risk_level=r.level, **inputs))

    if state is None:
        state = m.TouristState(tourist_id=tourist.tourist_id)
    recent = (state.recent or [])[-2:] + [dict(ts=ts.isoformat(), lat=lat, lon=lon, speed=speed, inactivity=inactivity)]
    if not state.updated_at or ts >= as_utc(state.updated_at):  # a late/out-of-order fix must not rewind "latest"
        state.latitude, state.longitude, state.speed_kmh, state.updated_at = lat, lon, speed, ts
        state.risk_score, state.risk_level, state.factors = r.score, r.level, inputs
        state.trail = (state.trail or [])[-39:] + [[lat, lon]]  # reassigned (not appended) so the JSON change is detected
        state.recent = recent
    db.add(state)
    return dict(risk_score=r.score, risk_level=r.level, inputs=inputs, geofence=geo_name)
