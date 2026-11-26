import React, {useEffect, useRef, useState} from 'react';
import {request} from './api.js';
import {recall, store} from './lib.js';

/** sms: link with a ready-written SOS. Works with no mobile data, as long as there is phone signal. */
export function smsSos(me) {
  const where = me.latitude != null ? ` My location: https://maps.google.com/?q=${me.latitude.toFixed(5)},${me.longitude.toFixed(5)}` : '';
  const text = `SOS from ${me.name} (Safe Tour ID ${me.blockchain_id}). I need help.${where}`;
  return `sms:${(me.emergency_phone || '').replace(/[^\d+]/g, '')}?&body=${encodeURIComponent(text)}`;
}

export function OfflineSos({me}) {
  return <div className="offline-sos">
    <p><b>No internet?</b> Text your SOS and location to {me.emergency_name || 'your emergency contact'} instead, or call 112.</p>
    <p className="actions"><a className="button sos-sms" href={smsSos(me)}>Text SOS to {me.emergency_name || 'contact'}</a>
      <a className="button ghost" href="tel:112">Call 112</a></p>
  </div>;
}

const QUICK = {
  en: [['Medical help', 'I need medical help'], ['Someone is following me', 'Someone is following me'], ['Theft', 'My things were stolen'],
       ['I am lost', 'I am lost and cannot find my way'], ['Accident', 'There has been an accident']],
  hi: [['डॉक्टर चाहिए', 'मुझे डॉक्टर चाहिए'], ['कोई पीछा कर रहा है', 'कोई मेरा पीछा कर रहा है'], ['चोरी', 'मेरा सामान चोरी हो गया'],
       ['रास्ता भटक गया', 'मैं रास्ता भटक गया हूँ'], ['एक्सीडेंट', 'एक्सीडेंट हो गया है']],
};
const Speech = typeof window !== 'undefined' && (window.SpeechRecognition || window.webkitSpeechRecognition);

