import React, {useMemo, useState} from 'react';
import MapView from '../MapView.jsx';
import {Chips, PlaceCard} from '../components.jsx';
import {CATEGORY, cityNow, href, openState, useFences} from '../lib.js';
import {useTrip} from '../trip.js';

export default function Explore({guide}) {
  const city = guide.slug, now = cityNow(guide.timezone), trip = useTrip(city);
  const {data: fences} = useFences(city);
  const [cat, setCat] = useState('all'), [q, setQ] = useState(''), [openOnly, setOpenOnly] = useState(false);
  const cats = [['all', 'All'], ...Object.entries(CATEGORY).filter(([k]) => guide.places.some(p => p.category === k))];
  const shown = useMemo(() => guide.places
    .filter(p => cat === 'all' || p.category === cat)
    .filter(p => !q || `${p.name} ${p.area} ${p.summary}`.toLowerCase().includes(q.toLowerCase()))
    .filter(p => !openOnly || openState(p.hours, now).open)
    .sort((a, b) => (b.must ? 1 : 0) - (a.must ? 1 : 0)), [guide, cat, q, openOnly, now.hm]); // eslint-disable-line
  const clear = () => { setCat('all'); setQ(''); setOpenOnly(false); };
  return <main className="page explore">
    <div className="page-head">
      <h1>Places to see in {guide.name}</h1>
      <p className="muted">Hours and fees last checked {guide.checked}. They change, so confirm at the ticket counter.</p>
    </div>
    <div className="filters">
      <label className="search"><span className="sr-only">Search places</span>
        <input type="search" value={q} onChange={e => setQ(e.target.value)} placeholder="Search by name or area"/></label>
      <Chips label="Category" options={cats} value={cat} onChange={setCat}/>
      <label className="switch"><input type="checkbox" checked={openOnly} onChange={e => setOpenOnly(e.target.checked)}/>
        <span>Open now ({now.day} {now.hm} local time)</span></label>
    </div>
    <div className="list-map">
      <div>
        {shown.length === 0
          ? <div className="empty"><p>No places match these filters.</p><button className="ghost" onClick={clear}>Clear filters</button></div>
          : <div className="place-grid">{shown.map(p => <PlaceCard key={p.id} city={city} p={p} now={now} trip={trip}/>)}</div>}
      </div>
      <div className="sticky-map">
        <MapView height="calc(100vh - 170px)" center={guide.center} zoom={guide.zoom} fences={fences} fit label={`Map of places in ${guide.name}`}
          fitPins={cat === 'daytrip' ? null : shown.filter(p => p.category !== 'daytrip')}
          pins={shown.map(p => ({id: p.id, lat: p.lat, lon: p.lon, label: p.name, kind: trip.has(p.id) ? 'added' : p.category === 'daytrip' ? 'trip' : 'place',
            onClick: () => { location.hash = href.place(city, p.id); }}))}/>
      </div>
    </div>
  </main>;
}
