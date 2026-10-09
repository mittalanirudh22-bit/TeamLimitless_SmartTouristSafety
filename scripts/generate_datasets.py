"""Generate SYNTHETIC datasets in the exact formats the pipeline expects.

The real GeoLife download (~1.6 GB) is not bundled, so this writes GeoLife-format
.plt trajectories around Bhopal, plus tourism / crime / geofence files. Everything
here is synthetic and illustrative: do not present it as real crime or visitor data.
Drop the real GeoLife dump into data/raw/geolife/ and re-run the pipeline to replace it.

Usage: python scripts/generate_datasets.py [--users 30] [--seed 42]
"""
import argparse, json, math
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LOC = ROOT / 'locations' / 'bhopal'

# (name, category, lat, lon) -- approximate landmark coordinates
POIS = [
    ('Upper Lake (Bada Talab)', 'lake', 23.2560, 77.3370),
    ('Bharat Bhavan', 'culture', 23.2540, 77.3490),
    ('Taj-ul-Masajid', 'heritage', 23.2658, 77.3915),
    ('New Market', 'market', 23.2330, 77.3990),
    ('Van Vihar National Park', 'park', 23.2420, 77.3640),
    ('Bhopal Junction Railway Station', 'transport', 23.2686, 77.4120),
    ('DB City Mall', 'mall', 23.2330, 77.4340),
    ('Museum of Man (Rashtriya Manav Sangrahalaya)', 'museum', 23.2150, 77.3640),
    ('Birla Mandir', 'heritage', 23.2410, 77.4140),
    ('Lower Lake / Boat Club', 'lake', 23.2560, 77.3810),
]

# Illustrative geofence boxes: (name, category, risk 0..1, centre lat, centre lon, half-size deg, description)
GEOFENCES = [
    ('Old City Heritage Zone', 'tourist_zone', 0.10, 23.2658, 77.3915, 0.006, 'Dense, well-patrolled tourist area.'),
    ('Upper Lake Promenade', 'tourist_zone', 0.10, 23.2560, 77.3450, 0.007, 'Popular walking area.'),
    ('New Market Commercial Area', 'tourist_zone', 0.15, 23.2330, 77.3990, 0.005, 'Busy shopping district.'),
    ('Isolated Lake Edge (night)', 'high_risk', 0.80, 23.2500, 77.3300, 0.004, 'Poorly lit, isolated at night.'),
    ('Industrial Belt', 'high_risk', 0.70, 23.2820, 77.4100, 0.006, 'Industrial area, low footfall for tourists.'),
    ('Forest Fringe (Van Vihar edge)', 'restricted', 0.60, 23.2380, 77.3560, 0.004, 'Wildlife area, restricted outside hours.'),
]


def box(lat, lon, h):
    return [[lon - h, lat - h], [lon + h, lat - h], [lon + h, lat + h], [lon - h, lat + h], [lon - h, lat - h]]


def write_plt(path: Path, pts):
    """pts: list of (lat, lon, alt_m, datetime) in GeoLife .plt format."""
    path.parent.mkdir(parents=True, exist_ok=True)
    head = ['Geolife trajectory', 'WGS 84', 'Altitude is in Feet', 'Reserved 3',
            '0,2,255,My Track,0,0,2,8421376', '0']
    base = datetime(1899, 12, 30)
    lines = []
    for lat, lon, alt, t in pts:
        days = (t - base).total_seconds() / 86400
        lines.append(f"{lat:.6f},{lon:.6f},0,{alt * 3.28084:.0f},{days:.10f},{t:%Y-%m-%d},{t:%H:%M:%S}")
    path.write_text('\n'.join(head + lines) + '\n')


MODES = {'walk': (4.5, 0.8, 5), 'bike': (14, 3, 3), 'bus': (28, 8, 3), 'car': (42, 10, 2)}  # mean, std km/h, sample sec