/** After SOS: tell the safety team what's happening by tapping, typing or speaking, in English or Hindi. */
export function SosDetails({token, onSent}) {
  const [lang, setLang] = useState('en'), [text, setText] = useState(''), [listening, setListening] = useState(false);
  const [result, setResult] = useState(null), [err, setErr] = useState(null), [busy, setBusy] = useState(false);
  const rec = useRef(null);
  useEffect(() => () => rec.current?.abort?.(), []);
  const send = async t => {
    if (!t.trim()) return;
    setBusy(true); setErr(null);
    try {
      const r = await request('/api/travellers/me/sos/message', {method: 'POST', body: {text: t}, headers: {'X-Tracking-Token': token}});
      setResult(r.triage); setText(''); onSent?.();
    } catch (e) { setErr(e.status ? e.message : 'No internet. Use "Text SOS" below instead.'); }
    finally { setBusy(false); }
  };
  const listen = () => {
    if (listening) { rec.current?.stop(); return; }
    const r = rec.current = new Speech();
    r.lang = lang === 'hi' ? 'hi-IN' : 'en-IN'; r.interimResults = true; r.maxAlternatives = 1;
    r.onresult = e => setText(Array.from(e.results).map(x => x[0].transcript).join(' '));
    r.onerror = e => { setErr(e.error === 'not-allowed' ? 'Microphone permission denied. Type instead.' : 'Could not hear that. Try again or type.'); setListening(false); };
    r.onend = () => setListening(false);
    setErr(null); setListening(true); r.start();
  };
  return <div className="sos-details" aria-live="polite">
    <h3>Tell the safety team what's happening</h3>
    <div className="lang-toggle" role="group" aria-label="Language">
      <button className={lang === 'en' ? 'chip on' : 'chip'} aria-pressed={lang === 'en'} onClick={() => setLang('en')}>English</button>
      <button className={lang === 'hi' ? 'chip on' : 'chip'} aria-pressed={lang === 'hi'} onClick={() => setLang('hi')}>हिंदी</button>
    </div>
    <div className="chips">{QUICK[lang].map(([label, msg]) => <button key={label} className="chip" disabled={busy} onClick={() => send(msg)}>{label}</button>)}</div>
    <label><span className="sr-only">Describe what's happening</span>
      <textarea rows={3} value={text} onChange={e => setText(e.target.value)} maxLength={500}
        placeholder={lang === 'hi' ? 'क्या हो रहा है? आप कहाँ हैं?' : "What's happening? Where are you?"}/></label>
    <p className="actions">
      {Speech && <button className={listening ? 'listening' : 'ghost'} onClick={listen} aria-pressed={listening}>{listening ? 'Listening… tap to stop' : 'Speak'}</button>}
      <button onClick={() => send(text)} disabled={busy || !text.trim()}>Send to safety team</button>
    </p>
    {result && <p className="note">Understood as <b>{({medical: 'Medical', harassment: 'Harassment or assault', theft: 'Theft or robbery', lost: 'Lost or stranded', accident: 'Accident or fall', other: 'Unspecified'})[result.category]}</b>
      {result.urgent && ', possibly life-threatening'}{result.places.length > 0 && <> near <b>{result.places.map(p => p.name).join(', ')}</b></>}. The safety team can see your message.</p>}
    {err && <p className="err">{err}</p>}
    {Speech && <p className="muted small">Speech is turned into text by your browser's speech service.</p>}
  </div>;
}

const shareUrl = token => `${location.origin}${location.pathname}#/share/${token}`;

/** Expiring, view-only links to the traveller's live location, for family. */
export function FamilyShare({token, me}) {
  const key = `safetour_share_${me.tourist_id}`;
  const [links, setLinks] = useState([]), [hours, setHours] = useState(24), [note, setNote] = useState(null), [err, setErr] = useState(null);
  const tokens = () => recall(key, {});
  const load = async () => {
    try { setLinks(await request('/api/travellers/me/share', {headers: {'X-Tracking-Token': token}})); } catch { /* offline */ }
  };
  useEffect(() => { load(); }, [token]); // eslint-disable-line
  const create = async () => {
    setErr(null);
    try {
      const r = await request('/api/travellers/me/share', {method: 'POST', body: {hours}, headers: {'X-Tracking-Token': token}});
      store(key, {...tokens(), [r.id]: r.token}); await load();
    } catch (e) { setErr(e.message); }
  };
  const stop = async id => {
    await request(`/api/travellers/me/share/${id}`, {method: 'DELETE', headers: {'X-Tracking-Token': token}}).catch(() => {});
    const t = tokens(); delete t[id]; store(key, t); load();
  };
  const copy = async url => {
    try { await navigator.clipboard.writeText(url); setNote('Link copied. Send it to your family.'); } catch { setNote(url); }
  };
  return <section className="card family-share">
    <h2>Share your live location with family</h2>
    <p className="muted">They see where you are, whether your phone has signal, and if you press SOS. They don't see your phone number or ID.</p>
    <p className="actions"><label className="inline-label">For <select value={hours} onChange={e => setHours(+e.target.value)}>
      <option value={6}>6 hours</option><option value={24}>1 day</option><option value={72}>3 days</option></select></label>
      <button onClick={create}>Create a link</button></p>
    {links.length > 0 && <ul className="share-list">{links.map(l => {
      const t = tokens()[l.id], url = t && shareUrl(t);
      const wa = url && `https://wa.me/?text=${encodeURIComponent(`Follow my trip live on Safe Tour: ${url}`)}`;
      return <li key={l.id}>
        <span>Link {l.id} <small>until {new Date(l.expires_at).toLocaleString('en-IN', {day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit'})}</small></span>
        <span className="actions">
          {url ? <><button className="ghost small" onClick={() => copy(url)}>Copy link</button>
            <a className="small" href={wa} target="_blank" rel="noreferrer">Send on WhatsApp</a></>
            : <small>Created on another device</small>}
          <button className="ghost small" onClick={() => stop(l.id)}>Stop sharing</button></span>
      </li>;
    })}</ul>}
    {note && <p className="note">{note}</p>}{err && <p className="err">{err}</p>}
  </section>;
}
