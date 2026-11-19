import React from 'react';
import MapView from '../MapView.jsx';
import {HoursFee, OpenBadge, Photo} from '../components.jsx';
import {CATEGORY_ONE, VEG, cityNow, directions, fmtKm, href, nearest, useFences, wikiUrl, zonesAt} from '../lib.js';
import {useTrip} from '../trip.js';

export default function PlacePage({guide, id}) {
  const city = guide.slug, now = cityNow(guide.timezone), trip = useTrip(city);
  const {data: fences} = useFences(city);
  const p = guide.places.find(x => x.id === id);
  if (!p) return <main className="page"><div className="problem"><h2>That place isn't in the {guide.name} guide</h2>
    <p><a className="button" href={href.explore(city)}>See all places in {guide.name}</a></p></div></main>;
  const zones = zonesAt(fences, p.lat, p.lon), near = nearest(guide.places, p, 4), food = nearest(guide.food, p, 3);
  const inTrip = trip.has(p.id);
  return <main className="page place">
    <p className="crumb"><a href={href.explore(city)}>All places in {guide.name}</a></p>
    <section className="place-hero">
      <Photo title={p.wiki} alt={p.name} credit className="place-photo"/>
      <div className="place-hero-text">
        <p className="kicker">{CATEGORY_ONE[p.category]}, {p.area}</p>
        <h1>{p.name}</h1>
        <p className="lede">{p.summary}</p>
        <p><OpenBadge hours={p.hours} now={now}/></p>
        <p className="actions">
          <button onClick={() => trip.toggle(p.id)} aria-pressed={inTrip} className={inTrip ? 'ghost' : ''}>{inTrip ? 'Remove from trip' : 'Add to trip'}</button>
          <a className="button ghost" href={directions(p.lat, p.lon)} target="_blank" rel="noreferrer">Directions in Google Maps</a>
          {p.wiki && <a className="text-link" href={wikiUrl(p.wiki)} target="_blank" rel="noreferrer">Read more on Wikipedia</a>}
        </p>
      </div>
    </section>

    <div className="place-cols">
      <div>
        <h2>Plan your visit</h2>
        <HoursFee p={p}/>
        {p.tips?.length > 0 && <><h3>Good to know</h3><ul className="tips">{p.tips.map(t => <li key={t}>{t}</li>)}</ul></>}
        <div className={`safety-box ${zones.some(z => z.properties.risk_level >= 0.5) ? 'warn' : ''}`}>
          <h3>Safety</h3>
          <p>{p.safety}</p>
          {zones.map(z => <p key={z.properties.name} className="zone-line">
            Inside the zone <b>{z.properties.name}</b>: {z.properties.description}</p>)}
          <p className="small"><a href={href.safety(city)}>Turn on live tracking</a> before you go, so the safety team can help if something goes wrong.</p>
        </div>
      </div>
      <aside>
        <MapView height={340} center={[p.lat, p.lon]} zoom={15} fences={fences} fit label={`Map around ${p.name}`}
          pins={[{id: p.id, lat: p.lat, lon: p.lon, label: p.name, kind: 'place', active: true},
            ...near.map(n => ({id: n.id, lat: n.lat, lon: n.lon, label: n.name, kind: 'place', onClick: () => { location.hash = href.place(city, n.id); }})),
            ...food.map(f => ({id: 'f-' + f.id, lat: f.lat, lon: f.lon, label: f.name, kind: 'food'}))]}/>
        <h3>Nearby</h3>
        <ul className="near">{near.map(n => <li key={n.id}><a href={href.place(city, n.id)}>{n.name}</a><span>{fmtKm(n.dist)}</span></li>)}</ul>
        <h3>Eat nearby</h3>
        <ul className="near">{food.map(f => <li key={f.id}><span><b>{f.name}</b><small>{VEG[f.veg]}, {f.price}</small></span><span>{fmtKm(f.dist)}</span></li>)}</ul>
      </aside>
    </div>
  </main>;
}
