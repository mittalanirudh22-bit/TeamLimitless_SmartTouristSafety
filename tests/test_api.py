import os, tempfile
import numpy as np
import pytest

_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
os.environ['DATABASE_URL'] = f'sqlite:///{_db.name}'
os.environ['OPS_TOKEN'] = 'test-ops'
os.environ['REGISTER_LIMIT_PER_HOUR'] = '1000'

from fastapi.testclient import TestClient  # noqa: E402
from backend.main import app  # noqa: E402

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
        assert out.status_code == 200 and out.json()['risk_level'] in ('LOW', 'MODERATE', 'HIGH')
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
