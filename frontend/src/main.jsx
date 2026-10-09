import React,{useEffect,useState} from 'react';
import {createRoot} from 'react-dom/client';
import Traveller from './Traveller.jsx';
import Ops from './Ops.jsx';
import './style.css';

function App(){
 const [hash,setHash]=useState(location.hash);
 useEffect(()=>{const f=()=>setHash(location.hash);addEventListener('hashchange',f);return()=>removeEventListener('hashchange',f)},[]);
 const ops=hash.startsWith('#/ops');
 return <>
  <nav><a href="#/" className={!ops?'on':''}>Traveller</a><a href="#/ops" className={ops?'on':''}>Operator dashboard</a></nav>
  {ops?<Ops/>:<Traveller/>}
  <footer>Anomaly model flags unusual movement, not crime. Risk score is decision support, not a calibrated probability. The blockchain ID is a private hash-chain ledger holding hashes only; no personal data is stored on it. Demo tourists use synthetic data.</footer>
 </>
}
createRoot(document.getElementById('root')).render(<App/>);
