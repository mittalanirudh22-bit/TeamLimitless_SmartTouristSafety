"""GPS ingest pipeline: the API validates and enqueues, workers score in batches.

* Default backend is in-process (sharded queues + threads): absorbs bursts and batches DB writes and model calls.
  Queued fixes are lost if the process dies (acceptable for position updates; SOS never goes through here).
* With REDIS_URL set, fixes go through Redis Streams (consumer groups, ack after commit = at-least-once; duplicates are
  dropped by timestamp). Run extra consumers with `python -m backend.worker` and set INGEST_EMBEDDED_WORKERS=0 on the web tier.
* Shards are chosen by crc32(tourist_id), so one tourist's fixes always go through one consumer, in order.
"""
import json, logging, os, queue, threading, time, zlib
from datetime import datetime, timezone
from . import models as m, scoring
from .database import SessionLocal
from .service import finish, open_incident

log = logging.getLogger('ingest')
SHARDS = int(os.getenv('INGEST_SHARDS', '2'))
BATCH_MAX = int(os.getenv('INGEST_BATCH_MAX', '500'))
BATCH_WAIT = float(os.getenv('INGEST_BATCH_WAIT_MS', '25')) / 1000
MAX_QUEUE = int(os.getenv('INGEST_MAX_QUEUE', '50000'))  # per backend; above this the API sheds load with 503
CLAIM_IDLE_MS = int(os.getenv('INGEST_CLAIM_IDLE_MS', '60000'))  # re-deliver fixes a dead consumer never acked
CLAIM_EVERY_S = float(os.getenv('INGEST_CLAIM_EVERY_S', '30'))
STREAM = 'limitless:fixes:'
GROUP = 'workers'

stats = dict(enqueued=0, handled=0, processed=0, batches=0, errors=0, rejected=0, last_batch_ms=0.0, last_batch_size=0)
_stats_lock = threading.Lock()


class Backpressure(Exception):
    pass


def _shard(tid):
    return zlib.crc32(tid.encode()) % SHARDS


def process_batch(entries):
    """entries: [{tid, lat, lon, ts(iso)}]. One session, one model call, one commit, then ledger blocks."""
    t0 = time.perf_counter()
    with SessionLocal() as db:
        tourists = {t.tourist_id: t for t in db.query(m.Tourist).filter(m.Tourist.tourist_id.in_({e['tid'] for e in entries}))}
        items = [dict(tourist=tourists[e['tid']], lat=e['lat'], lon=e['lon'], ts=datetime.fromisoformat(e['ts']))
                 for e in entries if e['tid'] in tourists and tourists[e['tid']].status == 'TRACKING']
        results = scoring.assess_batch(db, items)
        for it, res in zip(items, results):
            if res.get('risk_level') == 'HIGH':
                open_incident(db, it['tourist'].tourist_id, 'HIGH_RISK', 'HIGH', it['lat'], it['lon'],
                              f"Risk score {res['risk_score']}" + (f" in {res['geofence']}" if res['geofence'] else ''))
        finish(db)
    with _stats_lock:
        stats['processed'] += len(items)
        stats['batches'] += 1
        stats['last_batch_ms'] = round((time.perf_counter() - t0) * 1000, 1)
        stats['last_batch_size'] = len(entries)


def safe_process(entries):
    """A poison fix must not take the batch down with it: on failure, retry one by one and drop only the bad ones."""
    try:
        process_batch(entries)
    except Exception:
        log.exception('batch of %d failed; retrying individually', len(entries))
        for e in entries:
            try:
                process_batch([e])
            except Exception:
                log.exception('dropping fix for %s', e.get('tid'))
                with _stats_lock:
                    stats['errors'] += 1
    finally:
        with _stats_lock:
            stats['handled'] += len(entries)


