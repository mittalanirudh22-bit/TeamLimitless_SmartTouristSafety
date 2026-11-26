import React,{useCallback,useEffect,useRef,useState} from 'react';
import MapView from './MapView.jsx';
import {COLORS,request} from './api.js';
import {cached,useCities} from './lib.js';

const TK='limitless_ops_token';
const getTok=()=>{try{return sessionStorage.getItem(TK)||''}catch{return ''}};

function Factors({f}){
 if(!f)return null;
 return <div className="factors">{Object.entries(f).map(([k,v])=>
  <div key={k} className="frow"><span>{k.replace('_',' ')}</span><div className="bar"><i style={{width:`${Math.round(v*100)}%`}}/></div><b>{v.toFixed(2)}</b></div>)}</div>;
}

function Login({onSubmit,bad}){
 const [v,setV]=useState('');
 return <main><form className="card narrow" onSubmit={e=>{e.preventDefault();onSubmit(v)}}>
  <h2>Operator sign-in</h2><p className="muted">Enter the operator access token (the <code>OPS_TOKEN</code> environment variable on the server).</p>
  <input type="password" value={v} onChange={e=>setV(e.target.value)} placeholder="Operator token" autoFocus/>
  {bad&&<div className="err">Token rejected.</div>}<button>Sign in</button></form></main>
}

