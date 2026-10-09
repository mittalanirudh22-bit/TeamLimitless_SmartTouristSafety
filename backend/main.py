import os
from datetime import datetime, timezone
import yaml
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from ml.risk_engine import calculate_risk
from . import ledger, models as m, scoring, simulation
from .database import ROOT, SessionLocal, engine, get_db
from .seed import seed, DEMO
from .service import audit, finish, incident_out, iso, open_incident, process_fix, require_ops
from .travellers import router as travellers_router

DEFAULT_LOCATION = os.getenv('DEFAULT_LOCATION', 'bhopal')
DEMO_IDS = [t for t, _ in DEMO]
app = FastAPI(title='Team Limitless Smart Tourist Safety API', version='4.0.0')
app.include_router(travellers_router, prefix='/api/travellers')


@app.on_event('startup')
def startup():
    m.Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db, DEFAULT_LOCATION)
    ledger.ensure_genesis()


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


def demo_tourist(db, tid):
    """The unauthenticated ingest endpoints only serve the demo tourists, never registered travellers."""
    if tid not in DEMO_IDS:
        raise HTTPException(403, 'use /api/travellers/me/* with your tracking token')
    t = db.get(m.Tourist, tid)
    if not t:
        raise HTTPException(404, 'unknown tourist')
    return t


@app.get('/api/info')
def info():
    return {'project': 'Team Limitless', 'status': 'running', 'pilot_location': 'Bhopal', 'design': 'location-agnostic',
            'model_loaded': scoring.model_bundle() is not None, 'database': engine.dialect.name,
            'ops_auth': bool(os.getenv('OPS_TOKEN'))}


@app.get('/health')
def health():
    return {'status': 'healthy'}


@app.get('/config/{location}')
def config(location: str):
    path = ROOT / 'locations' / location / 'config.yaml'
    if not path.exists() or '/' in location or '.' in location:
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


# ---- public ledger verification (no PII) ----
@app.get('/api/ledger/verify')
def ledger_verify(db: Session = Depends(get_db)):
    return ledger.verify(db)


@app.get('/api/verify/{blockchain_id}')
def verify_id(blockchain_id: str, db: Session = Depends(get_db)):
    reg = db.query(m.Registration).filter_by(blockchain_id=blockchain_id.strip().upper()).first()
    if not reg:
        raise HTTPException(404, 'blockchain ID not found')
    blk = db.query(m.LedgerBlock).filter_by(block_type='REGISTRATION', ref=reg.tourist_id).first()
    chain = ledger.verify(db)
    return dict(blockchain_id=reg.blockchain_id, registered=True, registered_at=iso(reg.registered_at),
                block_index=blk.idx if blk else None, id_matches_block=bool(blk) and reg.blockchain_id.replace('-', '')[3:] == blk.hash[:16].upper(),
                chain_valid=chain['valid'], chain_length=chain['blocks'])


# ---- operator endpoints ----
@app.get('/api/ledger', dependencies=[Depends(require_ops)])
def ledger_list(limit: int = 25, db: Session = Depends(get_db)):
    rows = db.query(m.LedgerBlock).order_by(m.LedgerBlock.idx.desc()).limit(min(limit, 200)).all()
    return [ledger.block_out(b) for b in rows]


@app.get('/api/tourists', dependencies=[Depends(require_ops)])
def tourists(db: Session = Depends(get_db)):
    out = []
    regs = {r.tourist_id: r for r in db.query(m.Registration)}
    for t in db.query(m.Tourist).filter_by(location_slug=DEFAULT_LOCATION).order_by(m.Tourist.created_at, m.Tourist.tourist_id):
        loc = db.query(m.TouristLocation).filter_by(tourist_id=t.tourist_id).order_by(m.TouristLocation.recorded_at.desc()).first()
        ra = db.query(m.RiskAssessment).filter_by(tourist_id=t.tourist_id).order_by(m.RiskAssessment.assessed_at.desc()).first()
        trail = [[r.latitude, r.longitude] for r in db.query(m.TouristLocation).filter_by(tourist_id=t.tourist_id)
                 .order_by(m.TouristLocation.recorded_at.desc()).limit(40)][::-1]
        reg = regs.get(t.tourist_id)
        out.append(dict(tourist_id=t.tourist_id, name=t.display_name, status=t.status, registered=reg is not None,
                        blockchain_id=reg.blockchain_id if reg else None,
                        emergency_name=reg.emergency_name if reg else None, emergency_phone=reg.emergency_phone if reg else None,
                        latitude=loc.latitude if loc else None, longitude=loc.longitude if loc else None,
                        speed_kmh=loc.speed_kmh if loc else None, trail=trail,
                        risk_score=ra.risk_score if ra else None, risk_level=ra.risk_level if ra else None,
                        factors={k: getattr(ra, k) for k in ('movement_anomaly', 'geofence_risk', 'route_deviation', 'inactivity',
                                                             'historical_context', 'night_flag', 'sos')} if ra else None))
    return out


