export const COLORS={LOW:'#2e9e5b',MODERATE:'#e0a100',HIGH:'#d93a3a'};

export async function request(url,{method='GET',body,headers={}}={}){
 const r=await fetch(url,{method,headers:{...(body?{'Content-Type':'application/json'}:{}),...headers},body:body?JSON.stringify(body):undefined});
 if(!r.ok){
  let msg=r.statusText;
  try{const d=await r.json();msg=typeof d.detail==='string'?d.detail:Array.isArray(d.detail)?d.detail.map(x=>`${x.loc?.slice(-1)[0]}: ${x.msg}`).join('; '):msg}catch{}
  const e=new Error(msg);e.status=r.status;throw e;
 }
 return r.json();
}
