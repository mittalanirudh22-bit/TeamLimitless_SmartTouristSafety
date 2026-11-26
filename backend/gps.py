"""Clean up phone GPS before it reaches the risk engine.

Phones report a position plus an accuracy radius (metres). Indoors and in narrow lanes that radius grows and the
position wanders, which would otherwise look like erratic movement to the anomaly model. Each new fix is blended with
the previous estimate in proportion to how much each can be trusted (a one-dimensional Kalman filter per axis): a
precise fix moves the estimate almost all the way, a vague one only a little. A fix that would need an impossible
speed is held back as a likely glitch or spoofed location, unless the next fix confirms the new place (a tunnel,
a flight, or the phone simply had no fix for a while).
"""
import math, os
from datetime import datetime, timezone

MAX_KMH = float(os.getenv('GPS_MAX_KMH', '250'))       # faster than any road or train journey in India
DEFAULT_ACC_M = float(os.getenv('GPS_DEFAULT_ACC_M', '25'))
DRIFT_MS = float(os.getenv('GPS_DRIFT_MS', '1.5'))      # how far the true position may move per second between fixes


def metres(lat1, lon1, lat2, lon2):
    r = math.radians
    a = math.sin(r(lat2 - lat1) / 2) ** 2 + math.cos(r(lat1)) * math.cos(r(lat2)) * math.sin(r(lon2 - lon1) / 2) ** 2
    return 12_742_000 * math.asin(math.sqrt(a))


def _ts(v):
    t = datetime.fromisoformat(v) if isinstance(v, str) else v
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def filter_fix(prev, lat, lon, acc, ts):
    """prev: the last stored fix {lat, lon, ts, var?, pending?} or None.
    Returns (lat, lon, variance_m2, verdict) with verdict 'ok', 'reanchor' or 'jump' (lat/lon None for a jump)."""
    acc = max(5.0, float(acc) if acc else DEFAULT_ACC_M)  # phones report the radius they're 68% sure of
    if not prev or prev.get('lat') is None:
        return lat, lon, acc * acc, 'ok'
    dt = max(1.0, (_ts(ts) - _ts(prev['ts'])).total_seconds())
    d = metres(prev['lat'], prev['lon'], lat, lon)
    if max(0.0, d - acc) / dt * 3.6 > MAX_KMH:
        p = prev.get('pending')
        if p and metres(p[0], p[1], lat, lon) < max(300.0, 2 * acc):
            return lat, lon, acc * acc, 'reanchor'  # two fixes agree on the new place: believe it
        return None, None, None, 'jump'
    P = (prev.get('var') or acc * acc) + (DRIFT_MS * dt) ** 2
    R = acc * acc
    K = P / (P + R)
    if d > 3 * math.sqrt(P + R):  # far outside both error circles: the traveller really moved
        K = 1.0
    return prev['lat'] + K * (lat - prev['lat']), prev['lon'] + K * (lon - prev['lon']), (1 - K) * P + (K * R if K == 1.0 else 0.0), 'ok'