@app.post('/api/locations', dependencies=[Depends(require_ops)])
def ingest(fix: FixIn, db: Session = Depends(get_db)):
    t = demo_tourist(db, fix.tourist_id)
    res = process_fix(db, t, fix.latitude, fix.longitude, fix.timestamp or datetime.now(timezone.utc))
    finish(db)
    return res


@app.post('/api/sos', dependencies=[Depends(require_ops)])
def sos(body: SosIn, db: Session = Depends(get_db)):
    t = demo_tourist(db, body.tourist_id)
    res = scoring.assess(db, t, body.latitude, body.longitude, datetime.now(timezone.utc), sos=1.0)
    inc = open_incident(db, t.tourist_id, 'SOS', 'CRITICAL', body.latitude, body.longitude, body.description or 'Tourist pressed SOS')
    finish(db)
    return res | {'incident': incident_out(inc)}


@app.get('/api/incidents', dependencies=[Depends(require_ops)])
def incidents(status: str | None = None, db: Session = Depends(get_db)):
    q = db.query(m.Incident)
    if status:
        q = q.filter_by(status=status)
    return [incident_out(i) for i in q.order_by(m.Incident.id.desc()).limit(100)]


@app.post('/incidents', dependencies=[Depends(require_ops)])
def incident_legacy(payload: dict, db: Session = Depends(get_db)):
    tid = payload.get('tourist_id')
    if not tid or not db.get(m.Tourist, tid):
        raise HTTPException(422, 'valid tourist_id required')
    inc = open_incident(db, tid, payload.get('incident_type', 'MANUAL'), payload.get('severity', 'MEDIUM'),
                        payload.get('latitude'), payload.get('longitude'), payload.get('description'))
    finish(db)
    return {'status': inc.status, 'message': 'Incident accepted for response workflow.', 'incident': incident_out(inc)}


@app.patch('/api/incidents/{iid}', dependencies=[Depends(require_ops)])
def update_incident(iid: int, body: IncidentUpdate, db: Session = Depends(get_db)):
    inc = db.get(m.Incident, iid)
    if not inc:
        raise HTTPException(404, 'incident not found')
    inc.status = body.status
    inc.resolved_at = datetime.now(timezone.utc) if body.status == 'RESOLVED' else None
    audit(db, inc, body.status, body.actor)
    finish(db)
    return incident_out(inc)


@app.get('/api/incidents/{iid}/audit', dependencies=[Depends(require_ops)])
def incident_audit(iid: int, db: Session = Depends(get_db)):
    return [dict(action=a.action, actor=a.actor, details=a.details, created_at=iso(a.created_at))
            for a in db.query(m.IncidentAudit).filter_by(incident_id=iid).order_by(m.IncidentAudit.id)]


@app.post('/api/simulate/step', dependencies=[Depends(require_ops)])
def simulate_step(db: Session = Depends(get_db)):
    """Advance every demo tourist by one replayed GPS fix (controlled demo input, not live tracking)."""
    out = {}
    for t in db.query(m.Tourist).filter(m.Tourist.tourist_id.in_(DEMO_IDS)):
        fx = simulation.next_fix(t.tourist_id)
        if not fx:
            continue
        t.start_lat, t.start_lon = fx['start']
        t.dest_lat, t.dest_lon = fx['end']
        out[t.tourist_id] = process_fix(db, t, fx['lat'], fx['lon'], fx['ts'], hour=fx['hour'])
    finish(db)
    return out


@app.post('/api/simulate/reset', dependencies=[Depends(require_ops)])
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
