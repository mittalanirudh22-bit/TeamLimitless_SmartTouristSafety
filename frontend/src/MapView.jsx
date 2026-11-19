import React, {useEffect, useRef} from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));

/**
 * points: live tracked people [{id,lat,lon,color,radius,label,trail,onClick}]
 * pins:   places to show [{id,lat,lon,label,kind:'place'|'food'|'stay'|'trip',num,active,onClick}]
 * fences: GeoJSON safety zones; showFences toggles them. route: [[lat,lon],...] drawn as a line.
 */
export default function MapView({points = [], pins = [], fences, showFences = true, route, center = [23.2599, 77.4126], zoom = 12,
                                  follow = false, fit = false, fitPins, height = 420, label = 'Map'}) {
  const el = useRef(), map = useRef(), layers = useRef({}), fitted = useRef(false);
  useEffect(() => {
    const mp = map.current = L.map(el.current, {scrollWheelZoom: false}).setView(center, zoom);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {attribution: '© OpenStreetMap contributors'}).addTo(mp);
    for (const k of ['fences', 'route', 'pins', 'points']) layers.current[k] = L.layerGroup().addTo(mp);
    mp.on('focus', () => mp.scrollWheelZoom.enable());
    mp.on('blur', () => mp.scrollWheelZoom.disable());
    const ro = new ResizeObserver(() => { if (map.current === mp) mp.invalidateSize({pan: false}); });
    ro.observe(el.current);
    // stop any running pan/zoom before removing, or Leaflet's animation callbacks fire on a map that no longer exists
    return () => { ro.disconnect(); map.current = null; mp.stop(); mp.off(); mp.remove(); };
  }, []);

  useEffect(() => {  // follow the page's city when it changes
    if (!fit && !follow && map.current) map.current.setView(center, zoom, {animate: false});
  }, [center[0], center[1], zoom]); // eslint-disable-line

  useEffect(() => {
    const g = layers.current.fences; g.clearLayers();
    if (!showFences) return;
    fences?.features?.forEach(f => {
      const r = f.properties.risk_level || 0, hi = r >= 0.5;
      L.geoJSON(f, {style: {color: hi ? '#D7263D' : '#1E8C5A', weight: hi ? 2 : 1.5, dashArray: hi ? '6 4' : null, fillOpacity: hi ? .18 : .08}})
        .bindTooltip(`<b>${esc(f.properties.name)}</b><br>${esc(f.properties.description || '')}<br>Risk weight ${r.toFixed(2)}`)
        .addTo(g);
    });
  }, [fences, showFences]);

  useEffect(() => {
    const g = layers.current.route; g.clearLayers();
    if (route?.length > 1) L.polyline(route, {color: '#1D2A5B', weight: 3, opacity: .7, dashArray: '2 8', lineCap: 'round'}).addTo(g);
  }, [route]);

  const pinKey = pins.map(p => `${p.id}:${p.num ?? ''}:${p.active ? 1 : 0}:${p.kind}`).join('|') + '/' + (fitPins || []).map(p => p.id).join('|');
  useEffect(() => {
    const g = layers.current.pins; g.clearLayers();
    pins.forEach(p => {
      const icon = L.divIcon({className: '', iconSize: [28, 28], iconAnchor: [14, 14],
        html: `<span class="pin pin-${p.kind || 'place'}${p.active ? ' on' : ''}">${esc(p.num ?? '')}</span>`});
      const mk = L.marker([p.lat, p.lon], {icon, keyboard: true, title: p.label, alt: p.label, zIndexOffset: p.active ? 500 : 0}).addTo(g);
      if (p.label) mk.bindTooltip(esc(p.label), {direction: 'top', offset: [0, -12]});
      if (p.onClick) mk.on('click', p.onClick);
    });
    if (fit && pins.length) {
      const target = fitPins?.length ? fitPins : pins;  // e.g. frame the city, leaving far-off day trips outside the view
      const b = L.latLngBounds(target.map(p => [p.lat, p.lon]));
      map.current?.fitBounds(b, {padding: [36, 36], maxZoom: 15, animate: false});
    }
  }, [pinKey, fit]); // eslint-disable-line

  useEffect(() => {
    const g = layers.current.points; g.clearLayers();
    points.forEach(p => {
      if (p.lat == null) return;
      if (p.trail?.length > 1) L.polyline(p.trail, {color: p.color, weight: 3, opacity: .6}).addTo(g);
      const mk = L.circleMarker([p.lat, p.lon], {radius: p.radius || 8, color: '#fff', weight: 2, fillColor: p.color, fillOpacity: 1}).addTo(g);
      if (p.label) mk.bindTooltip(esc(p.label));
      if (p.onClick) mk.on('click', p.onClick);
    });
    const first = points.find(p => p.lat != null);
    if (first && (follow || !fitted.current) && !pins.length) {
      map.current?.setView([first.lat, first.lon], follow ? Math.max(map.current.getZoom(), 15) : 14, {animate: false});
      fitted.current = true;
    }
  }, [points, follow]); // eslint-disable-line

  return <div ref={el} className="map" style={{height}} role="region" aria-label={label} tabIndex={0}/>;
}
