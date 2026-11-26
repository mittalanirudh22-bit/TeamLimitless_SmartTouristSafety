"""Public, view-only live location for family, opened from a link the traveller shared. No phone numbers, no ID."""
import hashlib
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from . import models as m, watchdog
from .database import get_db
from .service import iso
from .scoring import as_utc

router = APIRouter()


@router.get('/{token}')
def shared_view(token: str, db: Session = Depends(get_db)):
    link = db.query(m.ShareLink).filter_by(token_hash=hashlib.sha256(token.encode()).hexdigest()).first()
    now = datetime.now(timezone.utc)
    if not link or link.revoked_at is not None:
        raise HTTPException(404, 'This link was stopped or never existed.')
    if as_utc(link.expires_at) <= now:
        raise HTTPException(410, 'This link has expired.')
    t = db.get(m.Tourist, link.tourist_id)
    reg = db.query(m.Registration).filter_by(tourist_id=t.tourist_id).first()
    st = db.get(m.TouristState, t.tourist_id)
    open_types = sorted({i.incident_type for i in db.query(m.Incident.incident_type).filter(
        m.Incident.tourist_id == t.tourist_id, m.Incident.status != 'RESOLVED')})
    first = (reg.full_name if reg else t.display_name or 'Traveller').split()[0]
    return dict(name=first, city=t.location_slug, status=t.status,
                latitude=st.latitude if st else None, longitude=st.longitude if st else None,
                trail=(st.trail or []) if st else [], risk_level=st.risk_level if st else None,
                updated_at=iso(watchdog.last_heard(st)) if st else None, last_seen_s=watchdog.silent_for(st, now),
                signal=watchdog.signal(st, t.status, now), sos=('SOS' in open_types), open_alerts=open_types,
                destination=dict(latitude=t.dest_lat, longitude=t.dest_lon) if t.dest_lat is not None else None,
                expires_at=iso(link.expires_at))
