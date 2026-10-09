import React,{useEffect,useRef} from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

/** points: [{id,lat,lon,color,radius,label,trail,onClick}] */
export default function MapView({points,fences,center=[23.2599,77.4126],zoom=12,follow=false,height=420}){
 const el=useRef(),map=useRef(),layers=useRef({}),fitted=useRef(false);
 useEffect(()=>{
  map.current=L.map(el.current).setView(center,zoom);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© OpenStreetMap'}).addTo(map.current);
  layers.current.fences=L.layerGroup().addTo(map.current);
  layers.current.points=L.layerGroup().addTo(map.current);
  return()=>map.current.remove();
 },[]);
 useEffect(()=>{
  const g=layers.current.fences;g.clearLayers();
  fences?.features?.forEach(f=>{
   const hi=f.properties.risk_level>=0.5;
   L.geoJSON(f,{style:{color:hi?'#d93a3a':'#2e7dd9',weight:1.5,fillOpacity:.15}})
    .bindTooltip(`${f.properties.name}<br>${f.properties.description||''}`).addTo(g);
  });
 },[fences]);
 useEffect(()=>{
  const g=layers.current.points;g.clearLayers();
  points.forEach(p=>{
   if(p.lat==null)return;
   if(p.trail?.length>1)L.polyline(p.trail,{color:p.color,weight:3,opacity:.6}).addTo(g);
   const mk=L.circleMarker([p.lat,p.lon],{radius:p.radius||8,color:'#fff',weight:2,fillColor:p.color,fillOpacity:1}).addTo(g);
   if(p.label)mk.bindTooltip(p.label);
   if(p.onClick)mk.on('click',p.onClick);
  });
  const first=points.find(p=>p.lat!=null);
  if(first&&(follow||!fitted.current)){map.current.setView([first.lat,first.lon],follow?Math.max(map.current.getZoom(),15):14);fitted.current=true}
 },[points,follow]);
 return <div ref={el} className="map" style={{height}}/>;
}
