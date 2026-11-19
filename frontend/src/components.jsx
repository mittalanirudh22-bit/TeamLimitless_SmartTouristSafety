import React, {useState} from 'react';
import {CATEGORY_ONE, biggerThumb, href, hoursText, openState, useWikiImage, wikiUrl} from './lib.js';

/** A Wikipedia photo when one loads; otherwise a patterned panel, so layouts never break offline. */
export function Photo({title, alt, kind = 'place', className = '', credit = false}) {
  const src = useWikiImage(title);
  const [stage, setStage] = useState(0);  // 0: large, 1: default thumbnail, 2: give up
  const url = src && (stage === 0 ? biggerThumb(src) : src);
  return <div className={`photo photo-${kind} ${className}`}>
    {url && stage < 2 && <img src={url} alt={alt} loading="lazy" onError={() => setStage(s => s + 1)}/>}
    {(!url || stage >= 2) && <span className="photo-mark" aria-hidden="true">{(alt || '?').slice(0, 1)}</span>}
    {credit && url && stage < 2 && <a className="photo-credit" href={wikiUrl(title)} target="_blank" rel="noreferrer">Photo: Wikipedia</a>}
  </div>;
}

export function OpenBadge({hours, now}) {
  const s = openState(hours, now);
  if (s.open === null) return null;
  return <span className={`open-badge ${s.open ? 'is-open' : 'is-shut'}`}>{s.label}</span>;
}

export function PlaceCard({city, p, now, trip, size = ''}) {
  const inTrip = trip?.has(p.id);
  return <article className={`place-card ${size}`}>
    <a href={href.place(city, p.id)} className="place-card-link">
      <Photo title={p.wiki} alt={p.name}/>
      <div className="place-card-body">
        <p className="kicker">{CATEGORY_ONE[p.category]}, {p.area}</p>
        <h3>{p.name}</h3>
        {size === 'big' && <p className="place-card-summary">{p.summary}</p>}
        <p className="place-card-meta"><OpenBadge hours={p.hours} now={now}/> <span>{p.fee.indian}</span></p>
      </div>
    </a>
    {trip && <button className={`add-trip ${inTrip ? 'added' : ''}`} onClick={() => trip.toggle(p.id)} aria-pressed={inTrip}>
      {inTrip ? 'In your trip' : 'Add to trip'}</button>}
  </article>;
}

export function Facts({rows}) {
  return <dl className="facts">{rows.filter(r => r[1]).map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>;
}

export function HoursFee({p}) {
  return <Facts rows={[
    ['Hours', hoursText(p.hours) + (p.hours.note ? `. ${p.hours.note}` : '')],
    ['Entry for Indian citizens', p.fee.indian],
    ['Entry for foreign visitors', p.fee.foreign],
    ['Time to allow', p.visit_min >= 60 ? `About ${Math.round(p.visit_min / 30) / 2} hours` : `About ${p.visit_min} minutes`],
    ['Best time', p.best],
  ]}/>;
}

export function EmergencyList({items, compact = false}) {
  return <ul className={`emergency ${compact ? 'compact' : ''}`}>
    {items.map(e => <li key={e.number + e.label}>
      <a href={`tel:${e.number}`} className="call-number" aria-label={`Call ${e.label}, ${e.number}`}>{e.number}</a>
      <span><b>{e.label}</b>{!compact && e.note && <small>{e.note}</small>}</span>
    </li>)}
  </ul>;
}

export function Chips({options, value, onChange, label}) {
  return <div className="chips" role="group" aria-label={label}>
    {options.map(([v, text]) => <button key={v} className={`chip ${value === v ? 'on' : ''}`} aria-pressed={value === v} onClick={() => onChange(v)}>{text}</button>)}
  </div>;
}

export function Loading({what = 'Loading'}) {
  return <main className="page"><p className="muted loading">{what}…</p></main>;
}

export function Problem({error, retry}) {
  const missing = error?.status === 404;
  return <main className="page"><div className="problem">
    <h2>{missing ? 'We don\'t have a guide for that city yet' : 'The Safe Tour server isn\'t responding'}</h2>
    <p>{missing ? 'Pick one of the cities we cover.' : 'Check that the API is running (uvicorn backend.main:app), then try again.'}</p>
    <p className="actions"><a className="button" href={href.home}>See all cities</a>{retry && !missing && <button className="ghost" onClick={retry}>Try again</button>}</p>
  </div></main>;
}
