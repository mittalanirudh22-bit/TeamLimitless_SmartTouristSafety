import os, tempfile
import numpy as np
import pytest

_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
os.environ['DATABASE_URL'] = f'sqlite:///{_db.name}'
os.environ['OPS_TOKEN'] = 'test-ops'
os.environ['REGISTER_LIMIT_PER_HOUR'] = '1000'

from fastapi.testclient import TestClient  # noqa: E402
from backend.main import app  # noqa: E402
from backend import ingest  # noqa: E402

OPS = {'X-Ops-Token': 'test-ops'}
BODY = dict(full_name='Test Traveller', nationality='India', phone='+91 90000 00000',
            emergency_name='Contact', emergency_phone='+91 90000 00001', consent=True)


@pytest.fixture(scope='module')
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def traveller(client):
    r = client.post('/api/travellers/register', json=BODY).json()
    return r, {'X-Tracking-Token': r['tracking_token']}


def test_fast_scorer_matches_sklearn():
    import joblib
    from ml.fast_iforest import FastScorer
    from backend.scoring import MODEL_PATH
    b = joblib.load(MODEL_PATH)
    fs = FastScorer.build(b['model'], len(b['features']))
    assert fs is not None
    rng = np.random.default_rng(1)
    X = np.column_stack([rng.normal(8, 30, 500), rng.normal(0, 4, 500), rng.uniform(0, 180, 500),
                         rng.exponential(100, 500), rng.exponential(40, 500)])
    import pandas as pd
    ref = b['model'].decision_function(pd.DataFrame(X, columns=b['features']))
    assert np.allclose(fs.decision_function(X), ref, atol=1e-9)


def test_consent_required(client):
    assert client.post('/api/travellers/register', json={**BODY, 'consent': False}).status_code == 400


def test_register_start_track_verify(client, traveller):
    r, h = traveller
    assert r['blockchain_id'].startswith('TLB-')
    assert client.post('/api/travellers/me/location', json={'latitude': 23.25, 'longitude': 77.35}, headers=h).status_code == 409
    assert client.post('/api/travellers/me/start', headers=h).json()['status'] == 'TRACKING'
    for i, ts in enumerate(['2026-10-10T10:00:00Z', '2026-10-10T10:00:05Z', '2026-10-10T10:00:10Z']):
        out = client.post('/api/travellers/me/location', json={'latitude': 23.25 + i * 1e-4, 'longitude': 77.35, 'timestamp': ts}, headers=h)
        assert out.status_code == 202 and out.json() == {'queued': True}
    assert ingest.wait_idle()
    me = client.get('/api/travellers/me', headers=h).json()
    assert me['latitude'] is not None and len(me['trail']) == 3 and me['risk_level']
    v = client.get(f"/api/verify/{r['blockchain_id']}").json()
    assert v['id_matches_block'] and v['chain_valid']


def test_sos_creates_incident_and_ledger_stays_valid(client, traveller):
    r, h = traveller
    client.post('/api/travellers/me/start', headers=h)
    s = client.post('/api/travellers/me/sos', json={'latitude': 23.25, 'longitude': 77.35}, headers=h).json()
    assert s['risk_level'] == 'HIGH' and s['incident']['incident_type'] == 'SOS'
    inc = client.get('/api/incidents', headers=OPS).json()
    assert any(i['id'] == s['incident']['id'] for i in inc)
    assert client.get('/api/ledger/verify').json()['valid']


def test_out_of_order_fix_does_not_rewind_state(client, traveller):
    _, h = traveller
    client.post('/api/travellers/me/start', headers=h)
    f = lambda lat, ts: client.post('/api/travellers/me/location', json={'latitude': lat, 'longitude': 77.35, 'timestamp': ts}, headers=h)
    f(23.26, '2026-10-10T11:00:10Z'); f(23.20, '2026-10-10T11:00:00Z')
    assert ingest.wait_idle()
    assert client.get('/api/travellers/me', headers=h).json()['latitude'] == 23.26