def make_trip(rng, start, end, mode, t0, anomaly):
    mean, std, dt = MODES[mode]
    sp = lambda: max(0.5, rng.normal(mean, std)) / 3.6  # m/s
    lat, lon = start
    t = t0
    pts = [(lat, lon, 520 + rng.normal(0, 3), t)]
    waypoint = np.array(end, dtype=float)
    kind = rng.choice(['spike', 'detour', 'stop', 'erratic']) if anomaly else None
    anomaly_at = rng.integers(20, 80) if anomaly else -1
    step = 0
    stop_left = 0
    detour = None
    while step < 2500:
        step += 1
        tgt = detour if detour is not None else waypoint
        dlat, dlon = tgt[0] - lat, tgt[1] - lon
        dist = math.hypot(dlat * 111000, dlon * 111000 * math.cos(math.radians(lat)))
        if dist < 25:
            if detour is not None:
                detour = None
                continue
            break
        v = sp()
        if stop_left > 0:
            v = 0.1 * rng.random()
            stop_left -= 1
        elif step == anomaly_at and kind == 'stop':
            stop_left = int(rng.integers(150, 300))  # 12-25 min at 5s sampling
        elif step == anomaly_at and kind == 'detour':
            detour = np.array([lat + rng.normal(0, 0.012), lon + rng.normal(0, 0.012)])
        if kind == 'spike' and anomaly_at <= step < anomaly_at + 8:
            v *= 6
        move = v * dt
        bearing_noise = rng.normal(0, 0.05 if mode != 'walk' else 0.12)
        if kind == 'erratic' and anomaly_at <= step < anomaly_at + 40:
            bearing_noise = rng.normal(0, 1.8)
        ang = math.atan2(dlon * math.cos(math.radians(lat)), dlat) + bearing_noise
        lat += move * math.cos(ang) / 111000
        lon += move * math.sin(ang) / (111000 * math.cos(math.radians(lat)))
        t = t + timedelta(seconds=dt)
        pts.append((lat, lon, 520 + rng.normal(0, 3), t))
    return pts


def gen_gps(n_users, rng):
    raw = ROOT / 'data' / 'raw' / 'geolife'
    count = 0
    for u in range(n_users):
        uid = f'{u:03d}'
        day0 = datetime(2024, 1, 8) + timedelta(days=int(rng.integers(0, 40)))
        for k in range(int(rng.integers(5, 9))):
            a, b = rng.choice(len(POIS), 2, replace=False)
            sa, sb = POIS[a], POIS[b]
            mode = rng.choice(list(MODES), p=[.45, .1, .2, .25])
            hour = int(rng.choice([8, 9, 10, 11, 14, 15, 16, 17, 18, 21, 23, 1]))
            t0 = day0 + timedelta(days=k, hours=hour, minutes=int(rng.integers(0, 60)))
            start = (sa[2] + rng.normal(0, .002), sa[3] + rng.normal(0, .002))
            end = (sb[2], sb[3])
            pts = make_trip(rng, start, end, mode, t0, anomaly=rng.random() < 0.25)
            if len(pts) > 10:
                write_plt(raw / uid / 'Trajectory' / f'{t0:%Y%m%d%H%M%S}.plt', pts)
                count += 1
    print(f'GPS: wrote {count} .plt trajectories for {n_users} users -> {raw}')


def gen_context(rng):
    ext = ROOT / 'data' / 'external'
    (ext / 'tourism').mkdir(parents=True, exist_ok=True)
    (ext / 'ncrb').mkdir(parents=True, exist_ok=True)
    yrs = list(range(2015, 2024))
    rows = []
    for y in yrs:
        f = 0.45 if y in (2020, 2021) else 1.0
        rows.append(('bhopal', y, int(3.2e6 * (1 + .06 * (y - 2015)) * f), int(21000 * (1 + .04 * (y - 2015)) * f)))
    pd.DataFrame(rows, columns=['location', 'year', 'domestic_visitors', 'foreign_visitors']).to_csv(
        ext / 'tourism' / 'bhopal_tourism.csv', index=False)
    cats = {'theft': 2400, 'robbery': 140, 'assault': 520, 'harassment': 310, 'fraud': 680, 'accident': 900}
    rows = [('bhopal', y, c, int(n * (1 + .03 * (y - 2015)) * rng.uniform(.9, 1.1))) for y in yrs for c, n in cats.items()]
    pd.DataFrame(rows, columns=['location', 'year', 'crime_category', 'crime_count']).to_csv(
        ext / 'ncrb' / 'bhopal_crime.csv', index=False)
    pd.DataFrame([(f'poi_{i}', n, c, la, lo, f'POINT({lo} {la})') for i, (n, c, la, lo) in enumerate(POIS)],
                 columns=['poi_id', 'name', 'category', 'latitude', 'longitude', 'geometry']).to_csv(
        ext / 'bhopal_poi.csv', index=False)
    feats = [{'type': 'Feature', 'properties': {'name': n, 'category': c, 'risk_level': r, 'description': d},
              'geometry': {'type': 'Polygon', 'coordinates': [box(la, lo, h)]}}
             for n, c, r, la, lo, h, d in GEOFENCES]
    LOC.mkdir(parents=True, exist_ok=True)
    (LOC / 'geofences.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': feats}, indent=1))
    print('Context: tourism, crime, POI csv + geofences.geojson written (synthetic)')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--users', type=int, default=30)
    p.add_argument('--seed', type=int, default=42)
    a = p.parse_args()
    rng = np.random.default_rng(a.seed)
    gen_gps(a.users, rng)
    gen_context(rng)
