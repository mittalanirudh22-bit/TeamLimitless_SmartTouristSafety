"""Traveller-facing API: register -> blockchain ID -> opt-in tracking."""
import hashlib, json, secrets, time
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from . import ledger, models as m, scoring
from .database import get_db
from .service import finish, incident_out, iso, open_incident, process_fix, queue_block

router = APIRouter()
PHONE = r'^\+?[0-9 \-]{7,18}$'
_hits: dict[str, list[float]] = {}


class RegisterIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=80)
    nationality: str = Field(min_length=2, max_length=60)
    phone: str = Field(pattern=PHONE)
    email: str | None = Field(None, max_length=120)
    emergency_name: str = Field(min_length=2, max_length=80)
    emergency_phone: str = Field(pattern=PHONE)
    consent: bool


class FixIn(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy: float | None = Field(None, ge=0)
    timestamp: datetime | None = None


class SosIn(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    description: str | None = Field(None, max_length=300)


def chain_id(block_hash: str) -> str:
    h = block_hash[:16].upper()
    return 'TLB-' + '-'.join(h[i:i + 4] for i in range(0, 16, 4))


def current_traveller(x_tracking_token: str | None = Header(None), db: Session = Depends(get_db)):
    if not x_tracking_token:
        raise HTTPException(401, 'tracking token required')
    reg = db.query(m.Registration).filter_by(token_hash=ledger.sha256(x_tracking_token)).first()
    if not reg:
        raise HTTPException(401, 'invalid tracking token')
    return reg, db.get(m.Tourist, reg.tourist_id)


def profile(db, reg, t):
    ra = db.query(m.RiskAssessment).filter_by(tourist_id=t.tourist_id).order_by(m.RiskAssessment.assessed_at.desc()).first()
    rows = (db.query(m.TouristLocation).filter_by(tourist_id=t.tourist_id)
            .order_by(m.TouristLocation.recorded_at.desc()).limit(60).all())
    inc = db.query(m.Incident).filter(m.Incident.tourist_id == t.tourist_id, m.Incident.status != 'RESOLVED').all()
    return dict(
        tourist_id=t.tourist_id, name=reg.full_name, nationality=reg.nationality, status=t.status,
        blockchain_id=reg.blockchain_id, registered_at=iso(reg.registered_at),
        emergency_name=reg.emergency_name, emergency_phone=reg.emergency_phone,
        latitude=rows[0].latitude if rows else None, longitude=rows[0].longitude if rows else None,
        trail=[[r.latitude, r.longitude] for r in rows][::-1],
        risk_score=ra.risk_score if ra else None, risk_level=ra.risk_level if ra else None,
        factors={k: getattr(ra, k) for k in ('movement_anomaly', 'geofence_risk', 'route_deviation', 'inactivity',
                                             'historical_context', 'night_flag', 'sos')} if ra else None,
        incidents=[incident_out(i) for i in inc])


@router.post('/register')
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db)):
    if not body.consent:
        raise HTTPException(400, 'Consent to location tracking is required to register.')
    ip = (request.headers.get('x-forwarded-for') or request.client.host or '?').split(',')[0].strip()
    now_s = time.time()
    _hits[ip] = [t for t in _hits.get(ip, []) if now_s - t < 3600]
    if len(_hits[ip]) >= 10:
        raise HTTPException(429, 'Too many registrations from this address; try again later.')
    _hits[ip].append(now_s)

    tid = 'TR' + secrets.token_hex(4).upper()
    salt, token = secrets.token_hex(16), secrets.token_urlsafe(24)
    registered = datetime.now(timezone.utc)
    # PII never enters the ledger: only a salted hash of the canonical registration record.
    record = json.dumps({'tourist_id': tid, 'name': body.full_name, 'nationality': body.nationality, 'phone': body.phone,
                         'registered_at': registered.isoformat(), 'salt': salt}, sort_keys=True, separators=(',', ':'))
    block = ledger.append('REGISTRATION', tid, ledger.sha256(record))
    db.add(m.Tourist(tourist_id=tid, location_slug='bhopal', display_name=body.full_name, status='REGISTERED'))
    db.flush()
    db.add(m.Registration(
        tourist_id=tid, full_name=body.full_name, nationality=body.nationality, phone=body.phone, email=body.email,
        emergency_name=body.emergency_name, emergency_phone=body.emergency_phone, blockchain_id=chain_id(block.hash),
        token_hash=ledger.sha256(token), salt=salt, consent_at=registered, registered_at=registered))
    db.commit()
    return dict(tourist_id=tid, blockchain_id=chain_id(block.hash), tracking_token=token,
                block=ledger.block_out(block))


@router.get('/me')
def me(who=Depends(current_traveller), db: Session = Depends(get_db)):
    return profile(db, *who)


def _set_status(db, who, status, block_type):
    reg, t = who
    if t.status != status:
        t.status = status
        queue_block(db, block_type, t.tourist_id,
                    ledger.sha256(f'{t.tourist_id}|{status}|{datetime.now(timezone.utc).isoformat()}'))
    finish(db)
    return profile(db, reg, t)


@router.post('/me/start')
def start(who=Depends(current_traveller), db: Session = Depends(get_db)):
    return _set_status(db, who, 'TRACKING', 'TRACKING_STARTED')


@router.post('/me/stop')
def stop(who=Depends(current_traveller), db: Session = Depends(get_db)):
    return _set_status(db, who, 'STOPPED', 'TRACKING_STOPPED')


@router.post('/me/location')
def location(fix: FixIn, who=Depends(current_traveller), db: Session = Depends(get_db)):
    reg, t = who
    if t.status != 'TRACKING':
        raise HTTPException(409, 'tracking has not been started')
    if fix.accuracy is not None and fix.accuracy > 150:
        return {'ignored': 'GPS accuracy too low', 'accuracy_m': fix.accuracy}
    res = process_fix(db, t, fix.latitude, fix.longitude, fix.timestamp or datetime.now(timezone.utc))
    finish(db)
    return res


@router.post('/me/sos')
def sos(body: SosIn, who=Depends(current_traveller), db: Session = Depends(get_db)):
    reg, t = who
    res = scoring.assess(db, t, body.latitude, body.longitude, datetime.now(timezone.utc), sos=1.0)
    inc = open_incident(db, t.tourist_id, 'SOS', 'CRITICAL', body.latitude, body.longitude,
                        body.description or 'Traveller pressed SOS')
    finish(db)
    return res | {'incident': incident_out(inc)}
