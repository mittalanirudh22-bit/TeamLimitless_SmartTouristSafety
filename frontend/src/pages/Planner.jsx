import React, {useEffect, useMemo, useState} from 'react';
import MapView from '../MapView.jsx';
import {request} from '../api.js';
import {directions, fmtTime, href, loadSession, useFences} from '../lib.js';
import {autoPlan, dateLabel, timeline, tripText, weekdayOf} from '../planner.js';
import {useTrip} from '../trip.js';

function useTraveller() {
  const session = loadSession();
  const [me, setMe] = useState(null);
  useEffect(() => {
    if (session?.token) request('/api/travellers/me', {headers: {'X-Tracking-Token': session.token}}).then(setMe).catch(() => setMe(null));
  }, [session?.token]);
  return {token: session?.token, me, setMe};
}

export default function Planner({guide}) {
  const city = guide.slug, trip = useTrip(city), {data: fences} = useFences(city), traveller = useTraveller();
  const [day, setDay] = useState(0), [note, setNote] = useState(null);
  const byId = useMemo(() => Object.fromEntries(guide.places.map(p => [p.id, p])), [guide]);
  const origin = {lat: guide.center[0], lon: guide.center[1]};
  const stops = trip.stops.filter(s => byId[s.id]);
  const days = Array.from({length: trip.days}, (_, d) => {
    const ps = stops.filter(s => Math.min(s.day, trip.days - 1) === d).map(s => byId[s.id]);
    return {d, ps, plan: timeline(ps, origin, weekdayOf(trip.start, d), fences)};
  });
  const sel = days[Math.min(day, trip.days - 1)];
  const notAdded = guide.places.filter(p => !trip.has(p.id));

  const setDays = n => trip.save(t => ({...t, days: n, stops: t.stops.map(s => ({...s, day: Math.min(s.day, n - 1)}))}));
  const move = (id, delta) => trip.save(t => {
    const list = [...t.stops], i = list.findIndex(s => s.id === id), me = list[i];
    let j = i + delta;
    while (j >= 0 && j < list.length && list[j].day !== me.day) j += delta;  // swap with the neighbour on the same day
    if (j < 0 || j >= list.length) return t;
    [list[i], list[j]] = [list[j], list[i]];
    return {...t, stops: list};
  });
  const toDay = (id, d) => trip.save(t => ({...t, stops: [...t.stops.filter(s => s.id !== id), {id, day: d}]}));
  const add = (id, d) => trip.save(t => ({...t, stops: [...t.stops, {id, day: d}]}));
  const remove = id => trip.save(t => ({...t, stops: t.stops.filter(s => s.id !== id)}));
  const plan = () => {
    if (stops.length && !confirm('Replace your current plan with a suggested one?')) return;
    trip.save(t => ({...t, stops: autoPlan(guide, t.days, t.start)}));
    setDay(0);
  };
  const copy = async () => {
    try { await navigator.clipboard.writeText(tripText(guide, {...trip, stops}, fences)); setNote('Plan copied. Paste it into a message to share it.'); }
    catch { setNote('Copying is blocked in this browser. Select the plan and copy it by hand.'); }
  };
  const goNow = async p => {
    try {
      const me = await request('/api/travellers/me/destination', {method: 'POST', body: {latitude: p.lat, longitude: p.lon},
        headers: {'X-Tracking-Token': traveller.token}});
      traveller.setMe(me);
      setNote(`Shared: you're heading to ${p.name}. The safety team will see if you move far off this route.`);
    } catch (e) { setNote(e.message); }
  };
  const tracking = traveller.me?.status === 'TRACKING' && traveller.me.city === city;

  return <main className="page planner">
    <div className="page-head">
      <h1>Plan your days in {guide.name}</h1>
      <p className="muted">Times are estimates from 9 am, using city traffic between stops. Your plan is saved in this browser.</p>
    </div>

    <div className="plan-controls">
      <label>Days<span className="stepper">
        <button className="ghost" aria-label="One day fewer" disabled={trip.days <= 1} onClick={() => setDays(trip.days - 1)}>−</button>
        <b aria-live="polite">{trip.days}</b>
        <button className="ghost" aria-label="One day more" disabled={trip.days >= 7} onClick={() => setDays(trip.days + 1)}>+</button></span></label>
      <label>Start date (optional, checks closing days)
        <input type="date" value={trip.start} onChange={e => trip.save(t => ({...t, start: e.target.value}))}/></label>
      <div className="actions">
        <button onClick={plan}>Plan it for me</button>
        <button className="ghost" onClick={copy} disabled={!stops.length}>Copy plan</button>
        <button className="ghost" onClick={() => confirm('Remove every stop from this trip?') && trip.save(t => ({...t, stops: []}))} disabled={!stops.length}>Clear</button>
      </div>
    </div>

    <p className={`track-banner ${tracking ? 'on' : ''}`}>
      {tracking ? 'Live tracking is on. Use "Going now" on a stop to share where you\'re heading with the safety team.'
        : <>Share your route with the safety team as you go. <a href={href.safety(city)}>{traveller.me ? 'Turn on tracking' : 'Get your tourist ID'}</a> first.</>}
    </p>
    {note && <p className="note" role="status">{note}</p>}

    {stops.length === 0 ? <div className="empty big">
      <h2>Your trip is empty</h2>
      <p>Let Safe Tour suggest a route for {trip.days} day{trip.days > 1 ? 's' : ''}, or add places one by one.</p>
      <p className="actions"><button onClick={plan}>Plan it for me</button><a className="button ghost" href={href.explore(city)}>Browse places</a></p>
    </div> : <div className="list-map">
      <div className="days">
        {days.map(({d, ps, plan: sched}) => <section key={d} className={`day ${sel.d === d ? 'on' : ''}`} aria-labelledby={`day-${d}`}>
          <header>
            <h2 id={`day-${d}`}><button className="day-pick" onClick={() => setDay(d)} aria-pressed={sel.d === d}>
              Day {d + 1}{dateLabel(trip.start, d) && <small>{dateLabel(trip.start, d)}</small>}</button></h2>
            {ps.length > 0 && <span className={sched.long ? 'warn-text' : 'muted'}>Ends about {fmtTime(sched.ends)}{sched.long ? ', a long day' : ''}</span>}
          </header>
          {ps.length === 0 && <p className="muted">Free day. Add places below or move some here.</p>}
          <ol className="stops">
            {sched.rows.map((r, i) => <li key={r.place.id}>
              <span className="stop-num" aria-hidden="true">{i + 1}</span>
              <div className="stop-body">
                <p className="stop-time">{fmtTime(r.start)} to {fmtTime(r.end)} <small>{r.travel} min to get here</small></p>
                <h3><a href={href.place(city, r.place.id)}>{r.place.name}</a></h3>
                {r.issues.map(x => <p key={x.text} className={`issue ${x.level}`}>{x.text}</p>)}
                <div className="stop-actions">
                  <button className="ghost small" aria-label={`Move ${r.place.name} earlier`} disabled={i === 0} onClick={() => move(r.place.id, -1)}>Earlier</button>
                  <button className="ghost small" aria-label={`Move ${r.place.name} later`} disabled={i === ps.length - 1} onClick={() => move(r.place.id, 1)}>Later</button>
                  {trip.days > 1 && <label className="sr-label"><span className="sr-only">Day for {r.place.name}</span>
                    <select value={d} onChange={e => toDay(r.place.id, +e.target.value)}>
                      {days.map(x => <option key={x.d} value={x.d}>Day {x.d + 1}</option>)}</select></label>}
                  <button className="ghost small" onClick={() => remove(r.place.id)}>Remove</button>
                  <a className="small" href={directions(r.place.lat, r.place.lon)} target="_blank" rel="noreferrer">Directions</a>
                  {tracking && <button className="small" onClick={() => goNow(r.place)}>Going now</button>}
                </div>
              </div>
            </li>)}
          </ol>
        </section>)}

        {notAdded.length > 0 && <section className="more">
          <h2>More places to add</h2>
          <ul>{notAdded.map(p => <li key={p.id}><a href={href.place(city, p.id)}>{p.name}</a>
            <button className="ghost small" onClick={() => add(p.id, sel.d)}>Add to day {sel.d + 1}</button></li>)}</ul>
        </section>}
      </div>
      <div className="sticky-map">
        <MapView height="calc(100vh - 170px)" center={guide.center} zoom={guide.zoom} fences={fences} fit label={`Route for day ${sel.d + 1}`}
          route={sel.ps.length ? [[origin.lat, origin.lon], ...sel.ps.map(p => [p.lat, p.lon])] : null}
          pins={sel.ps.map((p, i) => ({id: p.id, lat: p.lat, lon: p.lon, label: `${i + 1}. ${p.name}`, num: i + 1, kind: 'added'}))}/>
        <p className="muted small">Day {sel.d + 1} route, starting from central {guide.name}. Select another day to see its route.</p>
      </div>
    </div>}
  </main>;
}
