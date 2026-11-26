import React, {useEffect, useState} from 'react';
import MapView from '../MapView.jsx';
import {COLORS, request} from '../api.js';
import {cached} from '../lib.js';

const ago = s => s == null ? '' : s < 90 ? 'just now' : s < 5400 ? `${Math.round(s / 60)} min ago` : `${Math.round(s / 3600)} h ago`;

/** What family sees when they open a shared link: live position, signal, SOS. Refreshes every 15 seconds. */
export default function SharePage({token}) {
  const [v, setV] = useState(null), [err, setErr] = useState(null), [fences, setF] = useState(null), [guide, setG] = useState(null);
  useEffect(() => {
    let live = true;
    const tick = () => request('/api/share/' + encodeURIComponent(token))
      .then(d => { if (live) { setV(d); setErr(null); } })
      .catch(e => live && setErr(e.status === 410 ? 'This link has expired. Ask for a new one.'
        : e.status === 404 ? 'This link was stopped, or it is not a Safe Tour link.' : 'Cannot reach Safe Tour right now. Retrying…'));
    tick();
    const id = setInterval(tick, 15000);
    return () => { live = false; clearInterval(id); };
  }, [token]);
  useEffect(() => {
    if (!v?.city) return;
    request('/api/geofences?city=' + v.city).then(setF).catch(() => {});
    cached('/api/cities/' + v.city).then(setG).catch(() => {});
  }, [v?.city]);
  if (err && !v) return <main className="page"><div className="problem"><h1>Live location</h1><p>{err}</p></div></main>;
  if (!v) return <main className="page"><p className="muted loading">Loading…</p></main>;
  const state = v.sos ? 'sos' : v.signal === 'LOST' ? 'lost' : v.status !== 'TRACKING' ? 'off' : 'live';
  const line = {
    sos: `${v.name} pressed SOS. The safety team has been alerted. If you can't reach ${v.name}, call 112.`,
    lost: `No signal from ${v.name}'s phone since ${ago(v.last_seen_s)}. The safety team is alerted automatically if it stays silent.`,
    off: `${v.name} has turned live tracking off. Last known location is shown.`,
    live: `${v.name}'s phone is sharing its location. Updated ${ago(v.last_seen_s)}.`,
  }[state];
  return <main className="page share-page">
    <div className="page-head"><h1>{v.name}'s live location</h1>
      <p className="muted">{guide ? `In ${guide.name}. ` : ''}This link works until {new Date(v.expires_at).toLocaleString('en-IN', {day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit'})}.</p></div>
    <p className={`share-status share-${state}`} role="status">{line}</p>
    {err && <p className="note">{err}</p>}
    {v.latitude != null
      ? <MapView height={460} follow fences={fences} center={guide?.center || [v.latitude, v.longitude]} label={`${v.name}'s location`}
          points={[{id: 'p', lat: v.latitude, lon: v.longitude, color: state === 'lost' ? '#6b7385' : COLORS[v.risk_level] || '#1D2A5B', radius: 10, label: v.name, trail: v.trail}]}/>
      : <p className="empty">No location yet. It appears once {v.name} turns on tracking.</p>}
    <p className="actions" style={{marginTop: 14}}>
      {v.latitude != null && <a className="button ghost" href={`https://maps.google.com/?q=${v.latitude},${v.longitude}`} target="_blank" rel="noreferrer">Open in Google Maps</a>}
      <a className="button sos-sms" href="tel:112">Call 112</a></p>
    <p className="muted small">Shared by {v.name} through Safe Tour. Shaded areas are zones the safety team watches more closely.</p>
  </main>;
}
