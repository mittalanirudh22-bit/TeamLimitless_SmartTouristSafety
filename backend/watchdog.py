"""Signal-lost watchdog: notices when a tracked phone goes silent.

The server only scores a traveller when a location arrives, so a phone that is switched off, runs out of battery or loses
signal would otherwise stay frozen on the map at its last (often LOW) risk level. While tracking is on, the app sends a
location at least every 30 seconds, so a long silence means something is wrong. Pressing "Stop tracking" first is the
normal way to go offline and never raises an alert.

Escalation, per traveller with tracking on:
  * SIGNAL_LOST_S of silence      -> shown as "signal lost" on the operator dashboard
  * ALERT_RISKY_S of silence      -> SIGNAL_LOST incident if the last fix was risky: inside a flagged zone, at night,
                                     or already MODERATE/HIGH (severity HIGH)
  * ALERT_S of silence            -> SIGNAL_LOST incident in every other case (severity MEDIUM)
A dead battery (last reported at or below LOW_BATTERY %) is still alerted, but marked as the likely cause.
The incident closes itself when locations start arriving again.
"""
import logging, os, threading
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import text
from . import models as m, scoring
from .database import SessionLocal
from .service import finish, open_incident

log = logging.getLogger('watchdog')
SIGNAL_LOST_S = int(os.getenv('SIGNAL_LOST_S', '180'))
ALERT_RISKY_S = int(os.getenv('SIGNAL_ALERT_RISKY_S', '300'))
ALERT_S = int(os.getenv('SIGNAL_ALERT_S', '600'))
LOW_BATTERY = int(os.getenv('SIGNAL_LOW_BATTERY', '10'))
INTERVAL = int(os.getenv('WATCHDOG_INTERVAL_S', '30'))  # 0 disables the background thread


def silent_for(state, now):
    if not state or not state.updated_at:
        return None
    return max(0.0, (now - scoring.as_utc(state.updated_at)).total_seconds())


def signal(state, status, now):
    """'LIVE', 'LOST' or None (not tracking / no fix yet), for dashboards."""
    s = silent_for(state, now)
    if status != 'TRACKING' or s is None:
        return None
    return 'LOST' if s >= SIGNAL_LOST_S else 'LIVE'


def _tz(slug):
    try:
        return ZoneInfo(scoring.location_cfg(slug)['location'].get('timezone', 'UTC'))
    except Exception:
        return timezone.utc


def _risky(db, t, st):
    """Why the last known situation was risky (zone name, 'night', 'risk level'), or None."""
    geo_rows, tree = scoring.geofence_index(db, t.location_slug)
    from shapely.geometry import Point
    for gi in tree.query(Point(st.longitude, st.latitude), predicate='within'):
        name, risk, _ = geo_rows[int(gi)]
        if risk >= 0.5:
            return f'inside "{name}"'
    hour = scoring.as_utc(st.updated_at).astimezone(_tz(t.location_slug)).hour
    if hour >= 22 or hour <= 5:
        return 'at night'
    if st.risk_level in ('MODERATE', 'HIGH'):
        return f'with risk level {st.risk_level}'
    return None


def check(db, now=None):
    """One pass over every tracked traveller. Returns the incidents opened (as dicts) for logging and tests."""
    now = now or datetime.now(timezone.utc)
    opened = []
    rows = (db.query(m.Tourist, m.TouristState)
            .join(m.TouristState, m.TouristState.tourist_id == m.Tourist.tourist_id)
            .filter(m.Tourist.status == 'TRACKING').all())
    already = {i.tourist_id for i in db.query(m.Incident.tourist_id).filter(
        m.Incident.incident_type == 'SIGNAL_LOST', m.Incident.status != 'RESOLVED')}
    for t, st in rows:
        if t.tourist_id in already:
            continue
        silent = silent_for(st, now)
        if silent is None or silent < min(ALERT_RISKY_S, ALERT_S) or st.latitude is None:
            continue
        why = _risky(db, t, st)
        if silent < (ALERT_RISKY_S if why else ALERT_S):
            continue
        battery = (st.recent or [{}])[-1].get('battery')
        seen = scoring.as_utc(st.updated_at).astimezone(_tz(t.location_slug)).strftime('%H:%M')
        took = f'{int(silent // 60)} min' if silent >= 60 else f'{int(silent)} s'
        parts = [f'No signal for {took}', f'Last location {st.latitude:.5f}, {st.longitude:.5f} at {seen}' + (f', {why}' if why else '')]
        if battery is not None:
            parts.append(f'Battery {battery}%' + (', likely a dead phone: call the traveller, then their emergency contact' if battery <= LOW_BATTERY else ''))
        severity = 'HIGH' if why and (battery is None or battery > LOW_BATTERY) else 'MEDIUM'
        inc = open_incident(db, t.tourist_id, 'SIGNAL_LOST', severity, st.latitude, st.longitude, '. '.join(parts) + '.')
        opened.append(dict(tourist_id=t.tourist_id, severity=inc.severity, description=inc.description))
    finish(db)
    return opened


def resolve_returned(db, tourist_ids):
    """Locations are arriving again: close any open SIGNAL_LOST incidents for these travellers."""
    from .service import audit
    if not tourist_ids:
        return
    for inc in db.query(m.Incident).filter(m.Incident.tourist_id.in_(tourist_ids), m.Incident.incident_type == 'SIGNAL_LOST',
                                           m.Incident.status != 'RESOLVED'):
        inc.status, inc.resolved_at = 'RESOLVED', datetime.now(timezone.utc)
        audit(db, inc, 'RESOLVED', 'system', {'reason': 'signal back'})


def _run_once():
    with SessionLocal() as db:
        if db.bind.dialect.name == 'postgresql':  # one watchdog at a time across all web processes
            if not db.execute(text('SELECT pg_try_advisory_lock(7003)')).scalar():
                return
            try:
                opened = check(db)
            finally:
                db.execute(text('SELECT pg_advisory_unlock(7003)'))
                db.commit()
        else:
            opened = check(db)
    for o in opened:
        log.warning('signal lost: %s', o)


def start():
    if INTERVAL <= 0:
        return None
    stop = threading.Event()

    def loop():
        while not stop.wait(INTERVAL):
            try:
                _run_once()
            except Exception:
                log.exception('watchdog failed')
    threading.Thread(target=loop, daemon=True, name='signal-watchdog').start()
    return stop
