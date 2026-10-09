"""Demo replay: each demo tourist replays a real(ish) processed trajectory, one fix per tick."""
import json
from datetime import datetime, timedelta, timezone
import pandas as pd
from .database import ROOT

_state = {}


def _load():
    if 'cur' in _state:
        return
    f = ROOT / 'data' / 'processed' / 'mobility_with_anomaly.csv'
    if not f.exists():
        _state['cur'] = {}
        return
    d = pd.read_csv(f, parse_dates=['timestamp'])
    risky = []
    gj = ROOT / 'locations' / 'bhopal' / 'geofences.geojson'
    if gj.exists():
        for f in json.loads(gj.read_text())['features']:
            if f['properties'].get('risk_level', 0) >= 0.6:
                xs, ys = zip(*f['geometry']['coordinates'][0])
                risky.append((min(xs), max(xs), min(ys), max(ys)))
    d['in_risky'] = False
    for x0, x1, y0, y1 in risky:
        d['in_risky'] |= d.longitude.between(x0, x1) & d.latitude.between(y0, y1)
    g = d.groupby(['user_id', 'trajectory_id']).agg(n=('movement_anomaly', 'size'), m=('movement_anomaly', 'mean'),
                                                    h=('hour', 'median'), r=('in_risky', 'sum')).reset_index()
    g = g[(g.n >= 120) & (g.n <= 900)]
    calm = g[g.h.between(9, 17)].sort_values('m').iloc[0]
    odd = g.drop(calm.name).sort_values('m').iloc[-1]
    rest = g.drop([calm.name, odd.name])
    zone = rest.sort_values('r').iloc[-1]
    picks = {'T001': calm, 'T002': odd, 'T003': zone}
    _state['cur'] = {}
    for tid, row in picks.items():
        t = d[(d.user_id == row.user_id) & (d.trajectory_id == row.trajectory_id)].sort_values('timestamp')
        # thin to ~1 fix per 15s so a replay moves visibly and covers real ground
        t = t.iloc[::3].reset_index(drop=True)
        _state['cur'][tid] = {'df': t, 'i': 0, 'base': datetime.now(timezone.utc), 'last': None}


def next_fix(tid):
    _load()
    s = _state['cur'].get(tid)
    if s is None:
        return None
    df = s['df']
    r = df.iloc[s['i'] % len(df)]
    first = s['i'] % len(df) == 0
    if first and s['last'] is not None:
        s['base'] = s['last'] + timedelta(minutes=10)  # loop restart: virtual 10 min gap, avoids a teleport "speed"
    s['i'] += 1
    ts = s['base'] + (r.timestamp - df.timestamp.iloc[0]).to_pytimedelta()
    s['last'] = ts
    return dict(lat=float(r.latitude), lon=float(r.longitude), hour=int(r.hour), ts=ts, restart=first,
                start=(float(df.latitude.iloc[0]), float(df.longitude.iloc[0])),
                end=(float(df.latitude.iloc[-1]), float(df.longitude.iloc[-1])))


def reset():
    _state.clear()
