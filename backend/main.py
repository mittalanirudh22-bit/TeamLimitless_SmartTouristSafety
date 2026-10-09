import hashlib, json, os
from datetime import datetime, timezone
from pathlib import Path
import yaml
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from ml.risk_engine import calculate_risk
from . import models as m, scoring, simulation
from .database import ROOT, SessionLocal, engine, get_db
from .seed import seed

DEFAULT_LOCATION = os.getenv('DEFAULT_LOCATION', 'bhopal')
app = FastAPI(title='Team Limitless Smart Tourist Safety API', version='3.1.0')


@app.on_event('startup')
def startup():
    m.Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db, DEFAULT_LOCATION)


class RiskRequest(BaseModel):
    movement_anomaly: float = Field(0, ge=0, le=1)
    geofence_risk: float = Field(0, ge=0, le=1)
    route_deviation: float = Field(0, ge=0, le=1)
    inactivity: float = Field(0, ge=0, le=1)
    historical_context: float = Field(0, ge=0, le=1)
    night_flag: float = Field(0, ge=0, le=1)
    sos: float = Field(0, ge=0, le=1)


class FixIn(BaseModel):
    tourist_id: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    timestamp: datetime | None = None


class SosIn(BaseModel):
    tourist_id: str
    latitude: float
    longitude: float
    description: str | None = None


class IncidentUpdate(BaseModel):
    status: str = Field(pattern='^(OPEN|ACKNOWLEDGED|RESOLVED)$')
    actor: str = 'operator'


def iso(d):
    return d.isoformat() if d else None


def incident_out(i: m.Incident):
    return dict(id=i.id, tourist_id=i.tourist_id, incident_type=i.incident_type, severity=i.severity,
                latitude=i.latitude, longitude=i.longitude, status=i.status, description=i.description,
                created_at=iso(i.created_at), resolved_at=iso(i.resolved_at))


def audit(db, incident, action, actor, extra=None):
    """Append-only audit row with a SHA-256 of the canonical incident JSON (tamper-evidence; hash only, no PII on-chain)."""
    snap = json.dumps(incident_out(incident) | {'action': action}, sort_keys=True, separators=(',', ':'))
    db.add(m.IncidentAudit(incident_id=incident.id, action=action, actor=actor,
                           details={'sha256': hashlib.sha256(snap.encode()).hexdigest(), **(extra or {})}))


def open_incident(db, tourist_id, kind, severity, lat, lon, desc):
    dup = db.query(m.Incident).filter(m.Incident.tourist_id == tourist_id, m.Incident.incident_type == kind,
                                      m.Incident.status != 'RESOLVED').first()
    if dup:
        return dup
    inc = m.Incident(tourist_id=tourist_id, incident_type=kind, severity=severity, latitude=lat, longitude=lon, description=desc)
    db.add(inc)
    db.flush()
    audit(db, inc, 'CREATED', 'system')
    return inc


def process_fix(db, tourist, lat, lon, ts, sos=0.0, hour=None):
    res = scoring.assess(db, tourist, lat, lon, ts, sos=sos, hour=hour)
    if res['risk_level'] == 'HIGH' and not sos:
        open_incident(db, tourist.tourist_id, 'HIGH_RISK', 'HIGH', lat, lon,
                      f"Risk score {res['risk_score']}" + (f" in {res['geofence']}" if res['geofence'] else ''))
    return res


@app.get('/api/info')
def info():
    return {'project': 'Team Limitless', 'status': 'running', 'pilot_location': 'Bhopal', 'design': 'location-agnostic',
            'model_loaded': scoring.model_bundle() is not None, 'database': engine.dialect.name}


@app.get('/health')
def health():
    return {'status': 'healthy'}


@app.get('/config/{location}')
def config(location: str):
    path = ROOT / 'locations' / location / 'config.yaml'
    if not path.exists():
        raise HTTPException(404, 'location configuration not found')
    return yaml.safe_load(path.read_text(encoding='utf-8'))


@app.post('/risk')
def risk(req: RiskRequest):
    r = calculate_risk(**req.model_dump())
    return {'risk_score': r.score, 'risk_level': r.level}


@app.get('/api/geofences')
def geofences(db: Session = Depends(get_db)):
    return {'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'geometry': g.geojson, 'properties': dict(name=g.name, category=g.category, risk_level=g.risk_level, description=g.description)}
        for g in db.query(m.Geofence).filter_by(location_slug=DEFAULT_LOCATION)]}


