"""Stand-alone ingest consumer for the Redis backend: `REDIS_URL=... DATABASE_URL=... python -m backend.worker`.
Run several of them (distinct --name) for throughput; each handles all shards via a shared consumer group."""
import argparse, logging, signal, threading
from . import ingest, models as m, scoring
from .database import engine, ensure_indexes

p = argparse.ArgumentParser()
p.add_argument('--name', default=None, help='consumer name (unique per process)')
a = p.parse_args()
logging.basicConfig(level=logging.INFO)
m.Base.metadata.create_all(engine)
ensure_indexes()
if not ingest.redis_client():
    raise SystemExit('REDIS_URL is required for a stand-alone worker')
backend = ingest.RedisBackend(ingest.redis_client(), consumer=a.name)
backend.start()
stop = threading.Event()
for sig in (signal.SIGINT, signal.SIGTERM):
    signal.signal(sig, lambda *_: stop.set())
logging.info('worker running (%d shards)', ingest.SHARDS)
stop.wait()
backend.stop()
