"""Delete old history in small batches so the tables (and the free Postgres disk) don't grow forever.
tourist_state, registrations, incidents and the ledger are never pruned."""
import logging, os, threading, time
from datetime import datetime, timedelta, timezone
from sqlalchemy import text
from . import models as m
from .database import SessionLocal

log = logging.getLogger('retention')
DAYS = int(os.getenv('RETENTION_DAYS', '30'))  # 0 disables
INTERVAL = int(os.getenv('RETENTION_INTERVAL_S', '3600'))


def purge(days=DAYS, batch=5000):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    deleted = {}
    for model, col in ((m.TouristLocation, m.TouristLocation.recorded_at), (m.RiskAssessment, m.RiskAssessment.assessed_at)):
        n = 0
        while True:
            with SessionLocal() as db:
                ids = [r[0] for r in db.query(model.id).filter(col < cutoff).limit(batch)]
                if not ids:
                    break
                db.query(model).filter(model.id.in_(ids)).delete(synchronize_session=False)
                db.commit()
                n += len(ids)
        deleted[model.__tablename__] = n
    return deleted


def _run_once():
    with SessionLocal() as db:
        if db.bind.dialect.name == 'postgresql':  # one instance at a time across all web processes
            if not db.execute(text('SELECT pg_try_advisory_lock(7002)')).scalar():
                return
            try:
                log.info('retention purged %s', purge())
            finally:
                db.execute(text('SELECT pg_advisory_unlock(7002)'))
                db.commit()
            return
    log.info('retention purged %s', purge())


def start():
    if DAYS <= 0:
        return None
    stop = threading.Event()

    def loop():
        while not stop.wait(INTERVAL if INTERVAL else 3600):
            try:
                _run_once()
            except Exception:
                log.exception('retention failed')
    threading.Thread(target=loop, daemon=True, name='retention').start()
    return stop
