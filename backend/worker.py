"""Stand-alone ingest consumer for the Redis backend:
    REDIS_URL=... DATABASE_URL=... python -m backend.worker [--name w1]
Each process competes for shard leases (see ingest.py), so adding workers adds capacity up to INGEST_SHARDS and
extra processes act as hot spares. Stops cleanly on SIGTERM, releasing its shards and finishing its current batch."""
import argparse, logging, signal, threading
from . import ingest, models as m
from .database import engine, ensure_indexes

p = argparse.ArgumentParser()
p.add_argument('--name', default=None, help='consumer name (default: hostname-pid)')
a = p.parse_args()
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(message)s')
m.Base.metadata.create_all(engine)
ensure_indexes()
client = ingest.redis_client()
if client is None:
    raise SystemExit('REDIS_URL is required for a stand-alone worker')
backend = ingest.RedisBackend(client, consumer=a.name, role='worker')
backend.start()
stop = threading.Event()
for sig in (signal.SIGINT, signal.SIGTERM):
    signal.signal(sig, lambda *_: stop.set())
logging.info('worker %s running (%d shards)', backend.consumer, ingest.SHARDS)
while not stop.wait(60):  # heartbeat so the platform logs show the worker is alive and how it is doing
    logging.info('queue_depth=%s %s', backend.depth(), {k: v for k, v in ingest.stats.items() if k in ('handled', 'processed', 'batches', 'errors')})
backend.stop()