def test_auth_boundaries(client, traveller):
    r, h = traveller
    assert client.get('/api/tourists').status_code == 401
    assert client.get('/api/tourists', headers=OPS).status_code == 200
    assert client.get('/api/travellers/me').status_code == 401
    assert client.get('/api/travellers/me', headers={'X-Tracking-Token': 'nope'}).status_code == 401
    # unauthenticated-style ingest must not work against a registered traveller
    assert client.post('/api/locations', json={'tourist_id': r['tourist_id'], 'latitude': 1, 'longitude': 1}, headers=OPS).status_code == 403
    assert client.post('/api/simulate/reset', headers=OPS).status_code == 403


def test_dashboard_query_count_is_flat(client):
    from sqlalchemy import event
    from backend.database import engine
    n = []
    event.listen(engine, 'before_cursor_execute', lambda *a: n.append(1))
    client.get('/api/tourists', headers=OPS)
    assert len(n) <= 6  # does not grow with the number of tourists


def _fix(c, h, lat, lon, ts):
    return c.post('/api/travellers/me/location', json={'latitude': lat, 'longitude': lon, 'timestamp': ts}, headers=h)


def test_batch_matches_one_by_one(client):
    """The batched scoring path must give the same answers as scoring each fix on its own."""
    from datetime import datetime, timedelta, timezone
    from backend import models as m, scoring
    from backend.database import SessionLocal
    base = datetime(2026, 10, 11, 9, 0, tzinfo=timezone.utc)
    pts = [(23.25 + i * 2e-4 + (0.003 if i == 7 else 0), 77.35 + i * 1e-4, base + timedelta(seconds=5 * i)) for i in range(12)]
    ids = []
    with SessionLocal() as db:
        for tag in ('a', 'b'):
            t = m.Tourist(tourist_id=f'EQ{tag}', location_slug='bhopal', display_name=tag, status='TRACKING')
            db.add(t); ids.append(t)
        db.commit()
        one = [scoring.assess(db, ids[0], la, lo, ts) for la, lo, ts in pts]
        db.commit()
        many = scoring.assess_batch(db, [dict(tourist=ids[1], lat=la, lon=lo, ts=ts) for la, lo, ts in pts])
        db.commit()
    for x, y in zip(one, many):
        assert x['risk_score'] == pytest.approx(y['risk_score'], abs=1e-9) and x['inputs'] == pytest.approx(y['inputs'])


def test_duplicate_and_late_fixes_are_idempotent(client, traveller):
    from backend import models as m
    from backend.database import SessionLocal
    r, h = traveller
    client.post('/api/travellers/me/start', headers=h)
    for _ in range(3):
        _fix(client, h, 23.25, 77.35, '2026-10-12T10:00:00Z')  # at-least-once delivery may repeat a fix
    assert ingest.wait_idle()
    with SessionLocal() as db:
        assert db.query(m.TouristLocation).filter_by(tourist_id=r['tourist_id']).count() == 1


def test_poison_fix_does_not_sink_the_batch(client, traveller, monkeypatch):
    from backend import models as m, scoring
    from backend.database import SessionLocal
    r, h = traveller
    client.post('/api/travellers/me/start', headers=h)
    real = scoring.assess_batch

    def flaky(db, items):
        if len(items) > 1 or items[0]['lat'] == 23.299:
            raise RuntimeError('boom')
        return real(db, items)
    monkeypatch.setattr(scoring, 'assess_batch', flaky)
    for lat, ts in ((23.25, '2026-10-13T10:00:00Z'), (23.299, '2026-10-13T10:00:05Z'), (23.26, '2026-10-13T10:00:10Z')):
        _fix(client, h, lat, 77.35, ts)
    assert ingest.wait_idle()
    with SessionLocal() as db:
        got = sorted(x.latitude for x in db.query(m.TouristLocation).filter_by(tourist_id=r['tourist_id']))
    assert 23.299 not in got and 23.25 in got and 23.26 in got


def test_backpressure_returns_503(client, traveller, monkeypatch):
    _, h = traveller
    client.post('/api/travellers/me/start', headers=h)
    monkeypatch.setattr(ingest, 'MAX_QUEUE', -1)
    resp = _fix(client, h, 23.25, 77.35, '2026-10-14T10:00:00Z')
    assert resp.status_code == 503 and resp.headers['retry-after']


