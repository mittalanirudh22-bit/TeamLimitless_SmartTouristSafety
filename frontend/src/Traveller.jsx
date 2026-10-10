import React,{useCallback,useEffect,useRef,useState} from 'react';
import MapView from './MapView.jsx';
import {COLORS,request} from './api.js';

const KEY='limitless_session';
const load=()=>{try{return JSON.parse(localStorage.getItem(KEY))}catch{return null}};
const save=s=>{try{s?localStorage.setItem(KEY,JSON.stringify(s)):localStorage.removeItem(KEY)}catch{}};

function Register({onDone}){
 const [f,setF]=useState({full_name:'',nationality:'',phone:'',email:'',emergency_name:'',emergency_phone:'',consent:false});
 const [err,setErr]=useState(null),[busy,setBusy]=useState(false);
 const set=k=>e=>setF({...f,[k]:e.target.type==='checkbox'?e.target.checked:e.target.value});
 const submit=async e=>{
  e.preventDefault();setErr(null);setBusy(true);
  try{
   const body={...f,email:f.email||null};
   const r=await request('/api/travellers/register',{method:'POST',body});
   save({token:r.tracking_token,tourist_id:r.tourist_id});onDone(r.tracking_token);
  }catch(x){setErr(x.message)}finally{setBusy(false)}
 };
 return <form className="card narrow" onSubmit={submit}>
  <h2>Register as a traveller</h2>
  <p className="muted">Register once to receive your blockchain ID. After that you can choose to start live safety tracking.</p>
  <label>Full name<input required minLength={2} maxLength={80} value={f.full_name} onChange={set('full_name')} autoComplete="name"/></label>
  <label>Nationality<input required minLength={2} maxLength={60} value={f.nationality} onChange={set('nationality')}/></label>
  <label>Phone<input required value={f.phone} onChange={set('phone')} placeholder="+91 98765 43210" inputMode="tel" autoComplete="tel"/></label>
  <label>Email <small>(optional)</small><input type="email" value={f.email} onChange={set('email')} autoComplete="email"/></label>
  <h3>Emergency contact</h3>
  <label>Name<input required minLength={2} maxLength={80} value={f.emergency_name} onChange={set('emergency_name')}/></label>
  <label>Phone<input required value={f.emergency_phone} onChange={set('emergency_phone')} placeholder="+91 …" inputMode="tel"/></label>
  <label className="check"><input type="checkbox" checked={f.consent} onChange={set('consent')}/>
   <span>I consent to my location being collected while tracking is on, and shared with safety operators and my emergency contact if there is an incident. I can stop tracking at any time.</span></label>
  {err&&<div className="err">{err}</div>}
  <button disabled={busy||!f.consent}>{busy?'Registering…':'Register & get my ID'}</button>
 </form>
}

function IdCard({me,onStart,busy}){
 return <section className="card narrow">
  <h2>Your traveller ID</h2>
  <div className="idcard">
   <small>Blockchain ID</small><div className="chainid">{me.blockchain_id}</div>
   <div className="idrow"><span>{me.name}</span><span>{me.nationality}</span></div>
   <small>Registered {new Date(me.registered_at).toLocaleString()} · Ref {me.tourist_id}</small>
  </div>
  <p className="muted">Anyone can check this ID is genuine at the bottom of this page. Save it; your tracking login is kept in this browser.</p>
  <button onClick={onStart} disabled={busy}>{me.status==='STOPPED'?'Resume tracking':'Start tracking'}</button>
  <p className="muted small">Tracking uses your phone's GPS while this page is open, so keep it open and the screen on.</p>
 </section>
}

// demo walk: ~4.5 km/h, one fix per tick, virtual time advancing 15s per tick
function demoStep(s){
 const T=[23.2330,77.3990];
 const k=Math.cos(s.lat*Math.PI/180),dy=(T[0]-s.lat)*111000,dx=(T[1]-s.lon)*111000*k,d=Math.hypot(dx,dy)||1,m=19;
 s.lat+=dy/d*m/111000+(Math.random()-.5)*2e-5;s.lon+=dx/d*m/(111000*k)+(Math.random()-.5)*2e-5;
 s.ts+=15000;return s;
}

