/** Trip planning logic, kept free of React so it is easy to test and reason about. */
import {km, toMin, fromMin, fmtTime, zonesAt, WEEKDAYS, DAY_FULL} from './lib.js';

export const DAY_START = '09:00';
const DAY_END = toMin('19:30');
const NIGHT = toMin('18:30');

export const emptyTrip = () => ({days: 2, start: '', stops: []});

/** Minutes to get from a to b: city traffic for short hops, highway speed for day trips, plus parking/walking. */
export function travelMin(a, b) {
  const d = km(a, b);
  return Math.round(d / (d > 15 ? 45 : 20) * 60) + 10;
}

export function weekdayOf(start, dayIndex) {
  if (!start) return null;
  const d = new Date(start + 'T12:00:00');
  if (isNaN(d)) return null;
  d.setDate(d.getDate() + dayIndex);
  return WEEKDAYS[d.getDay()];
}

export function dateLabel(start, dayIndex) {
  if (!start) return null;
  const d = new Date(start + 'T12:00:00');
  if (isNaN(d)) return null;
  d.setDate(d.getDate() + dayIndex);
  return d.toLocaleDateString('en-IN', {weekday: 'short', day: 'numeric', month: 'short'});
}

/** Estimated schedule for one day's stops (in order), with problems a traveller should know about. */
export function timeline(places, origin, weekday, fences) {
  let t = toMin(DAY_START), here = origin;
  const rows = places.map(p => {
    const travel = travelMin(here, p), arrive = Math.ceil((t + travel) / 5) * 5, h = p.hours || {}, issues = [];  // plan in 5-minute steps
    let begin = arrive;
    if (weekday && (h.closed || []).includes(weekday)) issues.push({level: 'bad', text: `Closed on ${DAY_FULL[weekday]}. Move it to another day.`});
    if (h.open && arrive < toMin(h.open)) {
      begin = toMin(h.open);
      issues.push({level: 'info', text: `Opens at ${fmtTime(h.open)}; you'd wait ${begin - arrive} min.`});
    }
    const end = begin + p.visit_min;
    if (h.close && end > toMin(h.close)) issues.push({level: 'bad', text: `Closes at ${fmtTime(h.close)}, before you'd finish.`});
    const risky = zonesAt(fences, p.lat, p.lon).find(z => z.properties.risk_level >= 0.5);
    if (risky && end > NIGHT) issues.push({level: 'bad', text: `You'd be in "${risky.properties.name}" after dark. Go earlier in the day.`});
    else if (risky) issues.push({level: 'info', text: `Inside the flagged zone "${risky.properties.name}". Leave before dark.`});
    t = end; here = p;
    return {place: p, travel, arrive: fromMin(arrive), start: fromMin(begin), end: fromMin(end), issues};
  });
  return {rows, ends: fromMin(t), long: t > DAY_END};
}

/** Fill the days with a sensible route: must-see places first, nearest next, respecting opening hours and closed days.
 *  With two or more days, the last day goes to the out-of-town trips. */
export function autoPlan(guide, days, start) {
  const center = {lat: guide.center[0], lon: guide.center[1]};
  const city = guide.places.filter(p => p.category !== 'daytrip');
  const trips = guide.places.filter(p => p.category === 'daytrip');
  const tripDays = trips.length && days >= 2 ? (days >= 4 && trips.length > 2 ? 2 : 1) : 0;
  const used = new Set(), stops = [];

  const fill = (pool, day, until) => {
    const weekday = weekdayOf(start, day);
    let t = toMin(DAY_START), here = center;
    for (;;) {
      let best = null, bestCost = Infinity;
      for (const p of pool) {
        if (used.has(p.id) || (weekday && (p.hours?.closed || []).includes(weekday))) continue;
        const arrive = t + travelMin(here, p), h = p.hours || {};
        const begin = h.open ? Math.max(arrive, toMin(h.open)) : arrive, end = begin + p.visit_min;
        if (end > Math.min(until, h.close ? toMin(h.close) : until)) continue;
        const cost = (begin - t) + (p.must ? 0 : 45);  // travel + waiting, with a nudge towards must-sees
        if (cost < bestCost) { best = {p, end}; bestCost = cost; }
      }
      if (!best) return;
      used.add(best.p.id); stops.push({id: best.p.id, day});
      t = best.end; here = best.p;
    }
  };

  for (let d = 0; d < days - tripDays; d++) fill(city, d, DAY_END);
  for (let d = days - tripDays; d < days; d++) fill(trips, d, toMin('18:00'));
  return stops;
}

export function tripText(guide, trip, fences) {
  const byId = Object.fromEntries(guide.places.map(p => [p.id, p]));
  const origin = {lat: guide.center[0], lon: guide.center[1]};
  const lines = [`${guide.name} trip plan (Safe Tour)`, ''];
  for (let d = 0; d < trip.days; d++) {
    const ps = trip.stops.filter(s => s.day === d).map(s => byId[s.id]).filter(Boolean);
    lines.push(`Day ${d + 1}${dateLabel(trip.start, d) ? ` (${dateLabel(trip.start, d)})` : ''}`);
    if (!ps.length) lines.push('  Free day');
    for (const r of timeline(ps, origin, weekdayOf(trip.start, d), fences).rows)
      lines.push(`  ${fmtTime(r.start)}–${fmtTime(r.end)}  ${r.place.name}`);
    lines.push('');
  }
  lines.push('Emergency: 112. Tourist helpline: 1363.');
  return lines.join('\n');
}
