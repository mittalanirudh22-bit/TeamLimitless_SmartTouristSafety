"""GPS ingest pipeline: the API validates and enqueues, workers score in batches.

* Default backend is in-process (sharded queues + threads): absorbs bursts and batches DB writes and model calls.
  Queued fixes are lost if the process dies (acceptable for position updates; SOS never goes through here).
* With REDIS_URL set, fixes go through Redis Streams (consumer groups, ack after commit = at-least-once; duplicates are
  dropped by timestamp). Run extra consumers with `python -m backend.worker` and set INGEST_EMBEDDED_WORKERS=0 on the web tier.
* Shards are chosen by crc32(tourist_id). With Redis, each shard is owned by one consumer at a time through a short renewable
  lease, so one tourist's fixes are processed in order even with many consumers (web instances + workers); consumers beyond
  the shard count simply stand by as hot spares. Dedicated workers (`python -m backend.worker`) publish a heartbeat; while
  one is alive the web tier's embedded consumers stand by, and they resume on their own if every worker dies. Use more shards than consumers (INGEST_SHARDS, default 2; 4+ on Render).
"""
import json, logging, os, queue, socket, threading, time, zlib
from datetime import datetime, timezone
from . import models as m, scoring
from .database import SessionLocal
from .service import finish, open_incident

log = logging.getLogger('ingest')
SHARDS = int(os.getenv('INGEST_SHARDS', '2'))
BATCH_MAX = int(os.getenv('INGEST_BATCH_MAX', '500'))
BATCH_WAIT = float(os.getenv('INGEST_BATCH_WAIT_MS', '25')) / 1000
MAX_QUEUE = int(os.getenv('INGEST_MAX_QUEUE', '50000'))  # per backend; above this the API sheds load with 503
WORKER_TTL_MS = int(os.getenv('INGEST_WORKER_TTL_MS', '20000'))  # dedicated-worker heartbeat lifetime
LEASE_MS = int(os.getenv('INGEST_LEASE_MS', '15000'))  # a shard is consumed by exactly one consumer at a time
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

    def __init__(self, client, consumer=None, role='embedded'):
        self.r, self.consumer, self.role = client, consumer or f'{socket.gethostname()}-{os.getpid()}', role
        self._ded_checked, self._ded_alive = 0.0, False
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

    def _dedicated_alive(self):
        """Is any stand-alone worker heartbeating? Cached for 2 s so consumers don't hammer Redis."""
        if time.monotonic() - self._ded_checked > 2:
            self._ded_checked = time.monotonic()
            self._ded_alive = any(True for _ in self.r.scan_iter(match='limitless:worker:*', count=100))
        return self._ded_alive

    def _hold(self, i):
        """Acquire or renew the lease on shard i. False means another consumer owns it."""
        k = f'limitless:lease:{i}'
        if self.r.set(k, self.consumer, nx=True, px=LEASE_MS):
            return True
        cur = self.r.get(k)
        if cur is not None and cur.decode() == self.consumer:
            self.r.pexpire(k, LEASE_MS)
            return True
        return False

    def _release(self, i):
        k = f'limitless:lease:{i}'
        cur = self.r.get(k)
        if cur is not None and cur.decode() == self.consumer:
            self.r.delete(k)

    def start(self, shards=None):
        for i in (range(SHARDS) if shards is None else shards):
            th = threading.Thread(target=self._loop, args=(STREAM + str(i), i), daemon=True, name=f'ingest-redis-{i}')
            th.start()
            self.threads.append(th)

    def _loop(self, key, shard):
        # Recover anything a crashed consumer read but never acked, then switch to new messages.
        pending, last_claim = '0', time.monotonic()
        while not self.stopping.is_set():
            try:
                if self.role == 'worker':
                    self.r.set(f'limitless:worker:{self.consumer}', 1, px=WORKER_TTL_MS)
                elif self._dedicated_alive():  # a real worker is up: hand the shard over and stand by
                    self._release(shard)
                    self.stopping.wait(1)
                    continue
                if not self._hold(shard):  # someone else owns this shard; stand by and retry
                    self.stopping.wait(1)
                    continue
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
        try:
            self._release(shard)  # hand the shard over immediately instead of waiting for the lease to expire
        except Exception:
            pass

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
    _backend = None
    try:
        client = redis_client()
        _backend = RedisBackend(client) if client else MemoryBackend()
    except Exception:
        # A Redis outage at boot must not take the API down: degrade to the in-process queue, loudly.
        log.exception('Redis unavailable at startup; falling back to the in-process queue')
        _backend = MemoryBackend()
        _backend.name = 'memory (redis unavailable)'
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
    except Exception as e:  # queue full, or the backend (e.g. Redis) is unreachable: ask the client to retry
        with _stats_lock:
            stats['rejected' if isinstance(e, Backpressure) else 'errors'] += 1
        if not isinstance(e, Backpressure):
            log.exception('enqueue failed')
        raise Backpressure() from e
    with _stats_lock:
        stats['enqueued'] += 1


def public_status():
    """Non-sensitive summary for /api/info: which queue is active and whether a dedicated worker is consuming."""
    out = dict(backend=_backend.name if _backend else None, shards=SHARDS)
    if isinstance(_backend, RedisBackend):
        try:
            out['dedicated_worker_alive'] = _backend._dedicated_alive()
        except Exception:
            out['dedicated_worker_alive'] = None  # Redis unreachable right now
    return out


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
