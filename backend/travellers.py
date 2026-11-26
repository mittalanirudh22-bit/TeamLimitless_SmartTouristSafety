"""Traveller-facing API: register -> blockchain ID -> opt-in tracking."""
import hashlib, json, os, secrets, time
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from . import guide, ingest, ledger, models as m, scoring, triage
from .database import get_db
from .service import audit, finish, incident_out, iso, open_incident, process_fix, queue_block

router = APIRouter()
DEFAULT_LOCATION = os.getenv('DEFAULT_LOCATION', 'bhopal')
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
    city: str | None = Field(None, max_length=40)  # trip city slug; defaults to the pilot city


class FixIn(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy: float | None = Field(None, ge=0)
    timestamp: datetime | None = None
    battery: int | None = Field(None, ge=0, le=100)  # phone battery %, if the browser reports it


class DestinationIn(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class SosIn(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    description: str | None = Field(None, max_length=300)
    message: str | None = Field(None, max_length=500)  # what's happening, typed or spoken, any language


class SosMessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class ShareIn(BaseModel):
    hours: int = Field(24, ge=1, le=72)


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
    st = db.get(m.TouristState, t.tourist_id)
    inc = db.query(m.Incident).filter(m.Incident.tourist_id == t.tourist_id, m.Incident.status != 'RESOLVED').all()
    return dict(
        tourist_id=t.tourist_id, name=reg.full_name, nationality=reg.nationality, status=t.status, city=t.location_slug,
        destination=dict(latitude=t.dest_lat, longitude=t.dest_lon) if t.dest_lat is not None else None,
        blockchain_id=reg.blockchain_id, registered_at=iso(reg.registered_at),
        emergency_name=reg.emergency_name, emergency_phone=reg.emergency_phone,
        latitude=st.latitude if st else None, longitude=st.longitude if st else None,
        trail=(st.trail or []) if st else [],
        risk_score=st.risk_score if st else None, risk_level=st.risk_level if st else None,
        factors=st.factors if st else None, incidents=[incident_out(i) for i in inc])


@router.post('/register')
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db)):
    if not body.consent:
        raise HTTPException(400, 'Consent to location tracking is required to register.')
    city = (body.city or DEFAULT_LOCATION).strip().lower()
    if city not in guide.location_slugs():
        raise HTTPException(422, f'Safe Tour does not cover "{city}" yet.')
    ip = (request.headers.get('x-forwarded-for') or request.client.host or '?').split(',')[0].strip()
    limit, rc = int(os.getenv('REGISTER_LIMIT_PER_HOUR', '10')), ingest.redis_client()
    if rc is not None:  # shared across every web process
        n = rc.incr(f'limitless:rl:reg:{ip}')
        if n == 1:
            rc.expire(f'limitless:rl:reg:{ip}', 3600)
        over = n > limit
    else:
        now_s = time.time()
        _hits[ip] = [t for t in _hits.get(ip, []) if now_s - t < 3600]
        over = len(_hits[ip]) >= limit
        _hits[ip].append(now_s)
    if over:
        raise HTTPException(429, 'Too many registrations from this address; try again later.')

    tid = 'TR' + secrets.token_hex(4).upper()
    salt, token = secrets.token_hex(16), secrets.token_urlsafe(24)
    registered = datetime.now(timezone.utc)
    # PII never enters the ledger: only a salted hash of the canonical registration record.
    record = json.dumps({'tourist_id': tid, 'name': body.full_name, 'nationality': body.nationality, 'phone': body.phone,
                         'registered_at': registered.isoformat(), 'salt': salt}, sort_keys=True, separators=(',', ':'))
    block = ledger.append('REGISTRATION', tid, ledger.sha256(record))
    db.add(m.Tourist(tourist_id=tid, location_slug=city, display_name=body.full_name, status='REGISTERED'))
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
    _auth.pop(reg.token_hash, None)
    return profile(db, reg, t)


@router.post('/me/destination')
def set_destination(body: DestinationIn, who=Depends(current_traveller), db: Session = Depends(get_db)):
    """Tell the safety engine where the traveller is heading (from the trip planner). Route deviation is then
    measured from where they are now to that destination."""
    reg, t = who
    st = db.get(m.TouristState, t.tourist_id)
    if not st or st.latitude is None:
        raise HTTPException(409, 'Start tracking first, so the safety team knows where your route begins.')
    t.start_lat, t.start_lon = st.latitude, st.longitude
    t.dest_lat, t.dest_lon = body.latitude, body.longitude
    db.commit()
    return profile(db, reg, t)


@router.delete('/me/destination')
def clear_destination(who=Depends(current_traveller), db: Session = Depends(get_db)):
    reg, t = who
    t.start_lat = t.start_lon = t.dest_lat = t.dest_lon = None
    db.commit()
    return profile(db, reg, t)


@router.post('/me/start')
def start(who=Depends(current_traveller), db: Session = Depends(get_db)):
    return _set_status(db, who, 'TRACKING', 'TRACKING_STARTED')


@router.post('/me/stop')
def stop(who=Depends(current_traveller), db: Session = Depends(get_db)):
    return _set_status(db, who, 'STOPPED', 'TRACKING_STOPPED')


_auth: dict[str, tuple[float, str, str]] = {}  # token_hash -> (expires, tourist_id, status); keeps ingest off the DB
AUTH_TTL = 3.0


def traveller_light(x_tracking_token: str | None = Header(None), db: Session = Depends(get_db)):
    if not x_tracking_token:
        raise HTTPException(401, 'tracking token required')
    key, now_s = ledger.sha256(x_tracking_token), time.monotonic()
    hit = _auth.get(key)
    if hit and hit[0] > now_s:
        return hit[1], hit[2]
    reg = db.query(m.Registration).filter_by(token_hash=key).first()
    if not reg:
        raise HTTPException(401, 'invalid tracking token')
    status = db.get(m.Tourist, reg.tourist_id).status
    if len(_auth) > 20000:
        _auth.clear()
    _auth[key] = (now_s + AUTH_TTL, reg.tourist_id, status)
    return reg.tourist_id, status


@router.post('/me/location', status_code=202)
def location(fix: FixIn, who=Depends(traveller_light)):
    """Validate and enqueue; scoring happens in the ingest workers (see ingest.py). Poll /me for the result."""
    tid, status = who
    if status != 'TRACKING':
        raise HTTPException(409, 'tracking has not been started')
    now = datetime.now(timezone.utc)
    weak = fix.accuracy is not None and fix.accuracy > 150
    entry = dict(tid=tid, lat=fix.latitude, lon=fix.longitude, ts=(fix.timestamp or now).isoformat(), seen=now.isoformat(),
                 battery=fix.battery, acc=fix.accuracy)
    if weak:  # too vague to place the traveller, but it still proves the phone is alive (keeps the watchdog quiet)
        entry |= dict(heartbeat=True, ts=now.isoformat())
    try:
        ingest.enqueue(entry)
    except ingest.Backpressure:
        raise HTTPException(503, 'Server busy; retry shortly.', headers={'Retry-After': '5'})
    if weak:
        return {'queued': True, 'ignored': 'GPS accuracy too low', 'accuracy_m': fix.accuracy, 'counted_as_alive': True}
    return {'queued': True}


@router.post('/me/sos')
def sos(body: SosIn, who=Depends(current_traveller), db: Session = Depends(get_db)):
    reg, t = who
    res = scoring.assess(db, t, body.latitude, body.longitude, datetime.now(timezone.utc), sos=1.0)
    inc = open_incident(db, t.tourist_id, 'SOS', 'CRITICAL', body.latitude, body.longitude,
                        body.description or 'Traveller pressed SOS')
    if body.message:
        _triage(db, t, inc, body.message)
    finish(db)
    return res | {'incident': incident_out(inc)}


def _triage(db, t, inc, text):
    """Label an SOS from the traveller's own words. Labels and flags only: the SOS stays CRITICAL."""
    try:
        g = guide.get_guide(t.location_slug)
    except HTTPException:
        g = None
    inc.message = ((inc.message + '\n') if inc.message else '') + text.strip()[:500]
    every = [triage.classify(x, g) for x in inc.message.split('\n')]  # summarise all messages, not just the latest
    r = every[-1]
    cats = list(dict.fromkeys(x['category'] for x in every if x['category'] != 'other')) or ['other']
    places = list(dict.fromkeys(p['name'] for x in every for p in x['places']))
    urgent = any(x['urgent'] for x in every)
    inc.category = cats[-1]
    where = f" Mentions: {', '.join(places)}." if places else ''
    inc.description = (f"SOS: {', then '.join(triage.CATEGORIES[c] for c in cats)}{', possibly life-threatening' if urgent else ''}. "
                       f"Latest: \"{text.strip()[:160]}\"{where}")
    audit(db, inc, 'UPDATED', 'traveller', {'category': inc.category, 'urgent': r['urgent'], 'confidence': r['confidence']})
    return r


@router.post('/me/sos/message')
def sos_message(body: SosMessageIn, who=Depends(current_traveller), db: Session = Depends(get_db)):
    """Add what's happening to an SOS already raised, so one tap is never delayed by typing."""
    reg, t = who
    inc = (db.query(m.Incident).filter(m.Incident.tourist_id == t.tourist_id, m.Incident.incident_type == 'SOS',
                                       m.Incident.status != 'RESOLVED').order_by(m.Incident.id.desc()).first())
    if not inc:
        raise HTTPException(404, 'No open SOS. Press SOS first.')
    r = _triage(db, t, inc, body.text)
    finish(db)
    return {'incident': incident_out(inc), 'triage': r}


@router.post('/me/share')
def create_share(body: ShareIn, who=Depends(current_traveller), db: Session = Depends(get_db)):
    """A view-only link to the traveller's live location for family. The token is shown once; only its hash is kept."""
    reg, t = who
    now = datetime.now(timezone.utc)
    active = db.query(m.ShareLink).filter(m.ShareLink.tourist_id == t.tourist_id, m.ShareLink.revoked_at.is_(None),
                                          m.ShareLink.expires_at > now).count()
    if active >= 5:
        raise HTTPException(409, 'You already have 5 active share links. Stop one first.')
    token = secrets.token_urlsafe(18)
    link = m.ShareLink(tourist_id=t.tourist_id, token_hash=hashlib.sha256(token.encode()).hexdigest(),
                       created_at=now, expires_at=now + timedelta(hours=body.hours))
    db.add(link)
    db.commit()
    return dict(id=link.id, token=token, expires_at=iso(link.expires_at))


@router.get('/me/share')
def list_shares(who=Depends(current_traveller), db: Session = Depends(get_db)):
    reg, t = who
    now = datetime.now(timezone.utc)
    rows = db.query(m.ShareLink).filter(m.ShareLink.tourist_id == t.tourist_id, m.ShareLink.revoked_at.is_(None),
                                        m.ShareLink.expires_at > now).order_by(m.ShareLink.id)
    return [dict(id=r.id, created_at=iso(r.created_at), expires_at=iso(r.expires_at)) for r in rows]


@router.delete('/me/share/{link_id}')
def revoke_share(link_id: int, who=Depends(current_traveller), db: Session = Depends(get_db)):
    reg, t = who
    link = db.get(m.ShareLink, link_id)
    if not link or link.tourist_id != t.tourist_id:
        raise HTTPException(404, 'share link not found')
    link.revoked_at = datetime.now(timezone.utc)
    db.commit()
    return {'revoked': link_id}