function Tracking({token,me,refresh,fences,onStop}){
 const [gps,setGps]=useState('Waiting for GPS…'),[demo,setDemo]=useState(false),[note,setNote]=useState(null);
 const last=useRef(0),sent=useRef(null),pos=useRef(null);
 const send=useCallback(async(lat,lon,accuracy,ts)=>{
  try{
   const body={latitude:lat,longitude:lon,...(accuracy!=null?{accuracy}:{}),...(ts?{timestamp:new Date(ts).toISOString()}:{})};
   const r=await request('/api/travellers/me/location',{method:'POST',body,headers:{'X-Tracking-Token':token}});
   if(r.ignored)setGps(`Weak GPS signal (±${Math.round(r.accuracy_m)} m) — fix skipped`);
  }catch(e){setGps(`Could not send location: ${e.message}`)}
 },[token]);
 useEffect(()=>{
  if(demo){
   setGps('Demo movement (simulated, not your real location)');
   const s=pos.current&&pos.current.demo?pos.current:{demo:1,lat:me.latitude??23.2560,lon:me.longitude??77.3370,ts:Date.now()};
   pos.current=s;
   const id=setInterval(()=>{const p=demoStep(s);send(p.lat,p.lon,5,p.ts)},2000);
   return()=>clearInterval(id);
  }
  if(!navigator.geolocation){setGps('This device has no GPS support. Use demo movement to try it.');return}
  const id=navigator.geolocation.watchPosition(p=>{
   setGps(`GPS active (±${Math.round(p.coords.accuracy)} m)`);
   // Adaptive rate: at most one fix per 5 s while moving; a stationary phone sends a heartbeat every 30 s
   // (enough to keep inactivity detection correct) instead of a fix every few seconds.
   const now=Date.now(),{latitude:la,longitude:lo,accuracy:ac}=p.coords,prev=sent.current;
   if(now-last.current<5000)return;
   const moved=prev?Math.hypot((la-prev.la)*111000,(lo-prev.lo)*111000*Math.cos(la*Math.PI/180)):Infinity;
   if(moved<10&&now-last.current<30000)return;
   last.current=now;sent.current={la,lo};send(la,lo,ac);
  },e=>setGps(e.code===1?'Location permission denied — allow it in your browser settings, or use demo movement.':'GPS unavailable: '+e.message),
  {enableHighAccuracy:true,maximumAge:2000,timeout:20000});
  return()=>navigator.geolocation.clearWatch(id);
 },[demo,send]);
 useEffect(()=>{const id=setInterval(refresh,3000);return()=>clearInterval(id)},[refresh]);
 const sos=async()=>{
  if(me.latitude==null){setNote('No location yet — wait for a GPS fix, then press SOS.');return}
  if(!confirm('Send an SOS alert to safety operators with your current location?'))return;
  try{await request('/api/travellers/me/sos',{method:'POST',body:{latitude:me.latitude,longitude:me.longitude},headers:{'X-Tracking-Token':token}});setNote('SOS sent. Operators have been alerted.');refresh()}
  catch(e){setNote('SOS failed: '+e.message)}
 };
 const lvl=me.risk_level;
 return <div className="trackgrid">
  <section className="card">
   <h2>Live tracking <small>{gps}</small></h2>
   <MapView follow height={380} fences={fences}
    points={me.latitude==null?[]:[{id:'me',lat:me.latitude,lon:me.longitude,color:COLORS[lvl]||'#2e5bd9',radius:10,label:'You',trail:me.trail}]}/>
  </section>
  <section className="card">
   <h2>Your safety status</h2>
   <div className="status" style={{background:COLORS[lvl]||'var(--bg)',color:lvl?'#fff':'inherit'}}>
    <div className="big">{lvl||'—'}</div><div>{me.risk_score!=null?`risk score ${me.risk_score}`:'waiting for first location'}</div></div>
   {me.incidents?.length>0&&<div className="err">{me.incidents.length} active incident(s) — operators notified</div>}
   <p className="muted small">ID <b>{me.blockchain_id}</b></p>
   <button className="sos" onClick={sos}>SOS — I need help</button>
   {note&&<p className="note">{note}</p>}
   <label className="check"><input type="checkbox" checked={demo} onChange={e=>setDemo(e.target.checked)}/><span>Use demo movement (simulated walk, for testing without GPS)</span></label>
   <button className="ghost" onClick={onStop}>Stop tracking</button>
   <p className="muted small">Emergency contact: {me.emergency_name} · {me.emergency_phone}</p>
  </section>
 </div>
}

function Verify(){
 const [id,setId]=useState(''),[res,setRes]=useState(null),[err,setErr]=useState(null);
 const go=async e=>{e.preventDefault();setErr(null);setRes(null);
  try{setRes(await request('/api/verify/'+encodeURIComponent(id.trim())))}catch(x){setErr(x.message)}};
 return <section className="card narrow">
  <h3>Verify a blockchain ID</h3>
  <form className="inline" onSubmit={go}><input value={id} onChange={e=>setId(e.target.value)} placeholder="TLB-XXXX-XXXX-XXXX-XXXX" required/><button>Verify</button></form>
  {err&&<p className="note">{err}</p>}
  {res&&<p className="note">{res.id_matches_block&&res.chain_valid?'✔ Genuine':'✖ Does not verify'} — registered {new Date(res.registered_at).toLocaleString()}, ledger block #{res.block_index}, chain {res.chain_valid?'intact':'BROKEN'} ({res.chain_length} blocks).</p>}
 </section>
}

export default function Traveller(){
 const [session,setSession]=useState(load()),[me,setMe]=useState(null),[fences,setF]=useState(null),[busy,setBusy]=useState(false),[err,setErr]=useState(null);
 const token=session?.token;
 const refresh=useCallback(async()=>{
  if(!token)return;
  try{setMe(await request('/api/travellers/me',{headers:{'X-Tracking-Token':token}}));setErr(null)}
  catch(e){if(e.status===401){save(null);setSession(null);setMe(null)}else setErr('Cannot reach the server')}
 },[token]);
 useEffect(()=>{refresh()},[refresh]);
 useEffect(()=>{request('/api/geofences').then(setF).catch(()=>{})},[]);
 const act=async path=>{setBusy(true);try{setMe(await request('/api/travellers/me/'+path,{method:'POST',headers:{'X-Tracking-Token':token}}))}catch(e){setErr(e.message)}finally{setBusy(false)}};
 const logout=()=>{if(confirm('Remove this ID from this browser? You will not be able to track again without registering anew.')){save(null);setSession(null);setMe(null)}};
 return <main>
  <header><div><h1>Team Limitless</h1><p>Smart tourist safety — register, get your blockchain ID, travel with live safety tracking</p></div>
   {session&&<button className="ghost" onClick={logout}>Sign out of this device</button>}</header>
  {err&&<div className="err">{err}</div>}
  {!session&&<Register onDone={t=>setSession(load())}/>}
  {session&&!me&&<p className="muted">Loading…</p>}
  {me&&me.status==='TRACKING'?<Tracking token={token} me={me} refresh={refresh} fences={fences} onStop={()=>act('stop')}/>
   :me&&<IdCard me={me} busy={busy} onStart={()=>act('start')}/>}
  <Verify/>
 </main>
}
