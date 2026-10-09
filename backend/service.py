"""Shared helpers for the API routers."""
import hashlib, hmac, json, os
from datetime import datetime, timezone
from fastapi import Header, HTTPException
from . import ledger, models as m, scoring


def iso(d):
    if not d:
        return None
    if d.tzinfo is None:  # SQLite drops tzinfo; every stored time is UTC
        d = d.replace(tzinfo=timezone.utc)
    return d.isoformat()


def require_ops(x_ops_token: str | None = Header(None)):
    """Operator endpoints are open only when OPS_TOKEN is unset (local dev)."""
    tok = os.getenv('OPS_TOKEN')
    if tok and not (x_ops_token and hmac.compare_digest(x_ops_token, tok)):
        raise HTTPException(401, 'operator token required')


def incident_out(i: m.Incident):
    return dict(id=i.id, tourist_id=i.tourist_id, incident_type=i.incident_type, severity=i.severity,
                latitude=i.latitude, longitude=i.longitude, status=i.status, description=i.description,
                created_at=iso(i.created_at), resolved_at=iso(i.resolved_at))


def queue_block(db, block_type, ref, payload_hash):
    db.info.setdefault('pending_ledger', []).append((block_type, ref, payload_hash))


def finish(db):
    """Commit, then write queued ledger blocks (separate transactions, so no SQLite write-lock clash)."""
    db.commit()
    for args in db.info.pop('pending_ledger', []):
        ledger.append(*args)


def audit(db, incident, action, actor, extra=None):
    """Append-only audit row with a SHA-256 of the canonical incident JSON; the hash is also chained in the ledger."""
    snap = json.dumps(incident_out(incident) | {'action': action}, sort_keys=True, separators=(',', ':'))
    digest = hashlib.sha256(snap.encode()).hexdigest()
    db.add(m.IncidentAudit(incident_id=incident.id, action=action, actor=actor, details={'sha256': digest, **(extra or {})}))
    queue_block(db, f'INCIDENT_{action}', incident.tourist_id or '-', digest)


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


def process_fix(db, tourist, lat, lon, ts: datetime, sos=0.0, hour=None):
    res = scoring.assess(db, tourist, lat, lon, ts, sos=sos, hour=hour)
    if res['risk_level'] == 'HIGH' and not sos:
        open_incident(db, tourist.tourist_id, 'HIGH_RISK', 'HIGH', lat, lon,
                      f"Risk score {res['risk_score']}" + (f" in {res['geofence']}" if res['geofence'] else ''))
    return res
