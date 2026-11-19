import React, {useState} from 'react';
import MapView from '../MapView.jsx';
import {Chips} from '../components.jsx';
import {FOOD_KIND, STAY_KIND, VEG, directions} from '../lib.js';

const PRICE = [['any', 'Any budget'], ['₹', '₹ budget'], ['₹₹', '₹₹ mid-range'], ['₹₹₹', '₹₹₹ splurge']];

export default function EatStay({guide, query}) {
  const [tab, setTab] = useState(query?.has('stay') ? 'stay' : 'eat');
  const [veg, setVeg] = useState(false), [price, setPrice] = useState('any'), [active, setActive] = useState(null);
  const items = (tab === 'eat' ? guide.food : guide.stays)
    .filter(x => price === 'any' || x.price === price)
    .filter(x => tab !== 'eat' || !veg || x.veg === 'veg');
  return <main className="page eat">
    <div className="page-head">
      <h1>{tab === 'eat' ? `Where to eat in ${guide.name}` : `Where to stay in ${guide.name}`}</h1>
      <div className="tabs" role="tablist">
        <button role="tab" aria-selected={tab === 'eat'} className={tab === 'eat' ? 'on' : ''} onClick={() => setTab('eat')}>Eat</button>
        <button role="tab" aria-selected={tab === 'stay'} className={tab === 'stay' ? 'on' : ''} onClick={() => setTab('stay')}>Stay</button>
      </div>
    </div>
    <div className="filters">
      <Chips label="Budget" options={PRICE} value={price} onChange={setPrice}/>
      {tab === 'eat' && <label className="switch"><input type="checkbox" checked={veg} onChange={e => setVeg(e.target.checked)}/><span>Vegetarian only</span></label>}
    </div>
    <div className="list-map">
      <ul className="listing">
        {items.length === 0 && <li className="empty"><p>Nothing matches. Try another budget.</p></li>}
        {items.map(x => <li key={x.id} className={active === x.id ? 'on' : ''} onMouseEnter={() => setActive(x.id)} onFocus={() => setActive(x.id)} tabIndex={-1}>
          <div className="listing-top"><h2>{x.name}</h2><span className="price">{x.price}</span></div>
          <p className="muted">{x.area}</p>
          <p>{x.known_for || x.note}</p>
          <p className="tags">
            <span>{tab === 'eat' ? FOOD_KIND[x.kind] : STAY_KIND[x.kind] || 'Hotel'}</span>
            {tab === 'eat' && <span className={`veg-${x.veg}`}>{VEG[x.veg]}</span>}
            <a href={directions(x.lat, x.lon)} target="_blank" rel="noreferrer">Directions</a>
          </p>
        </li>)}
      </ul>
      <div className="sticky-map">
        <MapView height="calc(100vh - 170px)" center={guide.center} zoom={guide.zoom} fit showFences={false} label={`Map of ${tab === 'eat' ? 'food' : 'stays'}`}
          pins={items.map(x => ({id: x.id, lat: x.lat, lon: x.lon, label: x.name, kind: tab === 'eat' ? 'food' : 'stay', active: active === x.id,
            onClick: () => setActive(x.id)}))}/>
      </div>
    </div>
    <p className="muted small">We list places by reputation and type only, with no ratings. Prices are rough bands; check current rates before booking.</p>
  </main>;
}