class MemoryBackend:
    name = 'memory'

    def __init__(self):
        self.qs = [queue.Queue() for _ in range(SHARDS)]
        self.threads, self.stopping = [], threading.Event()

    def put(self, e):
        if self.depth() >= MAX_QUEUE:
            raise Backpressure()
        self.qs[_shard(e['tid'])].put(e)

    def depth(self):
        return sum(q.qsize() for q in self.qs)

    def start(self):
        for q in self.qs:
            th = threading.Thread(target=self._loop, args=(q,), daemon=True, name='ingest-worker')
            th.start()
            self.threads.append(th)

    def _loop(self, q):
        while True:
            try:
                batch = [q.get(timeout=0.2)]
            except queue.Empty:
                if self.stopping.is_set():
                    return
                continue
            deadline = time.monotonic() + BATCH_WAIT
            while len(batch) < BATCH_MAX:
                remaining = deadline - time.monotonic()
                try:
                    batch.append(q.get(timeout=remaining) if remaining > 0 else q.get_nowait())
                except queue.Empty:
                    break
            safe_process(batch)

    def stop(self, timeout=15):
        self.stopping.set()  # workers exit once their queue is empty, so queued fixes are flushed on a clean shutdown
        for th in self.threads:
            th.join(timeout)


class RedisBackend:
    name = 'redis'

    def __init__(self, client, consumer=None):
        self.r, self.consumer = client, consumer or f'c-{os.getpid()}'
        self.threads, self.stopping = [], threading.Event()
        for i in range(SHARDS):
            try:
                self.r.xgroup_create(STREAM + str(i), GROUP, id='0', mkstream=True)
            except Exception as e:  # BUSYGROUP: already exists
                if 'BUSYGROUP' not in str(e):
                    raise

    def put(self, e):
        if self.depth() >= MAX_QUEUE:
            raise Backpressure()
        self.r.xadd(STREAM + str(_shard(e['tid'])), {'d': json.dumps(e)})

    def depth(self):
        return sum(self.r.xlen(STREAM + str(i)) for i in range(SHARDS))

    def start(self, shards=None):
        for i in (range(SHARDS) if shards is None else shards):
            th = threading.Thread(target=self._loop, args=(STREAM + str(i),), daemon=True, name=f'ingest-redis-{i}')
            th.start()
            self.threads.append(th)

    def _loop(self, key):
        # Recover anything a crashed consumer read but never acked, then switch to new messages.
        pending, last_claim = '0', time.monotonic()
        while not self.stopping.is_set():
            try:
                if time.monotonic() - last_claim > CLAIM_EVERY_S:
                    last_claim = time.monotonic()
                    claimed = self.r.xautoclaim(key, GROUP, self.consumer, min_idle_time=CLAIM_IDLE_MS, start_id='0-0', count=BATCH_MAX)[1]
                    if claimed:
                        safe_process([json.loads(f[b'd' if b'd' in f else 'd']) for _, f in claimed])
                        self.r.xack(key, GROUP, *[mid for mid, _ in claimed])
                        self.r.xdel(key, *[mid for mid, _ in claimed])
                resp = self.r.xreadgroup(GROUP, self.consumer, {key: pending}, count=BATCH_MAX, block=500 if pending != '0' else 200)
                msgs = resp[0][1] if resp else []
                if pending == '0' and not msgs:
                    pending = '>'
                    continue
                if not msgs:
                    continue
                safe_process([json.loads(f[b'd' if b'd' in f else 'd']) for _, f in msgs])
                self.r.xack(key, GROUP, *[mid for mid, _ in msgs])
                self.r.xdel(key, *[mid for mid, _ in msgs])
            except Exception:
                log.exception('redis consumer error')
                time.sleep(1)

    def stop(self, timeout=15):
        self.stopping.set()
        for th in self.threads:
            th.join(timeout)


_backend = None


def redis_client():
    url = os.getenv('REDIS_URL')
    if not url:
        return None
    import redis
    return redis.Redis.from_url(url)


def start(embedded_workers=None):
    global _backend
    client = redis_client()
    _backend = RedisBackend(client) if client else MemoryBackend()
    if embedded_workers is None:
        embedded_workers = os.getenv('INGEST_EMBEDDED_WORKERS', '1') == '1'
    if embedded_workers:
        _backend.start()
    return _backend


def stop():
    if _backend:
        _backend.stop()


def enqueue(entry):
    try:
        _backend.put(entry)
    except Backpressure:
        with _stats_lock:
            stats['rejected'] += 1
        raise
    with _stats_lock:
        stats['enqueued'] += 1


def snapshot():
    return dict(backend=_backend.name if _backend else None, queue_depth=_backend.depth() if _backend else 0,
                shards=SHARDS, **stats)


def wait_idle(timeout=10.0):
    """Block until every fix enqueued by this process has been handled (tests, graceful scripts)."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        with _stats_lock:
            if stats['handled'] >= stats['enqueued']:
                return True
        time.sleep(0.01)
    return False
