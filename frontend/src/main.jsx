import React,{useEffect,useRef,useState,useCallback} from 'react';
import {createRoot} from 'react-dom/client';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import './style.css';

const API='/api';
const COLORS={LOW:'#2e9e5b',MODERATE:'#e0a100',HIGH:'#d93a3a'};
const j=async(url,opt)=>{const r=await fetch(url,opt);if(!r.ok)throw new Error(await r.text());return r.json()};
const post=(u,b)=>j(u,{method:'POST',headers:{'Content-Type':'application/json'},body:b?JSON.stringify(b):undefined});

function MapView({tourists,fences,selected,onSelect}){
 const el=useRef(),map=useRef(),layers=useRef({});
 useEffect(()=>{
  map.current=L.map(el.current).setView([23.2599,77.4126],12);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© OpenStreetMap'}).addTo(map.current);
  layers.current.fences=L.layerGroup().addTo(map.current);
  layers.current.tourists=L.layerGroup().addTo(map.current);
  return()=>map.current.remove();
 },[]);
 useEffect(()=>{
  const g=layers.current.fences;g.clearLayers();
  fences?.features?.forEach(f=>{
   const hi=f.properties.risk_level>=0.5;
   L.geoJSON(f,{style:{color:hi?'#d93a3a':'#2e7dd9',weight:1.5,fillOpacity:.15}}).bindTooltip(`${f.properties.name}<br>${f.properties.description||''}`).addTo(g);
  });
 },[fences]);
 useEffect(()=>{
  const g=layers.current.tourists;g.clearLayers();
  tourists.forEach(t=>{
   if(t.latitude==null)return;
   const c=COLORS[t.risk_level]||'#888';
   if(t.trail.length>1)L.polyline(t.trail,{color:c,weight:3,opacity:.6}).addTo(g);
   L.circleMarker([t.latitude,t.longitude],{radius:t.tourist_id===selected?11:8,color:'#fff',weight:2,fillColor:c,fillOpacity:1})
    .bindTooltip(`${t.name}: ${t.risk_level} (${t.risk_score})`).on('click',()=>onSelect(t.tourist_id)).addTo(g);
  });
 },[tourists,selected]);
 return <div ref={el} className="map"/>;
}

function Factors({f}){
 if(!f)return null;
 return <div className="factors">{Object.entries(f).map(([k,v])=>
  <div key={k} className="frow"><span>{k.replace('_',' ')}</span><div className="bar"><i style={{width:`${Math.round(v*100)}%`}}/></div><b>{v.toFixed(2)}</b></div>)}</div>;
}

function App(){
 const [tourists,setT]=useState([]),[fences,setF]=useState(null),[incidents,setI]=useState([]);
 const [sel,setSel]=useState('T001'),[running,setRun]=useState(true),[err,setErr]=useState(null);
 const refresh=useCallback(async()=>{
  try{const[t,i]=await Promise.all([j(`${API}/tourists`),j(`${API}/incidents`)]);setT(t);setI(i);setErr(null)}
  catch(e){setErr('API unreachable')}
 },[]);
 useEffect(()=>{j(`${API}/geofences`).then(setF).catch(()=>{});refresh()},[refresh]);
 useEffect(()=>{
  if(!running)return;
  const id=setInterval(async()=>{try{await post(`${API}/simulate/step`);await refresh()}catch{setErr('API unreachable')}},2000);
  return()=>clearInterval(id);
 },[running,refresh]);
 const t=tourists.find(x=>x.tourist_id===sel);
 const sos=async()=>{if(!t||t.latitude==null)return;await post(`${API}/sos`,{tourist_id:t.tourist_id,latitude:t.latitude,longitude:t.longitude});refresh()};
 const setStatus=async(id,status)=>{await j(`${API}/incidents/${id}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({status})});refresh()};
 const reset=async()=>{await post(`${API}/simulate/reset`);refresh()};
 return <main>
  <header><div><h1>Team Limitless</h1><p>Smart Tourist Safety Monitoring &amp; Incident Response — Bhopal pilot</p></div>
   <div className="actions"><button onClick={()=>setRun(!running)}>{running?'Pause demo':'Resume demo'}</button><button className="ghost" onClick={reset}>Reset</button></div></header>
  {err&&<div className="err">{err}</div>}
  <div className="grid">
   <section className="card wide"><h2>Live Monitoring <small>(replayed demo trajectories)</small></h2>
    <MapView tourists={tourists} fences={fences} selected={sel} onSelect={setSel}/></section>
   <section className="card"><h2>Tourists</h2>
    {tourists.map(x=><div key={x.tourist_id} className={`trow ${x.tourist_id===sel?'on':''}`} onClick={()=>setSel(x.tourist_id)}>
     <span>{x.name}</span><span className="pill" style={{background:COLORS[x.risk_level]||'#888'}}>{x.risk_level||'—'}</span><b>{x.risk_score??'-'}</b></div>)}
    {t&&<><h3>{t.name} — risk factors</h3><Factors f={t.factors}/><button className="sos" onClick={sos}>Trigger SOS for {t.tourist_id}</button></>}
   </section>
   <section className="card full"><h2>Incidents <small>{incidents.filter(i=>i.status!=='RESOLVED').length} active</small></h2>
    {incidents.length===0?<p className="muted">No incidents.</p>:
    <table><thead><tr><th>#</th><th>Tourist</th><th>Type</th><th>Severity</th><th>Status</th><th>Details</th><th/></tr></thead><tbody>
     {incidents.map(i=><tr key={i.id}><td>{i.id}</td><td>{i.tourist_id}</td><td>{i.incident_type}</td><td>{i.severity}</td><td>{i.status}</td><td>{i.description}</td>
      <td className="acts">{i.status==='OPEN'&&<button onClick={()=>setStatus(i.id,'ACKNOWLEDGED')}>Acknowledge</button>}
       {i.status!=='RESOLVED'&&<button onClick={()=>setStatus(i.id,'RESOLVED')}>Resolve</button>}</td></tr>)}
    </tbody></table>}
   </section>
  </div>
  <footer>Anomaly model flags unusual movement, not crime. Datasets are synthetic; SOS/incidents are controlled demo inputs. Risk score is decision support, not a calibrated probability.</footer>
 </main>
}
createRoot(document.getElementById('root')).render(<App/>);
