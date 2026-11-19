import React from 'react';
import {Loading, Photo, Problem} from '../components.jsx';
import {href, useCities} from '../lib.js';

export default function Home() {
  const {data: cities, error, loading} = useCities();
  if (loading) return <Loading what="Loading cities"/>;
  if (error) return <Problem error={error} retry={() => location.reload()}/>;
  return <main className="page home">
    <section className="home-hero">
      <h1>Explore the city.<br/>We'll keep watch.</h1>
      <p className="lede">City guides, a day-by-day trip planner and opt-in live safety tracking with SOS, in one place.
        Pick where you're going.</p>
    </section>

    <section className="city-tiles" aria-label="Cities">
      {cities.map(c => <a key={c.slug} href={href.city(c.slug)} className="city-tile">
        <Photo title={c.wiki} alt={c.name} kind="city"/>
        <div className="city-tile-text">
          <h2>{c.name}</h2>
          <p className="state">{c.state}</p>
          <p>{c.tagline}</p>
          <p className="counts">{c.counts.places} places, {c.counts.food} places to eat, {c.counts.stays} places to stay</p>
        </div>
      </a>)}
    </section>

    <section className="how" aria-labelledby="how-title">
      <h2 id="how-title">How the safety layer works</h2>
      <ol className="steps">
        <li><h3>Register once</h3>
          <p>You get a digital tourist ID. Its fingerprint is chained in a tamper-evident ledger; your name and phone number never go on it.</p></li>
        <li><h3>Turn on tracking while you explore</h3>
          <p>Your phone shares its location only while tracking is on, and you can stop at any time.</p></li>
        <li><h3>Get help fast</h3>
          <p>Press SOS, or let the risk engine spot trouble: unusual movement, a risky zone after dark, a long stop far off your planned route, or a phone that suddenly goes silent.
            Safety operators see it on their dashboard at once.</p></li>
      </ol>
    </section>

    <section className="home-split">
      <div>
        <h2>Plan the days, then share the route</h2>
        <p>Add places to a trip and Safe Tour orders them by distance and opening hours, warns you about closed days,
          and flags stops that would put you in a risky zone after dark. When you set off, share the next stop with the safety team.</p>
      </div>
      <div>
        <h2>For safety teams</h2>
        <p>The operator dashboard shows registered travellers on a live map with their risk level, open incidents, and the ledger that proves records haven't been edited.</p>
        <p><a className="button ghost" href={href.ops}>Open the operator dashboard</a></p>
      </div>
    </section>
  </main>;
}
