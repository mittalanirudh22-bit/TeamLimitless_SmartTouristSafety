"""Turns raw GPS fixes into the seven risk-engine inputs, then scores them."""
import math
from datetime import timezone
from zoneinfo import ZoneInfo
from functools import lru_cache
import joblib, numpy as np, pandas as pd, yaml
from shapely.geometry import Point, shape
from sqlalchemy import func
from sqlalchemy.orm import Session
from . import models as m
from .database import ROOT
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
def location_cfg(slug):
    return yaml.safe_load((ROOT / 'locations' / slug / 'config.yaml').read_text())


def geofence_shapes(db: Session, slug):
    return [(g, shape(g.geojson)) for g in db.query(m.Geofence).filter_by(location_slug=slug)]


def historical_context(db: Session, slug):
    """Latest-year share of violent/personal-safety crime, scaled 0..1 -- a city-level prior, not a prediction."""
    y = db.query(func.max(m.SafetyContext.year)).filter_by(location_slug=slug).scalar()
    if y is None:
        return 0.0
    rows = db.query(m.SafetyContext).filter_by(location_slug=slug, year=y).all()
    tot = sum(r.crime_count for r in rows) or 1
    personal = sum(r.crime_count for r in rows if r.crime_category in ('robbery', 'assault', 'harassment'))
    return round(min(1.0, (personal / tot) * 2), 4)


def as_utc(dt):
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def assess(db: Session, tourist: m.Tourist, lat, lon, ts, sos=0.0, hour=None):
    """Persist a fix, compute features, anomaly score, risk. Returns (risk dict, features dict, geofence name)."""
    ts = as_utc(ts)
    prev = (db.query(m.TouristLocation).filter_by(tourist_id=tourist.tourist_id)
            .order_by(m.TouristLocation.recorded_at.desc()).limit(3).all())
    speed = accel = turn = None
    inactivity = 0.0
    if prev:
        p = prev[0]
        dt = (ts - as_utc(p.recorded_at)).total_seconds()
        if dt > 0:
            dist = hav(p.latitude, p.longitude, lat, lon)
            speed = dist / dt * 3.6
            if p.speed_kmh is not None:
                accel = abs(speed - p.speed_kmh) / dt
            if len(prev) > 1:
                q = prev[1]
                b1 = bearing(q.latitude, q.longitude, p.latitude, p.longitude)
                b2 = bearing(p.latitude, p.longitude, lat, lon)
                turn = abs((b2 - b1 + 180) % 360 - 180)
            if speed < 1:
                inactivity = (p.inactivity_seconds or 0) + dt
            feats = dict(speed_kmh=speed, acceleration_kmh_s=accel or 0.0, direction_change_deg=turn or 0.0,
                         inactivity_seconds=inactivity, distance_m=dist)
    anomaly = 0.0
    if speed is not None:
        bundle = model_bundle()
        if bundle:
            X = pd.DataFrame([feats])[bundle['features']]
            raw = float(bundle['model'].decision_function(X)[0])
            span = bundle['raw_max'] - bundle['raw_min'] + 1e-9
            anomaly = float(np.clip(1 - (raw - bundle['raw_min']) / span, 0, 1))
    else:
        feats = {}

    pt = Point(lon, lat)
    geo_risk, geo_name = 0.0, None
    for g, poly in geofence_shapes(db, tourist.location_slug):
        if poly.contains(pt) and (g.risk_level or 0) >= geo_risk:
            geo_risk, geo_name = g.risk_level or 0.0, g.name

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
    return dict(risk_score=r.score, risk_level=r.level, inputs=inputs, geofence=geo_name)