@app.get('/api/tourists')
def tourists(db: Session = Depends(get_db)):
    out = []
    for t in db.query(m.Tourist).filter_by(location_slug=DEFAULT_LOCATION).order_by(m.Tourist.tourist_id):
        loc = db.query(m.TouristLocation).filter_by(tourist_id=t.tourist_id).order_by(m.TouristLocation.recorded_at.desc()).first()
        ra = db.query(m.RiskAssessment).filter_by(tourist_id=t.tourist_id).order_by(m.RiskAssessment.assessed_at.desc()).first()
        trail = [[r.latitude, r.longitude] for r in db.query(m.TouristLocation).filter_by(tourist_id=t.tourist_id)
                 .order_by(m.TouristLocation.recorded_at.desc()).limit(40)][::-1]
        out.append(dict(tourist_id=t.tourist_id, name=t.display_name, status=t.status,
                        latitude=loc.latitude if loc else None, longitude=loc.longitude if loc else None,
                        speed_kmh=loc.speed_kmh if loc else None, trail=trail,
                        risk_score=ra.risk_score if ra else None, risk_level=ra.risk_level if ra else None,
                        factors={k: getattr(ra, k) for k in ('movement_anomaly', 'geofence_risk', 'route_deviation', 'inactivity',
                                                             'historical_context', 'night_flag', 'sos')} if ra else None))
    return out


@app.post('/api/locations')
def ingest(fix: FixIn, db: Session = Depends(get_db)):
    t = db.get(m.Tourist, fix.tourist_id)
    if not t:
        raise HTTPException(404, 'unknown tourist')
    res = process_fix(db, t, fix.latitude, fix.longitude, fix.timestamp or datetime.now(timezone.utc))
    db.commit()
    return res


@app.post('/api/sos')
def sos(body: SosIn, db: Session = Depends(get_db)):
    t = db.get(m.Tourist, body.tourist_id)
    if not t:
        raise HTTPException(404, 'unknown tourist')
    res = scoring.assess(db, t, body.latitude, body.longitude, datetime.now(timezone.utc), sos=1.0)
    inc = open_incident(db, t.tourist_id, 'SOS', 'CRITICAL', body.latitude, body.longitude, body.description or 'Tourist pressed SOS')
    db.commit()
    return res | {'incident': incident_out(inc)}


@app.get('/api/incidents')
def incidents(status: str | None = None, db: Session = Depends(get_db)):
    q = db.query(m.Incident)
    if status:
        q = q.filter_by(status=status)
    return [incident_out(i) for i in q.order_by(m.Incident.id.desc()).limit(100)]


@app.post('/incidents')
def incident_legacy(payload: dict, db: Session = Depends(get_db)):
    tid = payload.get('tourist_id')
    if not tid or not db.get(m.Tourist, tid):
        raise HTTPException(422, 'valid tourist_id required')
    inc = open_incident(db, tid, payload.get('incident_type', 'MANUAL'), payload.get('severity', 'MEDIUM'),
                        payload.get('latitude'), payload.get('longitude'), payload.get('description'))
    db.commit()
    return {'status': inc.status, 'message': 'Incident accepted for response workflow.', 'incident': incident_out(inc)}


@app.patch('/api/incidents/{iid}')
def update_incident(iid: int, body: IncidentUpdate, db: Session = Depends(get_db)):
    inc = db.get(m.Incident, iid)
    if not inc:
        raise HTTPException(404, 'incident not found')
    inc.status = body.status
    inc.resolved_at = datetime.now(timezone.utc) if body.status == 'RESOLVED' else None
    audit(db, inc, body.status, body.actor)
    db.commit()
    return incident_out(inc)


@app.get('/api/incidents/{iid}/audit')
def incident_audit(iid: int, db: Session = Depends(get_db)):
    return [dict(action=a.action, actor=a.actor, details=a.details, created_at=iso(a.created_at))
            for a in db.query(m.IncidentAudit).filter_by(incident_id=iid).order_by(m.IncidentAudit.id)]


@app.post('/api/simulate/step')
def simulate_step(db: Session = Depends(get_db)):
    """Advance every demo tourist by one replayed GPS fix (controlled demo input, not live tracking)."""
    out = {}
    for t in db.query(m.Tourist).filter(m.Tourist.tourist_id.in_(['T001', 'T002', 'T003'])):
        fx = simulation.next_fix(t.tourist_id)
        if not fx:
            continue
        t.start_lat, t.start_lon = fx['start']
        t.dest_lat, t.dest_lon = fx['end']
        out[t.tourist_id] = process_fix(db, t, fx['lat'], fx['lon'], fx['ts'], hour=fx['hour'])
    db.commit()
    return out


@app.post('/api/simulate/reset')
def simulate_reset(db: Session = Depends(get_db)):
    if os.getenv('ALLOW_RESET') != '1':  # wipes incidents and history; off unless explicitly enabled
        raise HTTPException(403, 'reset disabled')
    for model in (m.IncidentAudit, m.Incident, m.RiskAssessment, m.TouristLocation):
        db.query(model).delete()
    db.commit()
    simulation.reset()
    return {'status': 'reset'}


DIST = ROOT / 'frontend' / 'dist'
if DIST.exists():
    app.mount('/assets', StaticFiles(directory=DIST / 'assets'), name='assets')

    @app.get('/{path:path}', include_in_schema=False)
    def spa(path: str):
        f = (DIST / path).resolve()
        return FileResponse(f if f.is_file() and DIST in f.parents else DIST / 'index.html')
else:
    @app.get('/', include_in_schema=False)
    def root():
        return info()
