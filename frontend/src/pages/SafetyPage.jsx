import React from 'react';
import Traveller from '../Traveller.jsx';
import {EmergencyList} from '../components.jsx';
import {useFences} from '../lib.js';
import {SafetyMap} from './CityPage.jsx';

const SIGNALS = [
  ['Unusual movement', 'A sudden stop, sharp turns or speed that doesn\'t fit walking or normal traffic, spotted by a machine-learning model.'],
  ['Risky zones', 'Being inside one of the shaded zones on the map.'],
  ['Off your route', 'Moving far from the line to the stop you said you were going to.'],
  ['Not moving', 'Staying still for a long time.'],
  ['Night time', 'Late night and early morning count for more.'],
  ['City context', 'A small, city-wide adjustment from public crime statistics.'],
  ['SOS', 'Pressing SOS always raises an alert straight away.'],
  ['Phone goes silent', 'No location for 10 minutes while tracking is on (5 minutes in a risky zone, at night or at an elevated risk level) alerts the safety team. Stop tracking first if you switch your phone off.'],
];

export default function SafetyPage({guide}) {
  const {data: fences} = useFences(guide.slug);
  const zones = [...(fences?.features || [])].sort((a, b) => b.properties.risk_level - a.properties.risk_level);
  return <main className="page safety">
    <div className="page-head">
      <h1>Safety in {guide.name}</h1>
      <p className="lede">Save these numbers, look over the zones, and turn on tracking while you're out.</p>
    </div>
    <div className="safety-cols">
      <div className="safety-main"><Traveller guide={guide}/></div>
      <aside className="safety-side">
        <h2>Emergency numbers</h2>
        <EmergencyList items={guide.emergency}/>
        <h2>Tips for {guide.name}</h2>
        <ul className="tips">{guide.safety_tips.map(t => <li key={t}>{t}</li>)}</ul>
      </aside>
    </div>

    <section aria-labelledby="zones-title">
      <div className="section-head"><h2 id="zones-title">Zones the risk engine watches</h2></div>
      <div className="zones">
        <SafetyMap guide={guide} fences={fences} places={guide.places.filter(p => p.category !== 'daytrip')} height={380} title={`Safety zones in ${guide.name}`}/>
        <ul className="zone-list">{zones.map(z => <li key={z.properties.name} className={z.properties.risk_level >= 0.5 ? 'risk' : 'calm'}>
          <b>{z.properties.name}</b><span>{z.properties.description}</span></li>)}</ul>
      </div>
      <p className="muted small">The zones are illustrative for this demo, drawn by hand rather than from police data.</p>
    </section>

    <section aria-labelledby="signals-title">
      <h2 id="signals-title">What raises your risk level</h2>
      <p>While tracking is on, each location update is scored from seven signals, and the safety team is alerted if your phone stops sending them. The score is a guide for the safety team, not a judgement about you.</p>
      <dl className="signals">{SIGNALS.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
    </section>
  </main>;
}
