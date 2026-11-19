import {useCallback, useEffect, useState} from 'react';
import {recall, store} from './lib.js';
import {emptyTrip} from './planner.js';

const key = city => `safetour_trip_${city}`;
const EVT = 'safetour-trip';

/** The traveller's trip for a city, saved in this browser and shared by every component on the page. */
export function useTrip(city) {
  const load = () => (city ? recall(key(city), null) : null) || emptyTrip();
  const [trip, setLocal] = useState(load);
  useEffect(() => {
    setLocal(load());
    const f = () => setLocal(load());
    addEventListener(EVT, f);
    return () => removeEventListener(EVT, f);
  }, [city]); // eslint-disable-line
  const save = useCallback(next => {
    const value = typeof next === 'function' ? next(load()) : next;
    store(key(city), value);
    dispatchEvent(new Event(EVT));
  }, [city]); // eslint-disable-line
  const ids = new Set(trip.stops.map(s => s.id));
  return {
    ...trip, save,
    has: id => ids.has(id),
    toggle: id => save(t => t.stops.some(s => s.id === id)
      ? {...t, stops: t.stops.filter(s => s.id !== id)}
      : {...t, stops: [...t.stops, {id, day: 0}]}),
  };
}