def test_delta_polling_returns_only_changes(client, traveller):
    _, h = traveller
    client.post('/api/travellers/me/start', headers=h)
    _fix(client, h, 23.25, 77.35, '2026-10-15T10:00:00Z')
    assert ingest.wait_idle()
    full = client.get('/api/tourists', headers=OPS).json()
    latest = max(t['updated_at'] for t in full if t['updated_at'])
    assert client.get('/api/tourists', params={'since': latest}, headers=OPS).json() == []
    _fix(client, h, 23.2501, 77.35, '2026-10-15T10:00:30Z')
    assert ingest.wait_idle()
    changed = client.get('/api/tourists', params={'since': latest}, headers=OPS).json()
    assert len(changed) == 1 and len(full) > 1


def test_retention_purges_old_history_only(client, traveller):
    from datetime import datetime, timedelta, timezone
    from backend import models as m, retention
    from backend.database import SessionLocal
    r, h = traveller
    client.post('/api/travellers/me/start', headers=h)
    old = datetime.now(timezone.utc) - timedelta(days=40)
    with SessionLocal() as db:
        db.add(m.TouristLocation(tourist_id=r['tourist_id'], recorded_at=old, latitude=1, longitude=1))
        db.add(m.TouristLocation(tourist_id=r['tourist_id'], recorded_at=datetime.now(timezone.utc), latitude=2, longitude=2))
        db.commit()
    out = retention.purge(days=30, batch=1)
    assert out['tourist_locations'] >= 1
    with SessionLocal() as db:
        lats = [x.latitude for x in db.query(m.TouristLocation).filter_by(tourist_id=r['tourist_id'])]
    assert 1 not in lats and 2 in lats


def test_redis_backend_orders_acks_and_recovers():
    """Redis Streams path, against fakeredis: per-tourist order is kept and every message is acked."""
    import fakeredis, json
    r = fakeredis.FakeRedis()
    got = []
    ingest.CLAIM_IDLE_MS, ingest.CLAIM_EVERY_S = 0, 0.1
    real_safe = ingest.safe_process
    ingest.safe_process = lambda entries: got.extend(entries)
    try:
        be = ingest.RedisBackend(r, consumer='t1')
        for i in range(30):
            be.put(dict(tid='TRX', lat=23.0, lon=77.0 + i * 1e-4, ts=f'2026-10-16T10:00:{i:02d}+00:00'))
        be.start()
        import time
        for _ in range(100):
            if len(got) >= 30:
                break
            time.sleep(0.05)
        be.stop(2)
        assert [e['ts'] for e in got] == sorted(e['ts'] for e in got) and len(got) == 30
        assert all(r.xpending(ingest.STREAM + str(i), ingest.GROUP)['pending'] == 0 for i in range(ingest.SHARDS))
        # a message read by a consumer that then "crashed" is re-delivered to a fresh consumer
        be2 = ingest.RedisBackend(r, consumer='dead')
        be2.put(dict(tid='TRX', lat=1, lon=1, ts='2026-10-16T11:00:00+00:00'))
        key = ingest.STREAM + str(ingest._shard('TRX'))
        r.xreadgroup(ingest.GROUP, 'dead', {key: '>'}, count=10)
        got.clear()
        be3 = ingest.RedisBackend(r, consumer='fresh')
        be3.start()
        time.sleep(1.0)
        be3.stop(2)
        assert any(e['lat'] == 1 for e in got)
    finally:
        ingest.safe_process = real_safe
        ingest.CLAIM_IDLE_MS, ingest.CLAIM_EVERY_S = 60000, 30