export default function Ops(){
 const [tok,setTok]=useState(getTok()),[bad,setBad]=useState(false),[need,setNeed]=useState(false);
 const [tourists,setT]=useState([]),[fences,setF]=useState(null),[incidents,setI]=useState([]),[chain,setC]=useState({blocks:[],ok:null});
 const [sel,setSel]=useState(null),[running,setRun]=useState(true),[err,setErr]=useState(null);
 const {data:cities}=useCities(),[city,setCity]=useState(''),[view,setView]=useState({center:[23.2599,77.4126],zoom:12});
 const H={'X-Ops-Token':tok};
 const call=useCallback((u,o={})=>request(u,{...o,headers:{...H,...(o.headers||{})}}),[tok]);
 const since=useRef(null),tick=useRef(0);
 // Full snapshot every 15th poll (picks up new registrations and status changes); in between, only tourists whose state changed.
 const refresh=useCallback(async()=>{
  try{
   const full=tick.current++%15===0||!since.current;
   const qs=new URLSearchParams({...(city?{city}:{}),...(full?{}:{since:since.current})}).toString();
   const [t,i,v]=await Promise.all([call('/api/tourists'+(qs?'?'+qs:'')),call('/api/incidents'),request('/api/ledger/verify')]);
   if(full)setT(t);else if(t.length){const by=new Map(t.map(x=>[x.tourist_id,x]));setT(old=>old.map(x=>by.get(x.tourist_id)||x))}
   const latest=t.map(x=>x.updated_at).filter(Boolean).sort().pop();
   if(full||latest)since.current=latest&&(!since.current||latest>since.current)?latest:since.current||latest;
   setI(i);setC(c=>({blocks:c.blocks,ok:v}));
   if(full||tick.current%5===1)setC({blocks:await call('/api/ledger?limit=12'),ok:v});
   setErr(null);setNeed(false);
   if(full)setSel(s=>s||t[0]?.tourist_id);
  }catch(e){if(e.status===401){setNeed(true);setBad(!!tok)}else setErr('API unreachable')}
 },[call,tok,city]);
 useEffect(()=>{since.current=null;tick.current=0;setSel(null);refresh()},[refresh]);
 useEffect(()=>{const c=city||'bhopal';request('/api/geofences?city='+c).then(setF).catch(()=>{});
  cached('/api/cities/'+c).then(g=>setView({center:g.center,zoom:g.zoom})).catch(()=>{})},[city]);
 useEffect(()=>{
  if(!running||need)return;
  const id=setInterval(async()=>{try{await call('/api/simulate/step',{method:'POST'});await refresh()}catch(e){if(e.status!==401)setErr('API unreachable')}},2000);
  return()=>clearInterval(id);
 },[running,need,call,refresh]);
 if(need)return <Login bad={bad} onSubmit={v=>{try{sessionStorage.setItem(TK,v)}catch{}setTok(v);setBad(false)}}/>;
 const t=tourists.find(x=>x.tourist_id===sel);
 const setStatus=async(id,status)=>{await call(`/api/incidents/${id}`,{method:'PATCH',body:{status}});refresh()};
 const real=tourists.filter(x=>x.registered);
 return <main>
  <header><div><h1>Operator dashboard</h1><p>Live monitoring and incident response</p></div>
   <div className="actions"><label className="inline-label">City <select value={city} onChange={e=>setCity(e.target.value)}>
    <option value="">All cities</option>{(cities||[]).map(c=><option key={c.slug} value={c.slug}>{c.name}</option>)}</select></label><button onClick={()=>setRun(!running)}>{running?'Pause demo tourists':'Resume demo tourists'}</button></div></header>
  {err&&<div className="err">{err}</div>}
  <div className="grid">
   <section className="card wide"><h2>Live map <small>{real.length} registered traveller(s) · demo tourists replay synthetic trajectories</small></h2>
    <MapView fences={fences} center={view.center} zoom={view.zoom} points={tourists.map(x=>({id:x.tourist_id,lat:x.latitude,lon:x.longitude,color:x.signal==='LOST'?'#6b7385':COLORS[x.risk_level]||'#888',
     radius:x.tourist_id===sel?11:8,label:`${x.name}: ${x.risk_level||'—'} (${x.risk_score??'-'})`,trail:x.trail,onClick:()=>setSel(x.tourist_id)}))}/></section>
   <section className="card"><h2>Tourists</h2>
    <div className="tlist">{tourists.map(x=><div key={x.tourist_id} className={`trow ${x.tourist_id===sel?'on':''}`} onClick={()=>setSel(x.tourist_id)}>
     <span>{x.name}{x.registered&&<small> · {x.status}</small>}{x.signal==='LOST'&&<small className="lost"> · no signal {Math.round(x.last_seen_s/60)} min</small>}</span><span className="pill" style={{background:x.signal==='LOST'?'#6b7385':COLORS[x.risk_level]||'#888'}}>{x.signal==='LOST'?'NO SIGNAL':x.risk_level||'—'}</span><b>{x.risk_score??'-'}</b></div>)}</div>
    {t&&<><h3>{t.name} — risk factors</h3>
     {t.blockchain_id&&<p className="muted small">ID {t.blockchain_id}<br/>Emergency: {t.emergency_name} {t.emergency_phone}</p>}
     <Factors f={t.factors}/></>}
   </section>
   <section className="card full"><h2>Incidents <small>{incidents.filter(i=>i.status!=='RESOLVED').length} active</small></h2>
    {incidents.length===0?<p className="muted">No incidents.</p>:
    <table><thead><tr><th>#</th><th>Tourist</th><th>Type</th><th>Severity</th><th>Status</th><th>Details</th><th/></tr></thead><tbody>
     {incidents.map(i=><tr key={i.id}><td>{i.id}</td><td>{i.tourist_id}</td><td>{i.incident_type}{i.category&&<span className={`cat cat-${i.category}`}>{i.category}</span>}</td><td>{i.severity}</td><td>{i.status}</td><td className="desc">{i.description}{i.message&&i.message.includes('\n')&&<small> ({i.message.split('\n').length} messages)</small>}</td>
      <td className="acts">{i.status==='OPEN'&&<button onClick={()=>setStatus(i.id,'ACKNOWLEDGED')}>Acknowledge</button>}
       {i.status!=='RESOLVED'&&<button onClick={()=>setStatus(i.id,'RESOLVED')}>Resolve</button>}</td></tr>)}
    </tbody></table>}
   </section>
   <section className="card full"><h2>Ledger <small>{chain.ok&&(chain.ok.valid?`✔ chain intact · ${chain.ok.blocks} blocks`:`✖ chain broken at block ${chain.ok.broken_at}`)}</small></h2>
    <table><thead><tr><th>#</th><th>Type</th><th>Ref</th><th>Time</th><th>Hash</th></tr></thead><tbody>
     {chain.blocks.map(b=><tr key={b.index}><td>{b.index}</td><td>{b.type}</td><td>{b.ref}</td><td>{new Date(b.timestamp).toLocaleString()}</td><td className="mono">{b.hash.slice(0,20)}…</td></tr>)}
    </tbody></table>
   </section>
  </div>
 </main>
}
