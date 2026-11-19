import React, {useEffect} from 'react';
import {createRoot} from 'react-dom/client';
import Ops from './Ops.jsx';
import Home from './pages/Home.jsx';
import CityPage from './pages/CityPage.jsx';
import Explore from './pages/Explore.jsx';
import PlacePage from './pages/PlacePage.jsx';
import EatStay from './pages/EatStay.jsx';
import Planner from './pages/Planner.jsx';
import SafetyPage from './pages/SafetyPage.jsx';
import {Loading, Problem} from './components.jsx';
import {href, rememberCity, useCities, useGuide, useRoute} from './lib.js';
import {useTrip} from './trip.js';
import './style.css';

const NAV = [['city', 'Overview'], ['explore', 'Explore'], ['plan', 'Trip planner'], ['eat', 'Eat and stay'], ['safety', 'Safety']];
const SAME_PAGE = {city: href.city, explore: href.explore, place: href.explore, eat: href.eat, plan: href.plan, safety: href.safety};

function Header({route}) {
  const {data: cities} = useCities(), city = route.city, trip = useTrip(city);
  const ops = route.page === 'ops';
  return <header className="site-head">
    <a className="skip" href="#content" onClick={e => { e.preventDefault(); document.getElementById('content')?.focus(); }}>Skip to content</a>
    <div className="site-head-row">
      <a className="brand" href={href.home}>Safe Tour</a>
      {!ops && cities && <label className="city-switch"><span className="sr-only">City</span>
        <select value={city || ''} onChange={e => { location.hash = e.target.value ? (SAME_PAGE[route.page] || href.city)(e.target.value) : href.home; }}>
          {!city && <option value="">Choose a city</option>}
          {cities.map(c => <option key={c.slug} value={c.slug}>{c.name}</option>)}
        </select></label>}
      {ops && <a className="back-link" href={href.home}>Tourist site</a>}
      <a className="call-112" href="tel:112" aria-label="Call 112, the national emergency number">Emergency 112</a>
    </div>
    {city && !ops && <nav className="site-nav" aria-label={`Guide sections`}>
      {NAV.map(([page, label]) => <a key={page} href={(SAME_PAGE[page])(city)}
        aria-current={route.page === page || (page === 'explore' && route.page === 'place') ? 'page' : undefined}>
        {label}{page === 'plan' && trip.stops.length > 0 && <span className="count">{trip.stops.length}</span>}</a>)}
    </nav>}
  </header>;
}

function Page({route}) {
  const needsGuide = ['city', 'explore', 'place', 'eat', 'plan', 'safety'].includes(route.page) && route.city;
  const {data: guide, error, loading} = useGuide(needsGuide ? route.city : null);
  useEffect(() => { if (guide) rememberCity(guide.slug); }, [guide]);
  useEffect(() => {
    const names = {city: '', explore: 'Places to see', place: 'Place', eat: 'Eat and stay', plan: 'Trip planner', safety: 'Safety'};
    document.title = route.page === 'ops' ? 'Operator dashboard – Safe Tour'
      : guide ? `${names[route.page] ? names[route.page] + ' in ' : ''}${guide.name} – Safe Tour` : 'Safe Tour';
  }, [route.page, guide]);
  if (route.page === 'ops') return <Ops/>;
  if (!needsGuide) return <Home/>;
  if (loading) return <Loading what="Loading the city guide"/>;
  if (error || !guide) return <Problem error={error} retry={() => location.reload()}/>;
  switch (route.page) {
    case 'explore': return <Explore guide={guide}/>;
    case 'place': return <PlacePage guide={guide} id={route.id}/>;
    case 'eat': return <EatStay key={route.query.toString()} guide={guide} query={route.query}/>;
    case 'plan': return <Planner guide={guide}/>;
    case 'safety': return <SafetyPage guide={guide}/>;
    default: return <CityPage guide={guide}/>;
  }
}

function App() {
  const route = useRoute();
  return <>
    <Header route={route}/>
    <div id="content" tabIndex={-1}><Page route={route}/></div>
    <footer className="site-foot">
      <p>Safe Tour by Team Limitless. City information last checked November 2026; hours and fees change, so confirm locally.
        Photos from Wikipedia, maps from OpenStreetMap contributors.</p>
      <p>The anomaly model flags unusual movement, not crime. The risk score supports decisions; it is not a calibrated probability.
        The blockchain ID is a private hash-chain ledger holding hashes only, with no personal data. Demo tourists and safety zones are synthetic.</p>
      <p><a href={href.ops}>Operator dashboard</a></p>
    </footer>
  </>;
}

createRoot(document.getElementById('root')).render(<App/>);
