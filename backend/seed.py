import json
import pandas as pd
import yaml
from sqlalchemy.orm import Session
from . import models as m
from .database import ROOT

DEMO = [('T001', 'Demo Tourist 1'), ('T002', 'Demo Tourist 2'), ('T003', 'Demo Tourist 3')]


def seed(db: Session, slug='bhopal'):
    if db.query(m.Location).filter_by(slug=slug).first():
        return
    cfg = yaml.safe_load((ROOT / 'locations' / slug / 'config.yaml').read_text())['location']
    db.add(m.Location(slug=slug, name=cfg['name'], state=cfg.get('state'), country=cfg['country']))
    db.flush()
    for tid, name in DEMO:
        db.add(m.Tourist(tourist_id=tid, location_slug=slug, display_name=name))
    gj = ROOT / 'locations' / slug / 'geofences.geojson'
    if gj.exists():
        for f in json.loads(gj.read_text())['features']:
            p = f['properties']
            db.add(m.Geofence(location_slug=slug, name=p['name'], category=p.get('category'),
                              risk_level=p.get('risk_level', 0), description=p.get('description'), geojson=f['geometry']))
    t = ROOT / 'data' / 'external' / 'tourism' / f'{slug}_tourism.csv'
    if t.exists():
        for r in pd.read_csv(t).itertuples():
            db.add(m.TourismContext(location_slug=slug, year=int(r.year), domestic_visitors=int(r.domestic_visitors),
                                    foreign_visitors=int(r.foreign_visitors), source='synthetic'))
    c = ROOT / 'data' / 'external' / 'ncrb' / f'{slug}_crime.csv'
    if c.exists():
        for r in pd.read_csv(c).itertuples():
            db.add(m.SafetyContext(location_slug=slug, year=int(r.year), crime_category=r.crime_category,
                                   crime_count=int(r.crime_count), source='synthetic'))
    db.commit()
