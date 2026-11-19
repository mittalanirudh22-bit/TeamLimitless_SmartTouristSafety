import React, {useState} from 'react';
import MapView from '../MapView.jsx';
import {EmergencyList, Facts, Photo, PlaceCard} from '../components.jsx';
import {FOOD_KIND, STAY_KIND, VEG, cityNow, href, useFences} from '../lib.js';
import {useTrip} from '../trip.js';

export function SafetyMap({guide, fences, places, height = 460, title = 'Map'}) {
  const [zones, setZones] = useState(true);
  const city = guide.slug;
  return <div className="safety-map">
    <MapView height={height} center={guide.center} zoom={guide.zoom} fences={fences} showFences={zones} label={title}
      pins={places.map(p => ({id: p.id, lat: p.lat, lon: p.lon, label: p.name, kind: p.category === 'daytrip' ? 'trip' : 'place',
        onClick: () => { location.hash = href.place(city, p.id); }}))}/>
    <div className="map-bar">
      <label className="switch"><input type="checkbox" checked={zones} onChange={e => setZones(e.target.checked)}/>
        <span>Safety layer</span></label>
      {zones && <span className="legend"><i className="lg-risk"/> Take care, especially after dark <i className="lg-calm"/> Busy, patrolled areas</span>}
    </div>
  </div>;
}

export default function CityPage({guide}) {
  const city = guide.slug, now = cityNow(guide.timezone), trip = useTrip(city);
  const {data: fences} = useFences(city);
  const must = guide.places.filter(p => p.must);
  const inTown = guide.places.filter(p => p.category !== 'daytrip');
  return <main className="page city">
    <section className="city-hero">
      <div className="city-hero-text">
        <p className="state">{guide.state}</p>
        <h1>{guide.name}</h1>
        <p className="lede">{guide.tagline}</p>
        <p>{guide.intro}</p>
        <p className="actions"><a className="button" href={href.explore(city)}>Explore {guide.places.length} places</a>
          <a className="button ghost" href={href.plan(city)}>Plan your days</a></p>
      </div>
      <Photo title={guide.wiki} alt={guide.name} kind="city" className="city-hero-photo" credit/>
    </section>

    <Facts rows={[['Best time to visit', guide.facts.best_time], ['Getting there', guide.facts.getting_there],
      ['Getting around', guide.facts.getting_around], ['Languages', guide.facts.languages]]}/>

    <section aria-labelledby="map-title">
      <div className="section-head"><h2 id="map-title">{guide.name} with the safety layer on</h2>
        <p className="muted">Pins are places in the guide. Shaded areas are the zones the risk engine watches. Tap a pin to open the place.</p></div>
      <SafetyMap guide={guide} fences={fences} places={inTown} title={`Map of ${guide.name}`}/>
    </section>

    <section aria-labelledby="must-title">
      <div className="section-head"><h2 id="must-title">Don't miss</h2><a href={href.explore(city)}>See all places</a></div>
      <div className="place-grid feature">
        {must.map((p, i) => <PlaceCard key={p.id} city={city} p={p} now={now} trip={trip} size={i === 0 ? 'big' : ''}/>)}
      </div>
    </section>

    <section className="two-col">
      <div>
        <div className="section-head"><h2>Eat like a local</h2><a href={href.eat(city)}>All food</a></div>
        <ul className="rows">{guide.food.slice(0, 4).map(f => <li key={f.id}>
          <b>{f.name}</b> <span className="muted">{f.area}</span>
          <p>{f.known_for}</p><p className="tags"><span>{FOOD_KIND[f.kind]}</span><span>{VEG[f.veg]}</span><span>{f.price}</span></p></li>)}</ul>
      </div>
      <div>
        <div className="section-head"><h2>Where to stay</h2><a href={href.eat(city) + '?stay'}>All stays</a></div>
        <ul className="rows">{guide.stays.slice(0, 4).map(s => <li key={s.id}>
          <b>{s.name}</b> <span className="muted">{s.area}</span>
          <p>{s.note}</p><p className="tags"><span>{STAY_KIND[s.kind] || 'Hotel'}</span><span>{s.price}</span></p></li>)}</ul>
      </div>
    </section>

    <section className="safety-strip" aria-labelledby="safe-title">
      <div>
        <h2 id="safe-title">Staying safe in {guide.name}</h2>
        <ul className="tips">{guide.safety_tips.map(t => <li key={t}>{t}</li>)}</ul>
        <p><a className="button sos-button" href={href.safety(city)}>Get your tourist ID and turn on tracking</a></p>
      </div>
      <div><h3>Numbers to save</h3><EmergencyList items={guide.emergency} compact/></div>
    </section>
  </main>;
}