def test_redis_shards_have_a_single_owner_and_hand_over():
    """With several consumers, each shard is consumed by exactly one (per-tourist ordering), and hands over on stop."""
    import fakeredis, time
    r = fakeredis.FakeRedis()
    seen, real_safe = [], ingest.safe_process
    ingest.safe_process = lambda entries: seen.extend(entries)
    try:
        a, b = ingest.RedisBackend(r, consumer='A'), ingest.RedisBackend(r, consumer='B')
        a.start(); b.start()
        time.sleep(0.5)
        owners = [r.get(f'limitless:lease:{i}').decode() for i in range(ingest.SHARDS)]
        assert all(o in ('A', 'B') for o in owners)
        tids = [f'TRO{i}' for i in range(6)]
        for n in range(20):
            for t in tids:
                a.put(dict(tid=t, lat=1, lon=1, ts=f'2026-10-17T10:00:{n:02d}+00:00'))
        deadline = time.time() + 5
        while len(seen) < 120 and time.time() < deadline:
            time.sleep(0.05)
        assert len(seen) == 120
        for t in tids:  # strictly in order per tourist
            ts = [e['ts'] for e in seen if e['tid'] == t]
            assert ts == sorted(ts)
        a.stop(2)  # A's shards are released and B takes them over
        deadline = time.time() + 5
        while time.time() < deadline and any(r.get(f'limitless:lease:{i}') != b'B' for i in range(ingest.SHARDS)):
            time.sleep(0.1)
        assert all(r.get(f'limitless:lease:{i}') == b'B' for i in range(ingest.SHARDS))
        b.stop(2)
    finally:
        ingest.safe_process = real_safe


def test_redis_down_falls_back_and_enqueue_failure_is_503(client, traveller, monkeypatch):
    class Dead:
        def __getattr__(self, name):
            raise ConnectionError('redis is down')
    monkeypatch.setattr(ingest, 'redis_client', lambda: Dead())
    saved = ingest._backend
    try:
        be = ingest.start(embedded_workers=False)
        assert be.name.startswith('memory')  # boot did not crash
    finally:
        ingest._backend = saved
    # a backend that dies after boot: clients get 503 + Retry-After, not a 500
    class Broken:
        name = 'broken'
        def put(self, e): raise ConnectionError('redis went away')
        def depth(self): return 0
    monkeypatch.setattr(ingest, '_backend', Broken())
    _, h = traveller
    client.post('/api/travellers/me/start', headers=h)
    resp = _fix(client, h, 23.25, 77.35, '2026-10-18T10:00:00Z')
    assert resp.status_code == 503 and resp.headers['retry-after']


def test_embedded_consumers_yield_to_a_live_worker_and_resume_without_it():
    import fakeredis, time
    r = fakeredis.FakeRedis()
    seen, real_safe, real_ttl = [], ingest.safe_process, ingest.WORKER_TTL_MS
    ingest.safe_process = lambda entries: seen.extend((e['tid'], e['ts']) for e in entries)
    ingest.WORKER_TTL_MS = 1500
    try:
        web = ingest.RedisBackend(r, consumer='web', role='embedded')
        web.start()
        web._ded_checked = 0
        for n in range(4):
            web.put(dict(tid='TRW', lat=1, lon=1, ts=f'2026-10-19T10:00:0{n}+00:00'))
        time.sleep(1.0)
        assert len(seen) == 4  # no worker yet: the web tier consumes
        worker = ingest.RedisBackend(r, consumer='w', role='worker')
        worker.start()
        time.sleep(3.5)  # web notices the heartbeat and releases every shard; the worker owns them all
        assert all(r.get(f'limitless:lease:{i}') == b'w' for i in range(ingest.SHARDS))
        seen.clear()
        web.put(dict(tid='TRW', lat=1, lon=1, ts='2026-10-19T10:01:00+00:00'))
        time.sleep(1.0)
        assert seen == [('TRW', '2026-10-19T10:01:00+00:00')]  # consumed exactly once, by the worker
        worker.stop(2)  # worker dies: heartbeat expires, web takes the shards back
        time.sleep(1.8 + 3)
        seen.clear()
        web.put(dict(tid='TRW', lat=1, lon=1, ts='2026-10-19T10:02:00+00:00'))
        time.sleep(1.5)
        assert seen == [('TRW', '2026-10-19T10:02:00+00:00')]
        web.stop(2)
    finally:
        ingest.safe_process, ingest.WORKER_TTL_MS = real_safe, real_ttl
