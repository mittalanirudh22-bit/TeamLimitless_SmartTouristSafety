import {useEffect, useState} from 'react';
import {request} from './api.js';

// ---------- data loading (cached per URL for the session) ----------
const cache = new Map();
export function cached(url) {
  if (!cache.has(url)) cache.set(url, request(url).catch(e => { cache.delete(url); throw e; }));
  return cache.get(url);
}
export function useAsync(fn, deps) {
  const [s, set] = useState({data: null, error: null, loading: true});
  useEffect(() => {
    let live = true;
    set(x => ({...x, loading: true}));
    fn().then(d => live && set({data: d, error: null, loading: false}),
              e => live && set({data: null, error: e, loading: false}));
    return () => { live = false; };
  }, deps); // eslint-disable-line
  return s;
}
export const useCities = () => useAsync(() => cached('/api/cities'), []);
export const useGuide = city => useAsync(() => city ? cached('/api/cities/' + city) : Promise.resolve(null), [city]);
export const useFences = city => useAsync(() => city ? cached('/api/geofences?city=' + city) : Promise.resolve(null), [city]);

// ---------- hash routing ----------
export function parseRoute(hash) {
  const [path, q = ''] = hash.replace(/^#\/?/, '').split('?');
  const parts = path.split('/').filter(Boolean).map(decodeURIComponent), query = new URLSearchParams(q);
  if (parts[0] === 'ops') return {page: 'ops', query};
  if (parts[0] === 'share' && parts[1]) return {page: 'share', token: parts[1], query};
  if (parts[0] === 'safety') return {page: 'safety', city: lastCity(), query};
  if (parts[0] === 'c' && parts[1]) {
    const city = parts[1], sub = parts[2] || 'city';
    if (sub === 'place') return {page: 'place', city, id: parts[3], query};
    return {page: ['explore', 'eat', 'plan', 'safety'].includes(sub) ? sub : 'city', city, query};
  }
  return {page: 'home', query};
}
export function useRoute() {
  const [hash, setHash] = useState(location.hash);
  useEffect(() => {
    const f = () => { setHash(location.hash); window.scrollTo(0, 0); };
    addEventListener('hashchange', f);
    return () => removeEventListener('hashchange', f);
  }, []);
  return parseRoute(hash);
}
export const href = {
  home: '#/', ops: '#/ops',
  city: c => `#/c/${c}`, explore: c => `#/c/${c}/explore`, eat: c => `#/c/${c}/eat`,
  plan: c => `#/c/${c}/plan`, safety: c => `#/c/${c}/safety`, place: (c, id) => `#/c/${c}/place/${id}`,
};

// ---------- small persistence helpers (storage can be unavailable: private mode, embedded views) ----------
export function store(key, val) {
  try { val == null ? localStorage.removeItem(key) : localStorage.setItem(key, JSON.stringify(val)); } catch { /* ignore */ }
}
export function recall(key, fallback = null) {
  try { const v = localStorage.getItem(key); return v == null ? fallback : JSON.parse(v); } catch { return fallback; }
}
export const lastCity = () => recall('safetour_city', null);
export const rememberCity = c => store('safetour_city', c);
export const loadSession = () => recall('limitless_session', null);

// ---------- labels ----------
export const CATEGORY = {
  heritage: 'Heritage', museum: 'Museums', nature: 'Nature', faith: 'Faith', market: 'Markets', daytrip: 'Day trips',
};
/** Singular labels for one place, e.g. "Museum, Shyamla Hills". */
export const CATEGORY_ONE = {
  heritage: 'Heritage', museum: 'Museum', nature: 'Nature', faith: 'Place of worship', market: 'Market', daytrip: 'Day trip',
};
export const FOOD_KIND = {street: 'Street food', restaurant: 'Restaurant', sweets: 'Sweets and snacks', cafe: 'Cafe'};
export const STAY_KIND = {heritage: 'Heritage hotel', luxury: 'Luxury', government: 'State tourism', area: 'Neighbourhood'};
export const VEG = {veg: 'Vegetarian', 'non-veg': 'Non-vegetarian', both: 'Veg and non-veg'};
export const DAY_FULL = {Mon: 'Mondays', Tue: 'Tuesdays', Wed: 'Wednesdays', Thu: 'Thursdays', Fri: 'Fridays', Sat: 'Saturdays', Sun: 'Sundays'};
export const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

// ---------- time ----------
export function fmtTime(hm) {
  let [h, m] = hm.split(':').map(Number);
  const ampm = h >= 12 ? 'pm' : 'am';
  h = h % 12 || 12;
  return m ? `${h}:${String(m).padStart(2, '0')} ${ampm}` : `${h} ${ampm}`;
}
export const toMin = hm => { const [h, m] = hm.split(':').map(Number); return h * 60 + m; };
export const fromMin = n => `${String(Math.floor(n / 60) % 24).padStart(2, '0')}:${String(Math.round(n % 60)).padStart(2, '0')}`;
export function hoursText(h) {
  if (!h?.open) return h?.text || 'Hours not listed';
  const closed = (h.closed || []).map(d => DAY_FULL[d]).join(' and ');
  return `${fmtTime(h.open)} to ${fmtTime(h.close)}${closed ? `, closed ${closed}` : ', every day'}`;
}
export function cityNow(tz = 'Asia/Kolkata') {
  const parts = new Intl.DateTimeFormat('en-GB', {timeZone: tz, weekday: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23'}).formatToParts(new Date());
  const g = t => parts.find(p => p.type === t)?.value;
  return {day: g('weekday'), hm: `${g('hour')}:${g('minute')}`};
}
/** {open: true|false|null, label} for a place's hours at the given city time. */
export function openState(h, now) {
  if (!h?.open) return {open: null, label: h?.text || ''};
  if ((h.closed || []).includes(now.day)) return {open: false, label: 'Closed today'};
  if (now.hm < h.open) return {open: false, label: `Opens at ${fmtTime(h.open)}`};
  if (now.hm >= h.close) return {open: false, label: `Closed for today, opens ${fmtTime(h.open)}`};
  return {open: true, label: `Open until ${fmtTime(h.close)}`};
}

// ---------- geography ----------
export function km(a, b) {
  const r = x => x * Math.PI / 180, dLat = r(b.lat - a.lat), dLon = r(b.lon - a.lon);
  const x = Math.sin(dLat / 2) ** 2 + Math.cos(r(a.lat)) * Math.cos(r(b.lat)) * Math.sin(dLon / 2) ** 2;
  return 12742 * Math.asin(Math.sqrt(x));
}
export const directions = (lat, lon) => `https://www.google.com/maps/dir/?api=1&destination=${lat},${lon}`;
function inRing(lon, lat, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j];
    if ((yi > lat) !== (yj > lat) && lon < (xj - xi) * (lat - yi) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}
/** Safety zones (GeoJSON features) that contain the point, riskiest first. */
export function zonesAt(fences, lat, lon) {
  return (fences?.features || [])
    .filter(f => f.geometry?.type === 'Polygon' && inRing(lon, lat, f.geometry.coordinates[0]))
    .sort((a, b) => b.properties.risk_level - a.properties.risk_level);
}
export const nearest = (items, from, n) =>
  items.filter(x => x.id !== from.id).map(x => ({...x, dist: km(from, x)})).sort((a, b) => a.dist - b.dist).slice(0, n);
export const fmtKm = d => d < 1 ? `${Math.round(d * 1000 / 50) * 50} m` : `${d.toFixed(d < 10 ? 1 : 0)} km`;

// ---------- photos from Wikipedia (loaded in the visitor's browser; the page works without them) ----------
const pending = new Map();
function wikiThumb(title) {
  const key = 'wikiimg:' + title;
  try { const hit = sessionStorage.getItem(key); if (hit !== null) return Promise.resolve(hit || null); } catch { /* ignore */ }
  if (!pending.has(title)) {
    pending.set(title, fetch(`https://en.wikipedia.org/api/rest_v1/page/summary/${encodeURIComponent(title)}`)
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        const src = d?.thumbnail?.source || '';
        try { sessionStorage.setItem(key, src); } catch { /* ignore */ }
        return src || null;
      })
      .catch(() => null));
  }
  return pending.get(title);
}
export function useWikiImage(title) {
  const [src, setSrc] = useState(null);
  useEffect(() => {
    let live = true;
    setSrc(null);
    if (title) wikiThumb(title).then(s => live && setSrc(s));
    return () => { live = false; };
  }, [title]);
  return src;
}
/** Wikimedia serves any width up to the original; ask for a sharper one and fall back to the default thumbnail. */
export const biggerThumb = src => src.replace(/\/(\d+)px-([^/]+)$/, '/960px-$2');
export const wikiUrl = title => `https://en.wikipedia.org/wiki/${encodeURIComponent(title)}`;
